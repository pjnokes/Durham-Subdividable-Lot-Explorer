"""
Generate synthetic building footprints for parcels that have a known
heated_area (from tax records) but no building footprint geometry from
Microsoft or OSM datasets.

Strategy:
  1. Load the parcel polygon in state plane (EPSG:2264, feet).
  2. Apply conservative setbacks to produce a buildable envelope.
  3. Detect the street edge so we can orient the building toward the front.
  4. Create a rectangular footprint sized to ~65% of heated_area
     (accounting for multi-story homes), placed front-center in the lot.
  5. Insert into building_footprints with source='synthetic'.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time

import psycopg2
from dotenv import load_dotenv
from shapely import wkb
from shapely.geometry import Polygon, box, mapping
from shapely.affinity import rotate, translate
from shapely.ops import nearest_points

load_dotenv()
DB_URL = os.environ["DATABASE_URL"]

# Conservative setbacks (feet) — used only for placement estimation
FRONT_SETBACK = 25
SIDE_SETBACK = 8
REAR_SETBACK = 25

# Assume average 1.5 stories → footprint ≈ 65% of heated_area
FOOTPRINT_RATIO = 0.65

# Don't generate footprints smaller than this
MIN_FOOTPRINT_SQFT = 400


def _buildable_envelope(parcel: Polygon, front_setback=FRONT_SETBACK,
                         side_setback=SIDE_SETBACK, rear_setback=REAR_SETBACK) -> Polygon:
    """Inward buffer to approximate the buildable envelope."""
    avg_setback = (front_setback + side_setback + rear_setback + side_setback) / 4
    envelope = parcel.buffer(-avg_setback)
    if envelope.is_empty or not isinstance(envelope, Polygon):
        envelope = parcel.buffer(-side_setback)
    if envelope.is_empty:
        return parcel.buffer(-3)
    return envelope


def _place_rectangle(parcel: Polygon, target_area: float,
                     street_edge=None) -> Polygon | None:
    """
    Place a rectangle of approximately target_area inside the parcel.

    If a street_edge is provided, orient the building parallel to it and
    push it toward the front of the lot. Otherwise, fall back to placing
    a rectangle at the centroid.
    """
    side = math.sqrt(target_area)
    width = side * 1.3   # slightly wider than deep (typical house proportions)
    depth = target_area / width

    if width < 15:
        width = 15
        depth = target_area / width
    if depth < 15:
        depth = 15
        width = target_area / depth

    envelope = _buildable_envelope(parcel)
    if envelope.is_empty:
        return None

    # Try to orient parallel to street if we know which edge it is
    if street_edge is not None:
        coords = list(street_edge.coords)
        dx = coords[-1][0] - coords[0][0]
        dy = coords[-1][1] - coords[0][1]
        angle = math.degrees(math.atan2(dy, dx))
    else:
        minr = parcel.minimum_rotated_rectangle
        mrcoords = list(minr.exterior.coords)
        edge1 = math.hypot(mrcoords[1][0] - mrcoords[0][0],
                           mrcoords[1][1] - mrcoords[0][1])
        edge2 = math.hypot(mrcoords[2][0] - mrcoords[1][0],
                           mrcoords[2][1] - mrcoords[1][1])
        if edge1 <= edge2:
            dx = mrcoords[1][0] - mrcoords[0][0]
            dy = mrcoords[1][1] - mrcoords[0][1]
        else:
            dx = mrcoords[2][0] - mrcoords[1][0]
            dy = mrcoords[2][1] - mrcoords[1][1]
        angle = math.degrees(math.atan2(dy, dx))

    cx, cy = envelope.centroid.x, envelope.centroid.y

    # If we have a street edge, push toward the front
    if street_edge is not None:
        street_mid = street_edge.interpolate(0.5, normalized=True)
        rear_pt = parcel.centroid
        # Move centroid 30% toward street from the envelope center
        cx = cx + 0.30 * (street_mid.x - cx)
        cy = cy + 0.30 * (street_mid.y - cy)

    hw, hd = width / 2, depth / 2
    rect = box(cx - hw, cy - hd, cx + hw, cy + hd)
    rect = rotate(rect, angle, origin=(cx, cy))

    # Ensure it stays within the parcel
    clipped = rect.intersection(parcel)
    if clipped.is_empty or clipped.area < target_area * 0.3:
        # Fall back: shrink to fit
        for scale in [0.8, 0.6, 0.5]:
            small_w, small_d = width * scale, depth * scale
            rect2 = box(cx - small_w/2, cy - small_d/2, cx + small_w/2, cy + small_d/2)
            rect2 = rotate(rect2, angle, origin=(cx, cy))
            clipped2 = rect2.intersection(parcel)
            if not clipped2.is_empty and clipped2.area > MIN_FOOTPRINT_SQFT:
                return clipped2 if isinstance(clipped2, Polygon) else None
        return None

    if isinstance(clipped, Polygon):
        return clipped
    # MultiPolygon — take the largest piece
    if hasattr(clipped, 'geoms'):
        polys = [g for g in clipped.geoms if isinstance(g, Polygon)]
        if polys:
            return max(polys, key=lambda p: p.area)
    return None


def run(limit: int | None = None, dry_run: bool = False):
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    limit_clause = f"LIMIT {limit}" if limit else ""

    cur.execute(f"""
        SELECT p.id, p.heated_area, ST_AsBinary(p.geom_stateplane), p.zoning
        FROM parcels p
        WHERE p.heated_area > 0
          AND p.geom_stateplane IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM building_footprints bf WHERE bf.parcel_id = p.id
          )
        ORDER BY p.heated_area DESC
        {limit_clause}
    """)
    rows = cur.fetchall()
    total = len(rows)
    print(f"Found {total:,} parcels needing synthetic footprints", flush=True)

    if total == 0:
        conn.close()
        return

    # Lazy import to avoid circular deps
    from backend.analysis.street_detection import detect_street_edges, EdgeLabel

    t0 = time.time()
    inserted = 0
    skipped = 0
    errors = 0

    for i, (parcel_id, heated_area, geom_wkb, zoning) in enumerate(rows):
        try:
            parcel = wkb.loads(bytes(geom_wkb))
            if not isinstance(parcel, Polygon) or parcel.is_empty:
                skipped += 1
                continue

            target_area = max(heated_area * FOOTPRINT_RATIO, MIN_FOOTPRINT_SQFT)

            # Detect street edge for orientation
            street_edge = None
            detection = detect_street_edges(parcel)
            if detection:
                for e in detection.edges:
                    if e.label == EdgeLabel.STREET:
                        street_edge = e.geometry
                        break

            footprint = _place_rectangle(parcel, target_area, street_edge)
            if footprint is None or footprint.is_empty:
                skipped += 1
                continue

            if dry_run:
                inserted += 1
                continue

            geojson_sp = json.dumps(mapping(footprint))

            cur.execute("""
                INSERT INTO building_footprints
                    (geom, geom_stateplane, area_sqft, parcel_id, source)
                VALUES (
                    ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 2264), 4326),
                    ST_SetSRID(ST_GeomFromGeoJSON(%s), 2264),
                    %s,
                    %s,
                    'synthetic'
                )
            """, (geojson_sp, geojson_sp, footprint.area, parcel_id))
            inserted += 1

            if (i + 1) % 100 == 0:
                conn.commit()
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                eta = (total - i - 1) / rate if rate > 0 else 0
                print(
                    f"  [{i+1:,}/{total:,}] {rate:.1f}/sec | ETA {eta/60:.1f}min | "
                    f"inserted={inserted:,} skipped={skipped} err={errors}",
                    flush=True,
                )

        except Exception as e:
            errors += 1
            try:
                conn.rollback()
            except Exception:
                pass

    conn.commit()
    elapsed = time.time() - t0
    print(f"\nDone in {elapsed/60:.1f} min", flush=True)
    print(f"  Inserted: {inserted:,}", flush=True)
    print(f"  Skipped:  {skipped:,}", flush=True)
    print(f"  Errors:   {errors:,}", flush=True)

    # Verify gap reduction
    cur.execute("""
        SELECT COUNT(*) FROM parcels p
        WHERE p.heated_area > 0
        AND NOT EXISTS (SELECT 1 FROM building_footprints bf WHERE bf.parcel_id = p.id)
    """)
    remaining = cur.fetchone()[0]
    print(f"  Remaining gap: {remaining:,}", flush=True)

    conn.close()


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    dry_run = "--dry-run" in sys.argv
    run(limit=limit, dry_run=dry_run)
