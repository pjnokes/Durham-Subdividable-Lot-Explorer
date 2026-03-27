"""
Batch Analysis Pipeline — run geometric subdivision analysis on all subdividable parcels.

Each worker process receives only parcel IDs, opens its own DB connection,
loads geometry locally, and writes results back. This avoids serializing
large WKB blobs through multiprocessing on Windows.
"""

from __future__ import annotations

import json
import math
import multiprocessing
import os
import sys
import time
import traceback
from dataclasses import dataclass
from typing import Optional

import psycopg2
from dotenv import load_dotenv
from shapely import wkb
from shapely.geometry import mapping, MultiPolygon, MultiLineString

load_dotenv()
DB_URL = os.environ["DATABASE_URL"]

NUM_WORKERS = min(8, max(1, (os.cpu_count() or 4) - 2))


@dataclass
class AnalysisResult:
    parcel_id: int
    is_subdividable: bool
    subdivision_type: str | None
    num_possible_lots: int
    min_new_lot_area_sqft: float | None
    max_structure_footprint_sqft: float | None
    confidence_score: float
    proposed_lots_geojson: str | None
    proposed_lot_lines_geojson: str | None
    proposed_structures_geojson: str | None
    existing_structure_conflict: bool
    notes: str


def _load_and_analyze(parcel_id: int, conn) -> AnalysisResult:
    """Load a single parcel from DB and run full geometric analysis."""
    from backend.analysis.lot_splitter import split_parcel
    from backend.analysis.flag_lot import try_flag_lot
    from backend.analysis.structure_fitter import fit_structure
    from backend.analysis.street_access import (
        load_nearby_streets,
        check_lot_street_access,
        check_pole_reaches_street,
    )
    from backend.udo.rules_engine import get_district_rules

    cur = conn.cursor()
    cur.execute("""
        SELECT p.zoning, p.area_sqft, ST_AsBinary(p.geom_stateplane),
               sa.quick_filter_result, sa.subdivision_type,
               p.heated_area, sa.num_street_frontages
        FROM parcels p
        JOIN subdivision_analysis sa ON sa.parcel_id = p.id
        WHERE p.id = %s AND p.geom_stateplane IS NOT NULL
    """, (parcel_id,))
    row = cur.fetchone()
    if row is None:
        return AnalysisResult(
            parcel_id=parcel_id, is_subdividable=False, subdivision_type=None,
            num_possible_lots=0, min_new_lot_area_sqft=None,
            max_structure_footprint_sqft=None, confidence_score=0.0,
            proposed_lots_geojson=None, proposed_lot_lines_geojson=None,
            proposed_structures_geojson=None, existing_structure_conflict=False,
            notes="Parcel not found or missing geometry",
        )

    zoning, area_sqft, geom_sp_wkb, qf_result, sub_type, heated_area, num_frontages = row

    if qf_result == "EXCLUDED_OWNER":
        return AnalysisResult(
            parcel_id=parcel_id, is_subdividable=False, subdivision_type=None,
            num_possible_lots=0, min_new_lot_area_sqft=None,
            max_structure_footprint_sqft=None, confidence_score=0.0,
            proposed_lots_geojson=None, proposed_lot_lines_geojson=None,
            proposed_structures_geojson=None, existing_structure_conflict=False,
            notes="Excluded owner (government/institutional)",
        )

    geom_sp = wkb.loads(bytes(geom_sp_wkb))

    rules = get_district_rules(zoning)
    if rules is None:
        return AnalysisResult(
            parcel_id=parcel_id, is_subdividable=False, subdivision_type=None,
            num_possible_lots=0, min_new_lot_area_sqft=None,
            max_structure_footprint_sqft=None, confidence_score=0.0,
            proposed_lots_geojson=None, proposed_lot_lines_geojson=None,
            proposed_structures_geojson=None, existing_structure_conflict=False,
            notes="Not residential zoning",
        )

    # Load building footprints
    cur.execute("""
        SELECT ST_AsBinary(bf.geom_stateplane)
        FROM building_footprints bf
        WHERE bf.parcel_id = %s AND bf.geom_stateplane IS NOT NULL
    """, (parcel_id,))
    existing_buildings = []
    for (bwkb_row,) in cur.fetchall():
        try:
            existing_buildings.append(wkb.loads(bytes(bwkb_row)))
        except Exception:
            pass

    primary_structure = None
    accessory_structures = []
    if existing_buildings:
        existing_buildings.sort(key=lambda g: g.area, reverse=True)
        primary_structure = existing_buildings[0]
        accessory_structures = existing_buildings[1:]

    # If there's a known structure (heated_area > 0) but no footprint geometry,
    # we can't verify that split lines avoid the building. Skip analysis.
    if primary_structure is None and heated_area and heated_area > 0:
        return AnalysisResult(
            parcel_id=parcel_id, is_subdividable=False, subdivision_type=None,
            num_possible_lots=1, min_new_lot_area_sqft=area_sqft,
            max_structure_footprint_sqft=None, confidence_score=0.0,
            proposed_lots_geojson=None, proposed_lot_lines_geojson=None,
            proposed_structures_geojson=None, existing_structure_conflict=False,
            notes="Missing building footprint — cannot verify structure safety",
        )

    # --- Load nearby streets for real street-access validation ---
    nearby_streets = load_nearby_streets(geom_sp, conn)

    # If no streets are within range, parcel has no street access at all
    if not nearby_streets:
        return AnalysisResult(
            parcel_id=parcel_id, is_subdividable=False, subdivision_type=None,
            num_possible_lots=1, min_new_lot_area_sqft=area_sqft,
            max_structure_footprint_sqft=None, confidence_score=0.0,
            proposed_lots_geojson=None, proposed_lot_lines_geojson=None,
            proposed_structures_geojson=None, existing_structure_conflict=False,
            notes="No street access — parcel not adjacent to any road",
        )

    # --- Try splitting strategies ---
    best_result = None

    # 1. Standard / small lot split — creates side-by-side lots, each with
    #    street frontage.  Works for any lot that has at least one street edge.
    split_result = split_parcel(
        geom_sp, zoning, area_sqft, primary_structure=primary_structure,
        nearby_streets=nearby_streets,
    )
    if split_result and split_result.num_lots >= 2:
        best_result = split_result

    # 2. Flag lot (for interior lots, or when standard split didn't yield 2+)
    if best_result is None or best_result.num_lots < 2:
        flag_result = try_flag_lot(
            geom_sp, zoning, primary_structure=primary_structure,
            nearby_streets=nearby_streets,
        )
        if flag_result and flag_result.success:
            lots = []
            structures = []

            if flag_result.front_lot:
                lots.append(flag_result.front_lot)
            if flag_result.rear_lot:
                lots.append(flag_result.rear_lot)

            # Only propose new structures on lots that don't hold the primary
            for lot_geom, fit in [
                (flag_result.front_lot, flag_result.front_structure),
                (flag_result.rear_lot, flag_result.rear_structure),
            ]:
                if fit and fit.footprint_geom:
                    if primary_structure and lot_geom and lot_geom.contains(primary_structure):
                        continue
                    structures.append(fit.footprint_geom)

            # Check conflicts before adding pole to lots list
            struct_conflict = False
            conflict_notes = ""
            actual_lots = [l for l in lots if l is not None]
            if primary_structure and actual_lots:
                for lot in actual_lots:
                    if primary_structure.intersects(lot) and not lot.contains(primary_structure):
                        struct_conflict = True
                        conflict_notes = "; primary structure spans lot line"

            # Validate flag lot street access with real street data
            # UDO: front lot must have min_lot_width_ft of frontage
            # UDO: pole must be at least min_pole_width_ft (20 ft)
            if nearby_streets:
                front_access = check_lot_street_access(
                    flag_result.front_lot, nearby_streets,
                    min_frontage_ft=rules.min_lot_width_ft,
                )
                if not front_access.has_access:
                    # Front lot doesn't reach a street — reject
                    return AnalysisResult(
                        parcel_id=parcel_id, is_subdividable=False, subdivision_type=None,
                        num_possible_lots=1, min_new_lot_area_sqft=area_sqft,
                        max_structure_footprint_sqft=None, confidence_score=0.0,
                        proposed_lots_geojson=None, proposed_lot_lines_geojson=None,
                        proposed_structures_geojson=None, existing_structure_conflict=False,
                        notes="Flag lot rejected — front lot has no real street access",
                    )
                # Pole must connect to a real street
                if flag_result.pole and not check_pole_reaches_street(flag_result.pole, nearby_streets):
                    return AnalysisResult(
                        parcel_id=parcel_id, is_subdividable=False, subdivision_type=None,
                        num_possible_lots=1, min_new_lot_area_sqft=area_sqft,
                        max_structure_footprint_sqft=None, confidence_score=0.0,
                        proposed_lots_geojson=None, proposed_lot_lines_geojson=None,
                        proposed_structures_geojson=None, existing_structure_conflict=False,
                        notes="Flag lot rejected — pole does not reach a real street",
                    )

            # Include pole as part of proposed_lots so the flag shape renders
            if flag_result.pole and not flag_result.pole.is_empty:
                lots.append(flag_result.pole)
            lots_multi = MultiPolygon(lots) if lots else None
            struct_multi = MultiPolygon(structures) if structures else None

            notes = f"Flag lot subdivision viable (pole on {'left/right/center'})"
            if flag_result.notes:
                notes = f"Flag lot: {flag_result.notes}"
            if conflict_notes:
                notes += conflict_notes

            return AnalysisResult(
                parcel_id=parcel_id,
                is_subdividable=True,
                subdivision_type="flag_lot",
                num_possible_lots=2,
                min_new_lot_area_sqft=min(flag_result.front_area_sqft, flag_result.rear_area_sqft),
                max_structure_footprint_sqft=max(
                    flag_result.front_structure.area_sqft if flag_result.front_structure else 0,
                    flag_result.rear_structure.area_sqft if flag_result.rear_structure else 0,
                ),
                confidence_score=0.7,
                proposed_lots_geojson=json.dumps(mapping(lots_multi)) if lots_multi else None,
                proposed_lot_lines_geojson=None,
                proposed_structures_geojson=json.dumps(mapping(struct_multi)) if struct_multi else None,
                existing_structure_conflict=struct_conflict,
                notes=notes,
            )

    if best_result and best_result.num_lots >= 2:
        # UDO: every lot must abut a public street with min_lot_width_ft frontage
        # For small lots, UDO requires 25 ft; for standard, district min_lot_width_ft
        if nearby_streets:
            if best_result.subdivision_type == "small_lot":
                required_frontage = 25.0  # UDO small_lot_option.min_lot_width_ft
            else:
                required_frontage = rules.min_lot_width_ft
            for lot in best_result.lots:
                lot_access = check_lot_street_access(
                    lot, nearby_streets,
                    min_frontage_ft=required_frontage,
                )
                if not lot_access.has_access:
                    best_result = None
                    break

    if best_result and best_result.num_lots >= 2:
        structure_fits = []
        for lot in best_result.lots:
            # Skip fitting a new structure on the lot that contains the primary
            if primary_structure and lot.contains(primary_structure):
                continue
            fit = fit_structure(lot, zoning, best_result.subdivision_type or "standard")
            if fit:
                structure_fits.append(fit)

        lots_multi = MultiPolygon(best_result.lots) if best_result.lots else None
        lines_multi = MultiLineString(best_result.lot_lines) if best_result.lot_lines else None
        struct_polys = [f.footprint_geom for f in structure_fits if f.footprint_geom]
        struct_multi = MultiPolygon(struct_polys) if struct_polys else None

        min_area = min(lot.area for lot in best_result.lots) if best_result.lots else None
        max_struct = max((f.area_sqft for f in structure_fits if f.area_sqft), default=None)

        struct_conflict = False
        conflict_notes = []
        if primary_structure and best_result.lots:
            for i, lot in enumerate(best_result.lots):
                if primary_structure.intersects(lot) and not lot.contains(primary_structure):
                    struct_conflict = True
                    conflict_notes.append(f"primary structure spans lot {i+1} boundary")

        demo_count = 0
        if accessory_structures and best_result.lot_lines:
            for acc in accessory_structures:
                for line in best_result.lot_lines:
                    if acc.intersects(line):
                        demo_count += 1
                        break

        notes_parts = [f"{best_result.num_lots} lots via {best_result.subdivision_type}"]
        if primary_structure:
            for i, lot in enumerate(best_result.lots):
                if lot.contains(primary_structure):
                    notes_parts.append(f"existing structure kept on lot {i+1}")
                    break
        if struct_conflict:
            notes_parts.append("; ".join(conflict_notes))
        if demo_count:
            notes_parts.append(f"{demo_count} accessory structure(s) may need removal")

        return AnalysisResult(
            parcel_id=parcel_id,
            is_subdividable=True,
            subdivision_type=best_result.subdivision_type,
            num_possible_lots=best_result.num_lots,
            min_new_lot_area_sqft=min_area,
            max_structure_footprint_sqft=max_struct,
            confidence_score=min(best_result.score / 50, 1.0),
            proposed_lots_geojson=json.dumps(mapping(lots_multi)) if lots_multi else None,
            proposed_lot_lines_geojson=json.dumps(mapping(lines_multi)) if lines_multi else None,
            proposed_structures_geojson=json.dumps(mapping(struct_multi)) if struct_multi else None,
            existing_structure_conflict=struct_conflict,
            notes="; ".join(notes_parts),
        )

    return AnalysisResult(
        parcel_id=parcel_id,
        is_subdividable=False,
        subdivision_type=None,
        num_possible_lots=1,
        min_new_lot_area_sqft=area_sqft,
        max_structure_footprint_sqft=None,
        confidence_score=0.3,
        proposed_lots_geojson=None,
        proposed_lot_lines_geojson=None,
        proposed_structures_geojson=None,
        existing_structure_conflict=False,
        notes="Geometric analysis found no viable subdivision",
    )


def _store_result(conn, result: AnalysisResult):
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE subdivision_analysis SET
            is_subdividable = %(is_subdividable)s,
            subdivision_type = %(subdivision_type)s,
            num_possible_lots = %(num_possible_lots)s,
            min_new_lot_area_sqft = %(min_new_lot_area_sqft)s,
            max_structure_footprint_sqft = %(max_structure_footprint_sqft)s,
            confidence_score = %(confidence_score)s,
            proposed_lots = CASE WHEN %(proposed_lots)s IS NOT NULL
                THEN ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%(proposed_lots)s), 2264), 4326)
                ELSE NULL END,
            proposed_lot_lines = CASE WHEN %(proposed_lot_lines)s IS NOT NULL
                THEN ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%(proposed_lot_lines)s), 2264), 4326)
                ELSE NULL END,
            proposed_structures = CASE WHEN %(proposed_structures)s IS NOT NULL
                THEN ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%(proposed_structures)s), 2264), 4326)
                ELSE NULL END,
            existing_structure_conflict = %(existing_structure_conflict)s,
            notes = %(notes)s,
            analyzed_at = NOW()
        WHERE parcel_id = %(parcel_id)s
        """,
        {
            "parcel_id": result.parcel_id,
            "is_subdividable": result.is_subdividable,
            "subdivision_type": result.subdivision_type,
            "num_possible_lots": result.num_possible_lots,
            "min_new_lot_area_sqft": result.min_new_lot_area_sqft,
            "max_structure_footprint_sqft": result.max_structure_footprint_sqft,
            "confidence_score": result.confidence_score,
            "proposed_lots": result.proposed_lots_geojson,
            "proposed_lot_lines": result.proposed_lot_lines_geojson,
            "proposed_structures": result.proposed_structures_geojson,
            "existing_structure_conflict": result.existing_structure_conflict,
            "notes": result.notes,
        },
    )


def _worker_process(parcel_ids: list[int], worker_id: int) -> dict:
    """
    Worker function: each process gets a chunk of parcel IDs,
    opens its own DB connection, loads data, analyzes, and stores results.
    Returns a summary dict.
    """
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False

    counts = {"ok": 0, "no": 0, "err": 0}
    batch_n = 0

    PER_PARCEL_TIMEOUT = 30  # seconds

    for pid in parcel_ids:
        t_start = time.time()
        try:
            result = _load_and_analyze(pid, conn)
            dt = time.time() - t_start
            if dt > PER_PARCEL_TIMEOUT:
                counts["err"] += 1
                batch_n += 1
                continue
            _store_result(conn, result)
            batch_n += 1

            if result.is_subdividable:
                counts["ok"] += 1
            elif "error" in (result.notes or "").lower():
                counts["err"] += 1
            else:
                counts["no"] += 1

            if batch_n % 50 == 0:
                conn.commit()

        except Exception as e:
            counts["err"] += 1
            try:
                conn.rollback()
            except Exception:
                pass

    try:
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

    return counts


def run(max_workers: int = 1, limit: int | None = None, corner_first: bool = True):
    """Run geometric analysis in a single process."""
    print(f"Batch processor — single-threaded on {os.cpu_count()} cores", flush=True)

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    order_clause = "ORDER BY sa.num_street_frontages DESC NULLS LAST" if corner_first else ""
    limit_clause = "LIMIT %(limit)s" if limit else ""
    query_params: dict = {}
    if limit:
        query_params["limit"] = int(limit)

    cur.execute(f"""
        SELECT p.id
        FROM parcels p
        JOIN subdivision_analysis sa ON sa.parcel_id = p.id
        WHERE sa.is_subdividable = true
          AND sa.quick_filter_result NOT IN ('EXCLUDED_OWNER', 'NOT_RESIDENTIAL')
          AND p.geom_stateplane IS NOT NULL
          AND p.area_sqft > 0
        {order_clause}
        {limit_clause}
    """, query_params)
    parcel_ids = [row[0] for row in cur.fetchall()]

    total = len(parcel_ids)
    print(f"Found {total:,} parcels for geometric analysis", flush=True)
    if total == 0:
        print("Nothing to process.", flush=True)
        conn.close()
        return

    t0 = time.time()
    totals = {"ok": 0, "no": 0, "err": 0}
    PER_PARCEL_TIMEOUT = 30

    for i, pid in enumerate(parcel_ids):
        t1 = time.time()
        try:
            result = _load_and_analyze(pid, conn)
            dt = time.time() - t1
            if dt > PER_PARCEL_TIMEOUT:
                totals["err"] += 1
            else:
                _store_result(conn, result)
                if result.is_subdividable:
                    totals["ok"] += 1
                else:
                    totals["no"] += 1

            if (i + 1) % 50 == 0:
                conn.commit()
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                eta = (total - i - 1) / rate if rate > 0 else 0
                print(
                    f"  [{i+1:,}/{total:,}] {rate:.1f}/sec | ETA {eta/60:.1f}min | "
                    f"ok={totals['ok']} no={totals['no']} err={totals['err']}",
                    flush=True,
                )

        except Exception:
            totals["err"] += 1
            try:
                conn.rollback()
            except Exception:
                pass

    conn.commit()
    elapsed = time.time() - t0
    print(f"\nCompleted {total:,} parcels in {elapsed/60:.1f} min ({total/elapsed:.1f}/sec)", flush=True)

    cur = conn.cursor()
    cur.execute("""
        SELECT subdivision_type, COUNT(*), AVG(num_possible_lots)::numeric(5,1)
        FROM subdivision_analysis
        WHERE is_subdividable = true AND subdivision_type IS NOT NULL
        GROUP BY subdivision_type ORDER BY COUNT(*) DESC;
    """)
    print("\n=== Geometric Analysis Summary ===", flush=True)
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]:,} parcels, avg {row[2]} lots", flush=True)

    cur.execute("SELECT COUNT(*) FROM subdivision_analysis WHERE proposed_lots IS NOT NULL;")
    with_geometry = cur.fetchone()[0]
    print(f"\nParcels with proposed geometry: {with_geometry:,}", flush=True)
    print(f"Results: {totals}", flush=True)
    conn.close()
    print("Done!", flush=True)


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(limit=limit)
