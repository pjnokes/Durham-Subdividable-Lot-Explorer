"""
Real street access validation using actual street centerline geometry
and Durham ROW (right-of-way) standards.

Durham ROW widths per construction standards (Sheet 401.09-401.11):
  - Local residential:  50 ft ROW  →  25 ft centerline to property line
  - Collector/state rd:  60 ft ROW  →  30 ft centerline to property line
  - Arterial/highway:    80 ft ROW  →  40 ft centerline to property line

UDO access requirements (general_lot_standards):
  - Every buildable lot must abut a public street, private street,
    or allowed driveway.
  - Standard lots: frontage >= district min_lot_width_ft
  - Small lots:    frontage >= 25 ft  (UDO small_lot_option)
  - Flag lot pole: width   >= 20 ft  (UDO flag_lot.min_pole_width_ft)

All geometry is EPSG:2264 (NC State Plane, feet).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union


# Durham ROW half-widths by road classification (centerline to property line)
# Source: Durham Construction Standard Details, Sheets 401.03–401.16
_ROW_HALF_WIDTH_BY_TYPE: dict[str, float] = {
    "LOCAL":          25.0,   # 50 ft ROW
    "LOCAL Pending":  25.0,
    "PRIVATE":        20.0,   # typically narrower
    "ALLEY":          10.0,   # alleys ~20 ft ROW
    "NC_STATE_RD":    30.0,   # 60 ft ROW
    "NC_HIGHWAY":     40.0,   # 80 ft ROW
    "US_HIGHWAY":     45.0,   # 90 ft ROW
    "NCDOT Pending":  30.0,
    "RALEIGH":        25.0,
    "MEDIAN_XING":    30.0,
}
_DEFAULT_ROW_HALF_WIDTH = 25.0

# Tolerance (feet) for survey/GIS alignment variation.
# Durham's older neighborhoods have ROWs ranging from 40-60 ft for
# local streets.  The GIS centerline may not be exactly centered,
# and parcel boundary precision varies.  8 ft covers these realities
# without inflating the buffer unreasonably.
_ALIGNMENT_TOLERANCE_FT = 8.0


@dataclass
class StreetAccessResult:
    has_access: bool
    street_edges: list[LineString]
    total_frontage_ft: float
    nearest_street_name: str | None = None
    nearest_street_dist_ft: float | None = None


def _row_half_width(ftr_code: str | None, pavement_width: float | None) -> float:
    """
    Compute the ROW half-width for a road segment.

    If we have the actual pavement width, the ROW is approximately
    pavement + 24 ft (curb, utility strip, sidewalk on both sides),
    so half-ROW ≈ pavement/2 + 12.

    Falls back to the table lookup by road classification.
    """
    if pavement_width and pavement_width > 0 and pavement_width < 150:
        return pavement_width / 2.0 + 12.0

    return _ROW_HALF_WIDTH_BY_TYPE.get(ftr_code or "", _DEFAULT_ROW_HALF_WIDTH)


def load_nearby_streets(parcel_geom_sp: Polygon, conn) -> list:
    """
    Query street_centerlines for segments near the parcel.
    Returns list of (LineString, road_name, ftr_code, width_ft) tuples.
    """
    from shapely import wkb

    search_radius = 65.0  # max ROW half-width (US highway 45ft) + tolerance (8ft) + margin

    cur = conn.cursor()
    cur.execute(
        """
        SELECT ST_AsBinary(sc.geom_stateplane), sc.road_name,
               sc.ftr_code, sc.width_ft
        FROM street_centerlines sc
        WHERE ST_DWithin(sc.geom_stateplane, ST_GeomFromWKB(%s, 2264), %s)
          AND sc.ftr_code NOT IN ('RAMP', 'INTERSTATE')
        """,
        (parcel_geom_sp.wkb, search_radius),
    )
    streets = []
    for row in cur.fetchall():
        try:
            geom = wkb.loads(bytes(row[0]))
            streets.append((geom, row[1], row[2], row[3]))
        except Exception:
            pass
    return streets


def _build_row_edge(nearby_streets: list) -> Polygon | None:
    """
    Build a polygon representing the ROW (right-of-way) edges of
    nearby streets, using each segment's actual pavement width and
    road classification to compute the correct buffer distance.
    """
    if not nearby_streets:
        return None

    buffers = []
    for geom, _name, ftr_code, width_ft in nearby_streets:
        half_row = _row_half_width(ftr_code, width_ft) + _ALIGNMENT_TOLERANCE_FT
        buf = geom.buffer(half_row)
        if not buf.is_empty:
            buffers.append(buf)

    if not buffers:
        return None

    return unary_union(buffers)


def get_street_adjacent_edges(
    parcel_geom_sp: Polygon,
    nearby_streets: list,
) -> list[LineString]:
    """
    Return the parcel boundary segments that lie within the ROW of
    a real street.
    """
    row_polygon = _build_row_edge(nearby_streets)
    if row_polygon is None:
        return []

    coords = list(parcel_geom_sp.exterior.coords)
    adjacent_edges = []

    for i in range(len(coords) - 1):
        edge = LineString([coords[i], coords[i + 1]])
        if edge.length < 1.0:
            continue
        overlap = edge.intersection(row_polygon)
        if not overlap.is_empty and overlap.length >= edge.length * 0.5:
            adjacent_edges.append(edge)

    return adjacent_edges


def check_lot_street_access(
    lot_geom: Polygon,
    nearby_streets: list,
    min_frontage_ft: float = 20.0,
) -> StreetAccessResult:
    """
    Check whether a proposed lot polygon abuts a real street ROW
    with at least min_frontage_ft of contact.

    Parameters
    ----------
    lot_geom : Polygon
        Proposed lot in EPSG:2264.
    nearby_streets : list
        Output of load_nearby_streets().
    min_frontage_ft : float
        UDO-required minimum frontage. For standard lots this is
        the district min_lot_width_ft; for flag lot access it's 20ft.
    """
    if not nearby_streets:
        return StreetAccessResult(
            has_access=False, street_edges=[], total_frontage_ft=0.0,
        )

    row_polygon = _build_row_edge(nearby_streets)
    if row_polygon is None:
        return StreetAccessResult(
            has_access=False, street_edges=[], total_frontage_ft=0.0,
        )

    lot_boundary = lot_geom.exterior
    contact = lot_boundary.intersection(row_polygon)

    if contact.is_empty:
        street_geoms = [s[0] for s in nearby_streets]
        street_union = unary_union(street_geoms)
        best_d = float("inf")
        nearest_name = None
        for geom, name, _code, _w in nearby_streets:
            d = lot_geom.distance(geom)
            if d < best_d:
                best_d = d
                nearest_name = name
        return StreetAccessResult(
            has_access=False, street_edges=[], total_frontage_ft=0.0,
            nearest_street_name=nearest_name, nearest_street_dist_ft=best_d,
        )

    contact_length = contact.length if hasattr(contact, "length") else 0.0
    adjacent_edges = get_street_adjacent_edges(lot_geom, nearby_streets)

    return StreetAccessResult(
        has_access=contact_length >= min_frontage_ft,
        street_edges=adjacent_edges,
        total_frontage_ft=contact_length,
    )


def check_pole_reaches_street(
    pole_geom: Polygon,
    nearby_streets: list,
) -> bool:
    """
    Verify that a flag lot pole physically reaches the street ROW.
    UDO requires the pole to connect the rear lot to a public street.
    """
    if not nearby_streets or pole_geom is None or pole_geom.is_empty:
        return False

    row_polygon = _build_row_edge(nearby_streets)
    if row_polygon is None:
        return False

    return pole_geom.intersects(row_polygon)
