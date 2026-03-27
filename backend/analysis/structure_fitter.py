"""
Structure fitter — find the largest axis-aligned rectangle that fits inside
the buildable envelope of a proposed lot.

Used to verify that a meaningful structure can actually be built on each
lot produced by the splitter.  The minimum footprint for a standard lot
is 600 sf; small lots allow up to 800 sf.

All geometry is EPSG:2264 (NC State Plane, feet).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shapely.geometry import Polygon, box

from backend.analysis.setback_engine import compute_buildable_envelope
from backend.udo.rules_engine import (
    Setbacks,
    get_max_structure_size,
    get_setbacks,
)

_STANDARD_MIN_FOOTPRINT = 600.0
_SMALL_LOT_MAX_FOOTPRINT = 800.0
_DEFAULT_ASPECT_RATIO = 2.5  # max depth/width for small lot narrow homes


@dataclass
class StructureFit:
    footprint_geom: Optional[Polygon]
    area_sqft: float
    width_ft: float
    depth_ft: float
    fits: bool
    max_allowed_sqft: Optional[float] = None
    notes: str = ""


def fit_structure(
    lot_geom_sp: Polygon,
    zoning: str,
    lot_type: str = "standard",
) -> Optional[StructureFit]:
    """
    Attempt to fit the largest axis-aligned rectangle inside the buildable
    envelope of a lot.

    Parameters
    ----------
    lot_geom_sp : Polygon
        Lot boundary in EPSG:2264.
    zoning : str
        Zoning code.
    lot_type : str
        "standard" or "small_lot".

    Returns
    -------
    StructureFit or None if the envelope cannot be computed.
    """
    if lot_geom_sp is None or lot_geom_sp.is_empty:
        return None

    setbacks = get_setbacks(zoning, lot_type)
    if setbacks is None:
        return None

    envelope_result = compute_buildable_envelope(lot_geom_sp, setbacks)
    if envelope_result is None or not envelope_result.valid or envelope_result.envelope is None:
        return StructureFit(
            footprint_geom=None, area_sqft=0, width_ft=0, depth_ft=0,
            fits=False, notes="no buildable envelope",
        )

    envelope = envelope_result.envelope
    limits = get_max_structure_size(zoning, lot_type)

    min_footprint = _STANDARD_MIN_FOOTPRINT
    max_footprint: Optional[float] = None
    if limits:
        max_footprint = limits.max_footprint_sqft
    if lot_type == "small_lot":
        min_footprint = _STANDARD_MIN_FOOTPRINT
        max_footprint = _SMALL_LOT_MAX_FOOTPRINT if max_footprint is None else max_footprint

    rect, width, depth = _find_largest_inscribed_rect(envelope, max_footprint)

    if rect is None:
        return StructureFit(
            footprint_geom=None, area_sqft=0, width_ft=0, depth_ft=0,
            fits=False, max_allowed_sqft=max_footprint,
            notes="could not inscribe rectangle",
        )

    area = rect.area
    aspect = max(width, depth) / max(min(width, depth), 0.1)
    max_aspect = _DEFAULT_ASPECT_RATIO + 0.5
    fits = area >= min_footprint and aspect <= max_aspect

    notes = ""
    if area < min_footprint:
        notes = f"footprint {area:.0f} sf < min {min_footprint:.0f} sf"
    elif aspect > max_aspect:
        notes = f"aspect ratio {aspect:.1f}:1 exceeds max {max_aspect:.1f}:1"

    return StructureFit(
        footprint_geom=rect,
        area_sqft=area,
        width_ft=width,
        depth_ft=depth,
        fits=fits,
        max_allowed_sqft=max_footprint,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Largest inscribed axis-aligned rectangle
# ---------------------------------------------------------------------------

def _find_largest_inscribed_rect(
    envelope: Polygon,
    max_area: Optional[float] = None,
    grid_steps: int = 12,
) -> tuple[Optional[Polygon], float, float]:
    """
    Find the largest axis-aligned rectangle fully contained in `envelope`.

    Uses a grid search over candidate center points within the envelope's
    bounding box, then binary-searches width/depth at each point.

    Parameters
    ----------
    envelope : Polygon
        The buildable region.
    max_area : float or None
        Cap on rectangle area (e.g. 800 sf for small lots).
    grid_steps : int
        Resolution of the center-point grid.

    Returns
    -------
    (rectangle_polygon, width, depth) or (None, 0, 0).
    """
    minx, miny, maxx, maxy = envelope.bounds
    span_x = maxx - minx
    span_y = maxy - miny

    if span_x < 1 or span_y < 1:
        return None, 0.0, 0.0

    best_area = 0.0
    best_rect: Optional[Polygon] = None
    best_w = 0.0
    best_d = 0.0

    step_x = span_x / grid_steps
    step_y = span_y / grid_steps

    for ix in range(grid_steps + 1):
        cx = minx + ix * step_x
        for iy in range(grid_steps + 1):
            cy = miny + iy * step_y

            w, d = _max_rect_at_point(cx, cy, envelope, span_x, span_y)
            if w < 1 or d < 1:
                continue

            # Constrain aspect ratio first, then cap area
            aspect = max(w, d) / max(min(w, d), 0.1)
            if aspect > _DEFAULT_ASPECT_RATIO:
                short = min(w, d)
                long_max = short * _DEFAULT_ASPECT_RATIO
                if w > d:
                    w = long_max
                else:
                    d = long_max

            area = w * d
            if max_area and area > max_area:
                scale = (max_area / area) ** 0.5
                w *= scale
                d *= scale
                area = w * d

            if area > best_area:
                r = box(cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2)
                if envelope.contains(r):
                    best_area = area
                    best_rect = r
                    best_w = w
                    best_d = d

    return best_rect, best_w, best_d


def _max_rect_at_point(
    cx: float,
    cy: float,
    envelope: Polygon,
    max_w: float,
    max_d: float,
) -> tuple[float, float]:
    """
    Binary-search for the largest axis-aligned rectangle centered at (cx, cy)
    that fits inside `envelope`.  Searches width and depth independently.
    """
    from shapely.geometry import Point
    if not envelope.contains(Point(cx, cy)):
        return 0.0, 0.0

    w = _binary_search_dim(cx, cy, max_w, envelope, axis="x")
    d = _binary_search_dim(cx, cy, max_d, envelope, axis="y")

    # Refine: after finding w with full height, re-check with actual depth
    if w > 0 and d > 0:
        r = box(cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2)
        if not envelope.contains(r):
            # Shrink iteratively
            for _ in range(8):
                w *= 0.9
                d *= 0.9
                r = box(cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2)
                if envelope.contains(r):
                    break
            else:
                return 0.0, 0.0

    return w, d


def _binary_search_dim(
    cx: float,
    cy: float,
    max_dim: float,
    envelope: Polygon,
    axis: str,
    steps: int = 12,
) -> float:
    """Binary search for the maximum extent along one axis."""
    lo, hi = 0.0, max_dim

    for _ in range(steps):
        mid = (lo + hi) / 2
        if axis == "x":
            test = box(cx - mid / 2, cy - 0.5, cx + mid / 2, cy + 0.5)
        else:
            test = box(cx - 0.5, cy - mid / 2, cx + 0.5, cy + mid / 2)

        if envelope.contains(test):
            lo = mid
        else:
            hi = mid

    return lo
