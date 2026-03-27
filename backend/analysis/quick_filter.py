"""
Quick Filter: classify every parcel as subdividable/not based on area vs zoning minimums.

Classifications:
  NOT_RESIDENTIAL    - Zoning is not RS-*/RU-*, or non-residential land class
  EXCLUDED_OWNER     - Government/institutional owner (City, County, Schools, etc.)
  TOO_SMALL          - Area < min lot size (already nonconforming)
  AT_MINIMUM         - Area between 1x and 1.5x min lot size
  SUBDIVIDABLE_SMALL_LOT - Small lot eligible AND area >= min_lot_for_zone + 2000 sf
  SUBDIVIDABLE_STANDARD  - Area >= 2x min lot size
  SUBDIVIDABLE_MULTIPLE  - Area >= 3x min lot size (could yield 3+ lots)
  NEEDS_GEOMETRY     - Area sufficient but width may be insufficient
"""

import math
import os

import psycopg2
from dotenv import load_dotenv
from tqdm import tqdm

from backend.udo.rules_engine import (
    get_base_zone,
    get_district_rules,
    get_min_lot_size,
    is_small_lot_eligible,
)

load_dotenv()
DB_URL = os.environ["DATABASE_URL"]

_EXCLUDED_OWNER_PATTERNS = [
    "CITY OF DURHAM",
    "COUNTY OF DURHAM",
    "DURHAM PUBLIC SCHOOLS",
    "DURHAM COUNTY",
    "STATE OF NORTH CAROLINA",
    "UNITED STATES",
    "HOUSING AUTHORITY",
    "DUKE UNIVERSITY",
    "NORTH CAROLINA CENTRAL",
]

_RESIDENTIAL_LAND_CLASS_PREFIXES = [
    "RES/",
    "VAC RES/",
    "VACRES/",
]


def is_excluded_owner(owner: str | None) -> bool:
    if not owner:
        return False
    upper = owner.upper()
    return any(pat in upper for pat in _EXCLUDED_OWNER_PATTERNS)


def is_residential_land_class(land_class: str | None) -> bool:
    if not land_class:
        return True  # if unknown, don't exclude
    upper = land_class.upper()
    return any(upper.startswith(prefix) for prefix in _RESIDENTIAL_LAND_CLASS_PREFIXES)


def classify_parcel(
    zoning: str | None,
    area_sqft: float | None,
    bbox_width_ft: float | None,
    num_street_frontages: int | None = None,
    property_owner: str | None = None,
    land_class: str | None = None,
) -> tuple[str, int, str]:
    """
    Returns (classification, num_possible_lots, subdivision_type).
    
    num_street_frontages controls feasibility:
      - 0 = landlocked, not subdividable
      - 1 = interior lot, only flag lot possible (rear lot served by driveway pole)
      - 2+ = corner/through lot, standard subdivision viable
    """
    if is_excluded_owner(property_owner):
        return "EXCLUDED_OWNER", 0, ""

    if not is_residential_land_class(land_class):
        return "NOT_RESIDENTIAL", 0, ""

    if not zoning:
        return "NOT_RESIDENTIAL", 0, ""

    base = get_base_zone(zoning)
    if base is None:
        return "NOT_RESIDENTIAL", 0, ""

    rules = get_district_rules(zoning)
    if rules is None:
        return "NOT_RESIDENTIAL", 0, ""

    if area_sqft is None or area_sqft <= 0:
        return "NOT_RESIDENTIAL", 0, ""

    min_lot = rules.min_lot_area_sqft
    min_width = rules.min_lot_width_ft

    if area_sqft < min_lot:
        return "TOO_SMALL", 0, ""

    # If we know street access, enforce it
    is_corner = num_street_frontages is not None and num_street_frontages >= 2
    is_interior = num_street_frontages is not None and num_street_frontages == 1
    is_landlocked = num_street_frontages is not None and num_street_frontages == 0

    if is_landlocked:
        return "AT_MINIMUM", 1, ""

    # Interior lots: only flag lot is realistic (rear lot via driveway pole)
    # Even with large area, you can't give new lots street frontage.
    # UDO requires 20ft min pole width. The lot must be wide enough for
    # the pole PLUS a conforming front lot beside it.
    if is_interior:
        min_flag_width = min_width + 20  # district min width + 20ft driveway pole
        if bbox_width_ft is not None and bbox_width_ft < min_flag_width:
            return "AT_MINIMUM", 1, ""
        if area_sqft >= min_lot * 2:
            return "SUBDIVIDABLE_STANDARD", 2, "flag_lot"
        if area_sqft >= min_lot * 1.5:
            return "NEEDS_GEOMETRY", 1, "flag_lot"
        return "AT_MINIMUM", 1, ""

    # Corner lots (2+ street frontages) or unknown street access: full analysis
    small_lot_eligible = is_small_lot_eligible(zoning, "urban")
    small_lot_min = get_min_lot_size(zoning, "small_lot") if small_lot_eligible else None

    # Corner lots can split along either street, giving each lot its own frontage
    if is_corner and small_lot_eligible and small_lot_min:
        small_lot_count = int(area_sqft // small_lot_min)
        # Be more conservative: account for setbacks eating ~30% of area
        realistic_count = max(2, int(small_lot_count * 0.7))
        if realistic_count >= 2 and area_sqft >= min_lot + small_lot_min:
            if bbox_width_ft and bbox_width_ft < 25 * 2:
                return "NEEDS_GEOMETRY", realistic_count, "small_lot"
            if realistic_count >= 3:
                return "SUBDIVIDABLE_MULTIPLE", realistic_count, "small_lot"
            return "SUBDIVIDABLE_SMALL_LOT", realistic_count, "small_lot"

    # For unknown street access (num_street_frontages is None), be generous
    # but still apply basic checks
    if num_street_frontages is None and small_lot_eligible and small_lot_min:
        small_lot_count = int(area_sqft // small_lot_min)
        if small_lot_count >= 2 and area_sqft >= min_lot + small_lot_min:
            if bbox_width_ft and bbox_width_ft < 25 * 2:
                return "NEEDS_GEOMETRY", small_lot_count, "small_lot"
            if small_lot_count >= 3:
                return "SUBDIVIDABLE_MULTIPLE", small_lot_count, "small_lot"
            return "SUBDIVIDABLE_SMALL_LOT", small_lot_count, "small_lot"

    # Standard subdivision
    standard_lots = int(area_sqft // min_lot)

    if standard_lots >= 3:
        if bbox_width_ft and bbox_width_ft < min_width * 2:
            return "NEEDS_GEOMETRY", standard_lots, "standard"
        return "SUBDIVIDABLE_MULTIPLE", standard_lots, "standard"

    if standard_lots >= 2:
        if bbox_width_ft and bbox_width_ft < min_width * 2:
            return "NEEDS_GEOMETRY", standard_lots, "standard"
        return "SUBDIVIDABLE_STANDARD", standard_lots, "standard"

    if area_sqft < min_lot * 1.5:
        return "AT_MINIMUM", 1, ""

    return "NEEDS_GEOMETRY", 1, "flag_lot"


def run():
    print("Starting quick filter analysis...", flush=True)
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("""
        SELECT p.id, p.zoning, p.area_sqft,
               ST_XMax(p.geom_stateplane) - ST_XMin(p.geom_stateplane) as bbox_width,
               sa.num_street_frontages,
               p.property_owner, p.land_class
        FROM parcels p
        LEFT JOIN subdivision_analysis sa ON sa.parcel_id = p.id
        WHERE p.geom IS NOT NULL
    """)
    parcels = cur.fetchall()
    print(f"Analyzing {len(parcels):,} parcels...", flush=True)

    cur.execute("TRUNCATE subdivision_analysis;")
    conn.commit()

    batch = []
    batch_size = 500

    frontage_map = {row[0]: row[4] for row in parcels if row[4] is not None}
    print(f"Preserving street frontage data for {len(frontage_map):,} parcels", flush=True)

    for parcel_id, zoning, area_sqft, bbox_width, num_frontages, owner, land_class in tqdm(parcels, desc="Classifying"):
        classification, num_lots, sub_type = classify_parcel(
            zoning, area_sqft, bbox_width, num_frontages, owner, land_class,
        )

        is_subdividable = classification in (
            "SUBDIVIDABLE_SMALL_LOT",
            "SUBDIVIDABLE_STANDARD",
            "SUBDIVIDABLE_MULTIPLE",
            "NEEDS_GEOMETRY",
        )

        is_corner = num_frontages is not None and num_frontages >= 2

        batch.append((
            parcel_id, is_subdividable, classification,
            sub_type if sub_type else None,
            num_lots if num_lots > 0 else None,
            num_frontages,
            is_corner if num_frontages is not None else None,
        ))

        if len(batch) >= batch_size:
            _insert_batch(cur, batch)
            conn.commit()
            batch = []

    if batch:
        _insert_batch(cur, batch)
        conn.commit()

    # Print summary
    cur.execute("""
        SELECT quick_filter_result, COUNT(*)
        FROM subdivision_analysis
        GROUP BY quick_filter_result
        ORDER BY COUNT(*) DESC;
    """)
    print("\n=== Quick Filter Results ===", flush=True)
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]:,}", flush=True)

    cur.execute("SELECT COUNT(*) FROM subdivision_analysis WHERE is_subdividable = true;")
    subdividable = cur.fetchone()[0]
    print(f"\nTotal subdividable: {subdividable:,}", flush=True)

    conn.close()
    print("Done!", flush=True)


def _insert_batch(cur, batch):
    for row in batch:
        cur.execute(
            """
            INSERT INTO subdivision_analysis
                (parcel_id, is_subdividable, quick_filter_result, subdivision_type,
                 num_possible_lots, num_street_frontages, is_corner_lot)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (parcel_id) DO UPDATE SET
                is_subdividable = EXCLUDED.is_subdividable,
                quick_filter_result = EXCLUDED.quick_filter_result,
                subdivision_type = EXCLUDED.subdivision_type,
                num_possible_lots = EXCLUDED.num_possible_lots,
                num_street_frontages = COALESCE(EXCLUDED.num_street_frontages, subdivision_analysis.num_street_frontages),
                is_corner_lot = COALESCE(EXCLUDED.is_corner_lot, subdivision_analysis.is_corner_lot),
                analyzed_at = NOW()
            """,
            row,
        )


if __name__ == "__main__":
    run()
