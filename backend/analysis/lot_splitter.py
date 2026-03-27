"""
Lot splitter — subdivide a parcel into conforming lots.

Strategy (in priority order to maximise lot count):
  1. Multiple small lots (if eligible): N lots of ≥2,000 sf, 25 ft min width.
  2. Standard subdivision: lots meeting district minimums.
  3. Single lot (no split, parcel as-is).

Split lines run PERPENDICULAR to street frontage (front-to-back) so that
every resulting lot retains a strip of street frontage.  For corner lots,
both street directions are tried and the best valid result is kept.

All geometry is EPSG:2264 (NC State Plane, feet).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from shapely import ops
from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import unary_union

from backend.analysis.setback_engine import compute_buildable_envelope
from backend.analysis.street_detection import EdgeLabel, detect_street_edges
from backend.analysis.structure_fitter import fit_structure
from backend.udo.rules_engine import (
    Setbacks,
    get_district_rules,
    get_min_lot_size,
    get_setbacks,
    is_small_lot_eligible,
)

# UDO has no explicit minimum structure footprint for standard lots.
# 600 sf is a practical lower bound for a habitable single-family dwelling;
# anything smaller is commercially unbuildable in Durham's market.
_MIN_STRUCTURE_FOOTPRINT = 600.0

# UDO has no explicit aspect ratio limit, but extremely elongated footprints
# are not viable single-family homes. 3:1 is a practical sanity check.
_MAX_STRUCTURE_ASPECT_RATIO = 3.0

_MAX_VERTICES = 80
_MAX_LOTS_TO_TRY = 8


@dataclass
class LotInfo:
    geometry: Polygon
    area_sqft: float
    width_ft: float
    buildable_area_sqft: float


@dataclass
class SplitResult:
    lots: list[Polygon] = field(default_factory=list)
    lot_lines: list[LineString] = field(default_factory=list)
    num_lots: int = 0
    subdivision_type: str = ""
    score: float = 0.0
    notes: str = ""
    lot_infos: list[LotInfo] = field(default_factory=list)


def _simplify_if_needed(geom: Polygon) -> Polygon:
    """Reduce vertex count on complex boundaries."""
    n = len(geom.exterior.coords)
    if n <= _MAX_VERTICES:
        return geom
    tolerance = 2.0
    for _ in range(10):
        simplified = geom.simplify(tolerance, preserve_topology=True)
        if isinstance(simplified, Polygon) and len(simplified.exterior.coords) <= _MAX_VERTICES:
            return simplified
        tolerance *= 1.5
    return geom.simplify(tolerance, preserve_topology=True)


def split_parcel(
    parcel_geom_sp: Polygon,
    zoning: str,
    area_sqft: float,
    primary_structure: Optional[Polygon] = None,
    nearby_streets: Optional[list] = None,
) -> Optional[SplitResult]:
    """
    Attempt to subdivide a parcel into the maximum number of conforming lots.
    """
    if parcel_geom_sp is None or parcel_geom_sp.is_empty:
        return None

    parcel_geom_sp = _simplify_if_needed(parcel_geom_sp)

    rules = get_district_rules(zoning)
    if rules is None:
        return None

    result = _try_small_lot_split(parcel_geom_sp, zoning, area_sqft, rules, primary_structure, nearby_streets)
    if result is not None and result.num_lots >= 2:
        return result

    result = _try_standard_split(parcel_geom_sp, zoning, area_sqft, rules, primary_structure, nearby_streets)
    if result is not None and result.num_lots >= 2:
        return result

    return SplitResult(
        lots=[parcel_geom_sp],
        num_lots=1,
        subdivision_type="none",
        score=0,
        notes="Cannot subdivide: no valid split found",
    )


# ---------------------------------------------------------------------------
# Small lot strategy
# ---------------------------------------------------------------------------

_SMALL_LOT_MIN_AREA = 2000.0
_SMALL_LOT_MIN_WIDTH = 25.0


def _try_small_lot_split(
    parcel: Polygon,
    zoning: str,
    area_sqft: float,
    rules,
    primary_structure: Optional[Polygon] = None,
    nearby_streets: Optional[list] = None,
) -> Optional[SplitResult]:
    if not is_small_lot_eligible(zoning, rules.tier):
        return None

    small_min = get_min_lot_size(zoning, "small_lot")
    if small_min is None:
        return None

    max_possible = min(int(area_sqft // small_min), _MAX_LOTS_TO_TRY)
    if max_possible < 2:
        return None

    setbacks = get_setbacks(zoning, "small_lot")
    if setbacks is None:
        return None

    for n in range(max_possible, 1, -1):
        result = _execute_split(
            parcel, n, small_min, _SMALL_LOT_MIN_WIDTH, setbacks, "small_lot",
            primary_structure=primary_structure, zoning=zoning,
            nearby_streets=nearby_streets,
        )
        if result is not None:
            return result
    return None


# ---------------------------------------------------------------------------
# Standard subdivision strategy
# ---------------------------------------------------------------------------

def _try_standard_split(
    parcel: Polygon,
    zoning: str,
    area_sqft: float,
    rules,
    primary_structure: Optional[Polygon] = None,
    nearby_streets: Optional[list] = None,
) -> Optional[SplitResult]:
    min_area = rules.min_lot_area_sqft
    min_width = rules.min_lot_width_ft

    max_possible = min(int(area_sqft // min_area), _MAX_LOTS_TO_TRY)
    if max_possible < 2:
        return None

    setbacks = get_setbacks(zoning, "standard")
    if setbacks is None:
        return None

    for n in range(max_possible, 1, -1):
        result = _execute_split(
            parcel, n, min_area, min_width, setbacks, "standard",
            primary_structure=primary_structure, zoning=zoning,
            nearby_streets=nearby_streets,
        )
        if result is not None:
            return result
    return None


# ---------------------------------------------------------------------------
# Core split execution — two-phase: quick geometry then full validation
# ---------------------------------------------------------------------------

def _execute_split(
    parcel: Polygon,
    num_lots: int,
    min_area: float,
    min_width: float,
    setbacks: Setbacks,
    subdivision_type: str,
    primary_structure: Optional[Polygon] = None,
    zoning: str = "",
    nearby_streets: Optional[list] = None,
) -> Optional[SplitResult]:
    """
    Try to split *parcel* into *num_lots* conforming lots.

    Phase 1 — fast geometric checks (area, width, access, structure clear).
    Phase 2 — expensive buildable-envelope validation only on best candidate.
    """
    detection = detect_street_edges(parcel)
    if detection is None:
        return None

    street_edges_geom = [
        e.geometry for e in detection.edges if e.label == EdgeLabel.STREET
    ]
    if not street_edges_geom:
        return None

    street_union = unary_union(street_edges_geom)

    side_yard_buffer = setbacks.side_yard_ft
    bounds = parcel.bounds
    diag = math.hypot(bounds[2] - bounds[0], bounds[3] - bounds[1])

    street_az = detection.street_azimuth_deg

    # Directions to try — always the street direction; add perpendicular for corners
    azimuths_to_try = [street_az]
    num_street_edges = sum(1 for e in detection.edges if e.label == EdgeLabel.STREET)
    if num_street_edges >= 2:
        azimuths_to_try.append((street_az + 90) % 360)

    candidates: list[tuple[float, list[Polygon], list[LineString], float]] = []

    for measure_az in azimuths_to_try:
        measure_rad = math.radians(measure_az)
        split_rad = math.radians((measure_az + 90) % 360)

        centroid = parcel.centroid
        cx, cy = centroid.x, centroid.y

        coords = list(parcel.exterior.coords)
        projections = [
            (c[0] - cx) * math.sin(measure_rad) + (c[1] - cy) * math.cos(measure_rad)
            for c in coords
        ]
        proj_min = min(projections)
        proj_max = max(projections)
        proj_span = proj_max - proj_min

        if proj_span < min_width * num_lots:
            continue

        # Structure exclusion zone along this measurement axis
        s_excl_min = None
        s_excl_max = None
        if primary_structure is not None and not primary_structure.is_empty:
            try:
                s_coords = list(primary_structure.exterior.coords)
                s_projs = [
                    (c[0] - cx) * math.sin(measure_rad) + (c[1] - cy) * math.cos(measure_rad)
                    for c in s_coords
                ]
                both_sides_buffer = side_yard_buffer * 2
                s_excl_min = min(s_projs) - both_sides_buffer
                s_excl_max = max(s_projs) + both_sides_buffer
            except Exception:
                pass

        # Try a few offsets (fewer than before for speed)
        for offset_pct in [0.0, -0.03, 0.03, -0.07, 0.07, -0.12, 0.12]:
            positions = []
            for i in range(1, num_lots):
                t = proj_min + (proj_span * i / num_lots) + (proj_span * offset_pct)
                positions.append(t)

            if s_excl_min is not None and s_excl_max is not None:
                positions = _adjust_positions_around_structure(
                    positions, s_excl_min, s_excl_max, proj_min, proj_max,
                )
                if positions is None:
                    continue

            candidate = _quick_split(
                parcel, positions, centroid, measure_rad, split_rad, diag,
                min_area, min_width, primary_structure, street_union,
            )
            if candidate is not None:
                lots, lines, score = candidate
                candidates.append((score, lots, lines, measure_rad))

    if not candidates:
        return None

    # Pick the best candidate, then do full validation
    candidates.sort(key=lambda c: c[0], reverse=True)
    for score, lots, lines, measure_rad in candidates:
        validated = _full_validate(
            lots, setbacks, subdivision_type, primary_structure, score, lines,
            zoning=zoning,
        )
        if validated is not None:
            return validated

    return None


def _quick_split(
    parcel: Polygon,
    positions: list[float],
    centroid,
    measure_rad: float,
    split_rad: float,
    diag: float,
    min_area: float,
    min_width: float,
    primary_structure: Optional[Polygon],
    street_union,
) -> Optional[tuple[list[Polygon], list[LineString], float]]:
    """
    Phase 1: fast geometric split with basic area/width/access checks.
    No expensive buildable-envelope computation.
    """
    cx, cy = centroid.x, centroid.y
    lot_lines: list[LineString] = []
    remaining = parcel
    lots: list[Polygon] = []

    for pos in sorted(positions):
        px = cx + pos * math.sin(measure_rad)
        py = cy + pos * math.cos(measure_rad)
        dx = math.sin(split_rad) * diag
        dy = math.cos(split_rad) * diag
        split_line = LineString([(px - dx, py - dy), (px + dx, py + dy)])

        if primary_structure is not None and not primary_structure.is_empty:
            clipped = split_line.intersection(parcel)
            if clipped.intersects(primary_structure) and not clipped.touches(primary_structure):
                return None

        lot_lines.append(split_line)

        try:
            parts = ops.split(remaining, split_line)
        except Exception:
            return None

        geoms = [g for g in parts.geoms if isinstance(g, Polygon) and g.area > 1]
        if len(geoms) < 2:
            return None

        geoms.sort(key=lambda g: _project_centroid(g, centroid, measure_rad))
        lots.append(geoms[0])
        remaining = _merge_polygons(geoms[1:])
        if remaining is None:
            return None

    lots.append(remaining)

    if len(lots) != len(positions) + 1:
        return None

    # Check: primary structure fully inside one lot
    if primary_structure is not None and not primary_structure.is_empty:
        if not any(lot.contains(primary_structure) for lot in lots):
            return None

    # Quick per-lot checks
    total_area = 0.0
    for lot in lots:
        if lot.area < min_area:
            return None

        w = _estimate_lot_width(lot, measure_rad)
        if w < min_width:
            return None

        if street_union is not None and not _lot_has_street_access(lot, street_union):
            return None

        total_area += lot.area

    score = len(lots) * 10 + total_area / 1000.0
    return lots, lot_lines, score


def _full_validate(
    lots: list[Polygon],
    setbacks: Setbacks,
    subdivision_type: str,
    primary_structure: Optional[Polygon],
    score: float,
    lot_lines: list[LineString],
    zoning: str = "",
) -> Optional[SplitResult]:
    """
    Phase 2: expensive validation — buildable envelope and structure fit.
    Only called on the best candidate from phase 1.
    """
    lot_infos: list[LotInfo] = []

    for lot in lots:
        has_primary = (
            primary_structure is not None
            and not primary_structure.is_empty
            and lot.contains(primary_structure)
        )
        if has_primary:
            lot_infos.append(LotInfo(
                geometry=lot, area_sqft=lot.area, width_ft=0.0,
                buildable_area_sqft=lot.area * 0.3,
            ))
            continue

        # Full structure fit: inscribed rectangle must be >= 600sf
        sfit = fit_structure(lot, zoning, subdivision_type)
        if sfit is None or not sfit.fits:
            return None

        lot_infos.append(LotInfo(
            geometry=lot, area_sqft=lot.area, width_ft=0.0,
            buildable_area_sqft=sfit.area_sqft,
        ))

    num = len(lots)
    return SplitResult(
        lots=lots,
        lot_lines=lot_lines,
        num_lots=num,
        subdivision_type=subdivision_type,
        score=score,
        notes=f"{num} lots via {subdivision_type}",
        lot_infos=lot_infos,
    )


def _adjust_positions_around_structure(
    positions: list[float],
    excl_min: float,
    excl_max: float,
    proj_min: float,
    proj_max: float,
) -> Optional[list[float]]:
    """Shift split positions to avoid the structure exclusion zone."""
    adjusted = []
    for pos in positions:
        if excl_min <= pos <= excl_max:
            dist_to_low = pos - excl_min
            dist_to_high = excl_max - pos
            new_pos = excl_min - 1.0 if dist_to_low <= dist_to_high else excl_max + 1.0
            if new_pos < proj_min or new_pos > proj_max:
                return None
            adjusted.append(new_pos)
        else:
            adjusted.append(pos)
    adjusted.sort()
    for i in range(1, len(adjusted)):
        if abs(adjusted[i] - adjusted[i - 1]) < 5.0:
            return None
    return adjusted


# ---------------------------------------------------------------------------
# Street access check
# ---------------------------------------------------------------------------

def _lot_has_street_access(lot: Polygon, street_union) -> bool:
    """
    Quick geometric pre-filter: does the lot boundary touch the
    heuristic street edges? Real street validation (ROW-based)
    happens in batch_processor using check_lot_street_access().
    """
    try:
        street_strip = street_union.buffer(1.0)
        overlap = lot.intersection(street_strip)
        return not overlap.is_empty
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _project_centroid(geom: Polygon, origin, measure_rad: float) -> float:
    c = geom.centroid
    return (c.x - origin.x) * math.sin(measure_rad) + (c.y - origin.y) * math.cos(measure_rad)


def _merge_polygons(polys: list[Polygon]) -> Optional[Polygon]:
    if not polys:
        return None
    merged = polys[0]
    for p in polys[1:]:
        merged = merged.union(p)
    if isinstance(merged, MultiPolygon):
        parts = sorted(merged.geoms, key=lambda g: g.area, reverse=True)
        merged = parts[0]
    if isinstance(merged, Polygon):
        return merged
    return None


def _estimate_lot_width(lot: Polygon, measure_rad: float) -> float:
    """Estimate lot width along the measurement axis (street frontage)."""
    coords = list(lot.exterior.coords)
    projections = [
        c[0] * math.sin(measure_rad) + c[1] * math.cos(measure_rad)
        for c in coords
    ]
    return max(projections) - min(projections)
