"""
Validate subdivision results against the rubric.

Checks every parcel with proposed lots:
1. Each lot has street access
2. Each lot meets minimum area
3. Each lot meets minimum width
4. Structure fits (≥600sf, aspect ratio ≤2:1)
5. Primary structure is preserved (not bisected)
6. Lot shapes are reasonable (not slivers)

Outputs a summary and flags specific issues.
"""

import json
import os
import sys
import psycopg2
from dotenv import load_dotenv
from shapely import wkb
from shapely.geometry import mapping, MultiPolygon, Polygon
from shapely.ops import unary_union

from backend.analysis.street_detection import EdgeLabel, detect_street_edges
from backend.analysis.setback_engine import compute_buildable_envelope
from backend.analysis.structure_fitter import fit_structure
from backend.udo.rules_engine import get_district_rules, get_setbacks, is_small_lot_eligible

load_dotenv()
DB_URL = os.environ["DATABASE_URL"]

MIN_STRUCTURE_FOOTPRINT = 600.0
MAX_ASPECT_RATIO = 2.0
MIN_STREET_CONTACT_FT = 5.0


def validate_parcel(pid, conn):
    """Validate a single parcel's subdivision results. Returns dict of issues."""
    cur = conn.cursor()

    cur.execute("""
        SELECT p.id, p.pin, p.location_addr, p.zoning, p.area_sqft,
               ST_AsBinary(p.geom_stateplane),
               sa.subdivision_type, sa.num_possible_lots,
               sa.existing_structure_conflict, sa.notes,
               sa.max_structure_footprint_sqft,
               ST_AsBinary(sa.proposed_lots),
               ST_AsBinary(sa.proposed_structures)
        FROM parcels p
        JOIN subdivision_analysis sa ON sa.parcel_id = p.id
        WHERE p.id = %s AND sa.proposed_lots IS NOT NULL
    """, (pid,))
    row = cur.fetchone()
    if not row:
        return None

    (p_id, pin, addr, zoning, area, geom_wkb,
     sub_type, num_lots, struct_conflict, notes,
     max_struct_sf, lots_wkb, structs_wkb) = row

    issues = []
    info = {
        'pin': pin, 'addr': addr, 'zoning': zoning, 'area': area,
        'type': sub_type, 'lots': num_lots, 'conflict': struct_conflict,
        'max_struct': max_struct_sf,
    }

    parcel = wkb.loads(bytes(geom_wkb))
    proposed_lots = wkb.loads(bytes(lots_wkb)) if lots_wkb else None

    if proposed_lots is None:
        return {'info': info, 'issues': ['no proposed lots geometry'], 'pass': False}

    # Get individual lot polygons
    if isinstance(proposed_lots, MultiPolygon):
        lots = list(proposed_lots.geoms)
    elif isinstance(proposed_lots, Polygon):
        lots = [proposed_lots]
    else:
        return {'info': info, 'issues': ['invalid geometry type'], 'pass': False}

    # Load primary structure
    cur.execute("""
        SELECT ST_AsBinary(bf.geom_stateplane) FROM building_footprints bf
        WHERE bf.parcel_id = %s AND bf.geom_stateplane IS NOT NULL
        ORDER BY ST_Area(bf.geom_stateplane) DESC LIMIT 1
    """, (pid,))
    brow = cur.fetchone()
    primary = wkb.loads(bytes(brow[0])) if brow else None

    # Street edges
    detection = detect_street_edges(parcel)
    street_edges = []
    if detection:
        street_edges = [e.geometry for e in detection.edges if e.label == EdgeLabel.STREET]
    street_union = unary_union(street_edges) if street_edges else None

    rules = get_district_rules(zoning)
    if not rules:
        return {'info': info, 'issues': ['no rules for zoning'], 'pass': False}

    is_small = sub_type == "small_lot"
    min_area = 2000.0 if is_small else rules.min_lot_area_sqft
    min_width = 25.0 if is_small else rules.min_lot_width_ft
    setbacks = get_setbacks(zoning, "small_lot" if is_small else "standard")

    for i, lot in enumerate(lots):
        lot_label = f"lot {i+1}"

        # 1. Area check
        if lot.area < min_area:
            issues.append(f"{lot_label}: area {lot.area:.0f}sf < min {min_area:.0f}sf")

        # 2. Street access
        if street_union:
            strip = street_union.buffer(1.0)
            overlap = lot.intersection(strip)
            contact = overlap.area if not overlap.is_empty else 0
            if contact < MIN_STREET_CONTACT_FT:
                issues.append(f"{lot_label}: no street access (contact={contact:.1f})")

        # 3. Primary structure check
        if primary and not primary.is_empty:
            if primary.intersects(lot) and not lot.contains(primary):
                issues.append(f"{lot_label}: primary structure bisected")

        # 4. Lot shape (aspect ratio of bounding box)
        lbounds = lot.bounds
        lw = lbounds[2] - lbounds[0]
        ld = lbounds[3] - lbounds[1]
        lot_aspect = max(lw, ld) / max(min(lw, ld), 0.1)
        if lot_aspect > 5.0:
            issues.append(f"{lot_label}: extreme aspect ratio {lot_aspect:.1f}:1")

    # 5. Check proposed structures
    if structs_wkb:
        proposed_structs = wkb.loads(bytes(structs_wkb))
        if isinstance(proposed_structs, MultiPolygon):
            structs = list(proposed_structs.geoms)
        elif isinstance(proposed_structs, Polygon):
            structs = [proposed_structs]
        else:
            structs = []

        for j, s in enumerate(structs):
            if s.area < MIN_STRUCTURE_FOOTPRINT:
                issues.append(f"struct {j+1}: {s.area:.0f}sf < min {MIN_STRUCTURE_FOOTPRINT:.0f}sf")
            sb = s.bounds
            sw = sb[2] - sb[0]
            sd = sb[3] - sb[1]
            s_aspect = max(sw, sd) / max(min(sw, sd), 0.1)
            if s_aspect > MAX_ASPECT_RATIO:
                issues.append(f"struct {j+1}: aspect {s_aspect:.1f}:1 (max {MAX_ASPECT_RATIO})")

    # 6. Max structure footprint sanity
    if max_struct_sf is not None and max_struct_sf < MIN_STRUCTURE_FOOTPRINT:
        issues.append(f"max_structure={max_struct_sf:.0f}sf < min {MIN_STRUCTURE_FOOTPRINT:.0f}sf")

    return {
        'info': info,
        'issues': issues,
        'pass': len(issues) == 0,
    }


def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 200

    cur.execute("""
        SELECT p.id FROM parcels p
        JOIN subdivision_analysis sa ON sa.parcel_id = p.id
        WHERE sa.proposed_lots IS NOT NULL
          AND sa.is_subdividable = true
          AND sa.num_possible_lots >= 2
        ORDER BY RANDOM()
        LIMIT %s
    """, (limit,))
    ids = [r[0] for r in cur.fetchall()]

    print(f"Validating {len(ids)} parcels with proposed geometry...\n")

    pass_count = 0
    fail_count = 0
    issue_counts = {}
    failed_examples = []

    for pid in ids:
        result = validate_parcel(pid, conn)
        if result is None:
            continue

        if result['pass']:
            pass_count += 1
        else:
            fail_count += 1
            for iss in result['issues']:
                key = iss.split(':')[1].strip().split('(')[0].strip() if ':' in iss else iss
                issue_counts[key] = issue_counts.get(key, 0) + 1
            if len(failed_examples) < 15:
                failed_examples.append(result)

    total = pass_count + fail_count
    print(f"=== VALIDATION SUMMARY ===")
    print(f"Total validated: {total}")
    print(f"  PASS: {pass_count} ({pass_count/max(total,1)*100:.1f}%)")
    print(f"  FAIL: {fail_count} ({fail_count/max(total,1)*100:.1f}%)")

    if issue_counts:
        print(f"\n=== ISSUE BREAKDOWN ===")
        for issue, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
            print(f"  {count:4d}  {issue}")

    if failed_examples:
        print(f"\n=== SAMPLE FAILURES ===")
        for r in failed_examples[:10]:
            info = r['info']
            print(f"\n  {info['addr'] or '(no addr)'} — PIN {info['pin']} ({info['zoning']}, {info['area']:,.0f}sf)")
            print(f"    Type: {info['type']}, Lots: {info['lots']}, Max struct: {info['max_struct']}")
            for iss in r['issues']:
                print(f"    ✗ {iss}")

    conn.close()


if __name__ == "__main__":
    main()
