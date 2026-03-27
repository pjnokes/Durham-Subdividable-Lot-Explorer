"""
Flag lot analysis — attempt to create a flag-lot subdivision.

A flag lot has a narrow "pole" (driveway corridor) connecting a rear "flag"
lot to the street.  Durham UDO requires the pole to be at least 20 ft wide.
Both the front and rear lots must independently meet district dimensional
standards.

All geometry is EPSG:2264 (NC State Plane, feet).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import split, unary_union

from backend.analysis.setback_engine import compute_buildable_envelope
from backend.analysis.street_detection import EdgeLabel, detect_street_edges
from backend.analysis.structure_fitter import StructureFit, fit_structure
from backend.udo.rules_engine import (
    get_district_rules,
    get_flag_lot_rules,
    get_setbacks,
)


@dataclass
class FlagLotResult:
    success: bool
    front_lot: Optional[Polygon] = None
    rear_lot: Optional[Polygon] = None
    pole: Optional[Polygon] = None
    pole_width_ft: float = 0.0
    front_area_sqft: float = 0.0
    rear_area_sqft: float = 0.0
    front_structure: Optional[StructureFit] = None
    rear_structure: Optional[StructureFit] = None
    score: float = 0.0
    notes: str = ""


def try_flag_lot(
    parcel_geom_sp: Polygon,
    zoning: str,
    primary_structure: Optional[Polygon] = None,
    nearby_streets: Optional[list] = None,
) -> Optional[FlagLotResult]:
    """
    Attempt to subdivide a parcel into a front lot and a rear flag lot
    connected by a 20 ft pole.

    When *primary_structure* is given the split is constrained so the
    structure ends up entirely on one lot (never bisected).

    Parameters
    ----------
    parcel_geom_sp : Polygon
        Parcel boundary in EPSG:2264.
    zoning : str
        Zoning code.
    primary_structure : Polygon, optional
        Existing primary building footprint (EPSG:2264).

    Returns
    -------
    FlagLotResult or None if the parcel geometry is invalid.
    """
    if parcel_geom_sp is None or parcel_geom_sp.is_empty:
        return None

    # Simplify complex boundaries to prevent hangs
    n = len(parcel_geom_sp.exterior.coords)
    if n > 80:
        parcel_geom_sp = parcel_geom_sp.simplify(2.0, preserve_topology=True)
        if not isinstance(parcel_geom_sp, Polygon) or parcel_geom_sp.is_empty:
            return None

    rules = get_district_rules(zoning)
    if rules is None:
        return FlagLotResult(success=False, notes="non-residential zoning")

    flag_rules = get_flag_lot_rules()
    min_pole_width = flag_rules.get("min_pole_width_ft", 20)
    min_lot_area = rules.min_lot_area_sqft
    min_lot_width = rules.min_lot_width_ft

    detection = detect_street_edges(parcel_geom_sp)
    if detection is None:
        return FlagLotResult(success=False, notes="could not detect street edges")

    street_edges = [e for e in detection.edges if e.label == EdgeLabel.STREET]
    if not street_edges:
        return FlagLotResult(success=False, notes="no street edge detected")

    best: Optional[FlagLotResult] = None

    for side in ["left", "right"]:
        result = _try_pole_on_side(
            parcel_geom_sp, zoning, rules, street_edges, detection,
            side, min_pole_width, min_lot_area, min_lot_width,
            primary_structure=primary_structure,
        )
        if result is not None and result.success:
            if best is None or result.score > best.score:
                best = result

    if best is not None:
        return best

    result = _try_center_pole(
        parcel_geom_sp, zoning, rules, detection,
        min_pole_width, min_lot_area, min_lot_width,
        primary_structure=primary_structure,
    )
    if result is not None and result.success:
        return result

    return FlagLotResult(success=False, notes="no viable flag lot configuration")


# ---------------------------------------------------------------------------
# Pole on left/right side of lot
# ---------------------------------------------------------------------------

def _try_pole_on_side(
    parcel: Polygon,
    zoning: str,
    rules,
    street_edges: list,
    detection,
    side: str,
    min_pole_width: float,
    min_lot_area: float,
    min_lot_width: float,
    primary_structure: Optional[Polygon] = None,
) -> Optional[FlagLotResult]:
    """Place a pole along one side of the lot, creating a flag lot at the rear."""
    bounds = parcel.bounds
    lot_width = bounds[2] - bounds[0]
    lot_depth = bounds[3] - bounds[1]

    if lot_width < min_pole_width + min_lot_width:
        return None

    street_az = detection.street_azimuth_deg
    street_rad = math.radians(street_az)

    diag = math.hypot(lot_width, lot_depth)

    min_front_depth = min_lot_area / max(lot_width, 1)
    max_front_depth = lot_depth * 0.7

    best_result: Optional[FlagLotResult] = None
    best_score = -1.0

    for frac in [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8]:
        front_depth = min_front_depth + (max_front_depth - min_front_depth) * frac
        if front_depth <= 0 or front_depth >= lot_depth:
            continue

        result = _evaluate_flag_split(
            parcel, zoning, rules, detection, street_rad,
            front_depth, min_pole_width, side,
            min_lot_area, min_lot_width, diag,
            primary_structure=primary_structure,
        )
        if result is not None and result.success and result.score > best_score:
            best_score = result.score
            best_result = result

    return best_result


def _evaluate_flag_split(
    parcel: Polygon,
    zoning: str,
    rules,
    detection,
    street_rad: float,
    front_depth: float,
    pole_width: float,
    side: str,
    min_lot_area: float,
    min_lot_width: float,
    diag: float,
    primary_structure: Optional[Polygon] = None,
) -> Optional[FlagLotResult]:
    """
    Evaluate a specific flag lot configuration: front lot of given depth,
    pole on given side, rear lot gets the remainder.

    If *primary_structure* is provided, the split line must not bisect it
    and the structure must be fully contained in one resulting lot.
    """
    centroid = parcel.centroid
    cx, cy = centroid.x, centroid.y

    perp_rad = math.radians((detection.street_azimuth_deg + 90) % 360)
    split_pos_x = cx + front_depth * math.cos(perp_rad) * 0.5
    split_pos_y = cy + front_depth * math.sin(perp_rad) * 0.5

    dx = math.sin(street_rad) * diag
    dy = math.cos(street_rad) * diag

    split_line = LineString([
        (split_pos_x - dx, split_pos_y - dy),
        (split_pos_x + dx, split_pos_y + dy),
    ])

    if primary_structure and not primary_structure.is_empty:
        clipped = split_line.intersection(parcel)
        if clipped.intersects(primary_structure) and not clipped.touches(primary_structure):
            return None

    try:
        parts = split(parcel, split_line)
    except Exception:
        return None

    polys = [g for g in parts.geoms if isinstance(g, Polygon) and g.area > 100]
    if len(polys) < 2:
        return None

    street_geoms = [e.geometry for e in detection.edges if e.label == EdgeLabel.STREET]
    if not street_geoms:
        return None
    street_union = unary_union(street_geoms)

    polys.sort(key=lambda p: p.centroid.distance(street_union))
    front_lot = polys[0]
    rear_area_geom = _merge_all(polys[1:])

    if rear_area_geom is None:
        return None

    pole_geom = _create_pole_strip(parcel, rear_area_geom, pole_width, side, detection)
    if pole_geom is None or pole_geom.is_empty:
        return None

    # Ensure pole doesn't cut through the primary structure
    if primary_structure and not primary_structure.is_empty:
        if pole_geom.intersects(primary_structure) and not pole_geom.touches(primary_structure):
            return None

    # Subtract pole from both front and rear lots
    front_lot = front_lot.difference(pole_geom)
    if front_lot.is_empty:
        return None
    if isinstance(front_lot, MultiPolygon):
        parts_list = sorted(front_lot.geoms, key=lambda g: g.area, reverse=True)
        front_lot = parts_list[0]
    if not isinstance(front_lot, Polygon):
        return None

    rear_lot = rear_area_geom.difference(pole_geom)
    if rear_lot.is_empty:
        return None
    if isinstance(rear_lot, MultiPolygon):
        parts_list = sorted(rear_lot.geoms, key=lambda g: g.area, reverse=True)
        rear_lot = parts_list[0]
    if not isinstance(rear_lot, Polygon):
        return None

    if front_lot.area < min_lot_area or rear_lot.area < min_lot_area:
        return None

    # Check primary structure is fully on one lot
    if primary_structure and not primary_structure.is_empty:
        contained = front_lot.contains(primary_structure) or rear_lot.contains(primary_structure)
        if not contained:
            return None

    front_width = _estimate_width(front_lot, street_rad)
    rear_width = _estimate_width(rear_lot, street_rad)
    if front_width < min_lot_width or rear_width < min_lot_width:
        return None

    # Only require structure fitting on the lot that does NOT hold the primary
    front_has_primary = primary_structure and front_lot.contains(primary_structure)
    rear_has_primary = primary_structure and rear_lot.contains(primary_structure)

    front_fit = None if front_has_primary else fit_structure(front_lot, zoning, "standard")
    rear_fit = None if rear_has_primary else fit_structure(rear_lot, zoning, "flag_lot")

    if not front_has_primary and (front_fit is None or not front_fit.fits):
        return None
    if not rear_has_primary and (rear_fit is None or not rear_fit.fits):
        return None

    score = 20.0 + (front_lot.area + rear_lot.area) / 1000.0

    return FlagLotResult(
        success=True,
        front_lot=front_lot,
        rear_lot=rear_lot,
        pole=pole_geom,
        pole_width_ft=pole_width,
        front_area_sqft=front_lot.area,
        rear_area_sqft=rear_lot.area,
        front_structure=front_fit,
        rear_structure=rear_fit,
        score=score,
        notes=f"flag lot, pole on {side}",
    )


# ---------------------------------------------------------------------------
# Center pole fallback
# ---------------------------------------------------------------------------

def _try_center_pole(
    parcel: Polygon,
    zoning: str,
    rules,
    detection,
    min_pole_width: float,
    min_lot_area: float,
    min_lot_width: float,
    primary_structure: Optional[Polygon] = None,
) -> Optional[FlagLotResult]:
    """
    Try placing the pole through the center of the lot.
    Front lot flanks both sides of the pole at the street; rear lot is behind.
    """
    bounds = parcel.bounds
    lot_width = bounds[2] - bounds[0]
    lot_depth = bounds[3] - bounds[1]

    if lot_width < min_pole_width + 2 * min_lot_width:
        return None

    centroid = parcel.centroid
    street_rad = math.radians(detection.street_azimuth_deg)

    diag = math.hypot(lot_width, lot_depth)

    perp_rad = math.radians((detection.street_azimuth_deg + 90) % 360)
    mid_x = centroid.x
    mid_y = centroid.y

    dx = math.sin(street_rad) * diag
    dy = math.cos(street_rad) * diag

    split_line = LineString([(mid_x - dx, mid_y - dy), (mid_x + dx, mid_y + dy)])

    if primary_structure and not primary_structure.is_empty:
        clipped = split_line.intersection(parcel)
        if clipped.intersects(primary_structure) and not clipped.touches(primary_structure):
            return None

    try:
        parts = split(parcel, split_line)
    except Exception:
        return None

    polys = [g for g in parts.geoms if isinstance(g, Polygon) and g.area > 100]
    if len(polys) < 2:
        return None

    street_geoms = [e.geometry for e in detection.edges if e.label == EdgeLabel.STREET]
    if not street_geoms:
        return None
    street_union = unary_union(street_geoms)

    polys.sort(key=lambda p: p.centroid.distance(street_union))
    front_lot = polys[0]
    rear_lot = _merge_all(polys[1:])

    if rear_lot is None or front_lot.area < min_lot_area or rear_lot.area < min_lot_area:
        return None

    pole_geom = _center_pole_geom(parcel, front_lot, min_pole_width, detection)
    if pole_geom is None:
        return None

    if primary_structure and not primary_structure.is_empty:
        if pole_geom.intersects(primary_structure) and not pole_geom.touches(primary_structure):
            return None

    front_lot = front_lot.difference(pole_geom)
    if front_lot.is_empty:
        return None
    if isinstance(front_lot, MultiPolygon):
        parts_list = sorted(front_lot.geoms, key=lambda g: g.area, reverse=True)
        front_lot = parts_list[0]
    if not isinstance(front_lot, Polygon):
        return None

    rear_lot = rear_lot.difference(pole_geom)
    if rear_lot.is_empty:
        return None
    if isinstance(rear_lot, MultiPolygon):
        parts_list = sorted(rear_lot.geoms, key=lambda g: g.area, reverse=True)
        rear_lot = parts_list[0]
    if not isinstance(rear_lot, Polygon):
        return None

    if front_lot.area < min_lot_area or rear_lot.area < min_lot_area:
        return None

    if primary_structure and not primary_structure.is_empty:
        contained = front_lot.contains(primary_structure) or rear_lot.contains(primary_structure)
        if not contained:
            return None

    front_has_primary = primary_structure and front_lot.contains(primary_structure)
    rear_has_primary = primary_structure and rear_lot.contains(primary_structure)

    front_fit = None if front_has_primary else fit_structure(front_lot, zoning, "standard")
    rear_fit = None if rear_has_primary else fit_structure(rear_lot, zoning, "flag_lot")

    if not front_has_primary and (front_fit is None or not front_fit.fits):
        return None
    if not rear_has_primary and (rear_fit is None or not rear_fit.fits):
        return None

    score = 20.0 + (front_lot.area + rear_lot.area) / 1000.0

    return FlagLotResult(
        success=True,
        front_lot=front_lot,
        rear_lot=rear_lot,
        pole=pole_geom,
        pole_width_ft=min_pole_width,
        front_area_sqft=front_lot.area,
        rear_area_sqft=rear_lot.area,
        front_structure=front_fit,
        rear_structure=rear_fit,
        score=score,
        notes="flag lot, center pole",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_pole_strip(
    parcel: Polygon,
    rear_geom: Polygon,
    pole_width: float,
    side: str,
    detection,
) -> Optional[Polygon]:
    """
    Create a pole strip along one side of the parcel boundary,
    extending from the street frontage all the way to the rear lot.
    Uses the actual detected SIDE_LEFT / SIDE_RIGHT parcel edges rather
    than axis-aligned bounding boxes, so the pole follows the real
    parcel shape regardless of lot orientation.
    """
    target_label = EdgeLabel.SIDE_LEFT if side == "left" else EdgeLabel.SIDE_RIGHT
    side_edges = [e.geometry for e in detection.edges if e.label == target_label]

    if not side_edges:
        return None

    side_line = unary_union(side_edges)

    pole_area = side_line.buffer(pole_width).intersection(parcel)

    if pole_area.is_empty:
        return None
    if isinstance(pole_area, MultiPolygon):
        parts = sorted(pole_area.geoms, key=lambda g: g.area, reverse=True)
        pole_area = parts[0]
    if not isinstance(pole_area, Polygon):
        return None
    return pole_area


def _center_pole_geom(
    parcel: Polygon,
    front_lot: Polygon,
    pole_width: float,
    detection,
) -> Optional[Polygon]:
    """Create a pole strip through the center of the parcel, perpendicular to street."""
    centroid = parcel.centroid
    perp_rad = math.radians((detection.street_azimuth_deg + 90) % 360)
    diag = math.hypot(
        parcel.bounds[2] - parcel.bounds[0],
        parcel.bounds[3] - parcel.bounds[1],
    ) * 1.5

    center_line = LineString([
        (centroid.x - diag * math.cos(perp_rad), centroid.y - diag * math.sin(perp_rad)),
        (centroid.x + diag * math.cos(perp_rad), centroid.y + diag * math.sin(perp_rad)),
    ])

    pole_strip = center_line.buffer(pole_width / 2, cap_style=2)
    pole = pole_strip.intersection(parcel)
    if pole.is_empty:
        return None
    if isinstance(pole, MultiPolygon):
        parts = sorted(pole.geoms, key=lambda g: g.area, reverse=True)
        pole = parts[0]
    if not isinstance(pole, Polygon):
        return None
    return pole


def _merge_all(polys: list[Polygon]) -> Optional[Polygon]:
    if not polys:
        return None
    merged = unary_union(polys)
    if isinstance(merged, MultiPolygon):
        parts = sorted(merged.geoms, key=lambda g: g.area, reverse=True)
        merged = parts[0]
    if isinstance(merged, Polygon):
        return merged
    return None


def _estimate_width(lot: Polygon, street_rad: float) -> float:
    coords = list(lot.exterior.coords)
    projections = [
        c[0] * math.cos(street_rad) - c[1] * math.sin(street_rad)
        for c in coords
    ]
    return max(projections) - min(projections)
