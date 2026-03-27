"""
Setback engine — computes buildable envelopes from parcel polygons.

Given a parcel polygon and per-edge setback distances, compute the interior
region where structures may be placed.  Two modes:

1. **Simple**: uniform front/side/rear setbacks applied by labeling edges via
   street detection, then inward-offsetting each edge.
2. **Per-edge**: each edge gets its own setback distance.

All geometry is EPSG:2264 (NC State Plane, feet).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import unary_union

from backend.analysis.street_detection import EdgeLabel, detect_street_edges
from backend.udo.rules_engine import Setbacks


@dataclass
class BuildableEnvelope:
    envelope: Optional[Polygon]
    area_sqft: float
    valid: bool
    notes: str = ""


def compute_buildable_envelope(
    parcel_geom_sp: Polygon,
    setbacks: Setbacks,
) -> Optional[BuildableEnvelope]:
    """
    Compute the buildable envelope using edge-specific setbacks.

    Each edge is labeled (STREET, SIDE_LEFT/RIGHT, REAR) by the street
    detector, then inward-offset by the corresponding setback distance.
    The buildable area is the intersection of all the inward half-planes
    clipped to the parcel boundary.

    Parameters
    ----------
    parcel_geom_sp : Polygon
        Parcel in EPSG:2264.
    setbacks : Setbacks
        Per-edge-type setback distances in feet.

    Returns
    -------
    BuildableEnvelope or None on geometry failure.
    """
    if parcel_geom_sp is None or parcel_geom_sp.is_empty:
        return None

    detection = detect_street_edges(parcel_geom_sp)
    if detection is None:
        return _envelope_from_uniform_buffer(parcel_geom_sp, setbacks)

    setback_map = {
        EdgeLabel.STREET: setbacks.street_yard_ft,
        EdgeLabel.SIDE_LEFT: setbacks.side_yard_ft,
        EdgeLabel.SIDE_RIGHT: setbacks.side_yard_ft,
        EdgeLabel.REAR: setbacks.rear_yard_ft,
    }

    return _offset_edges(parcel_geom_sp, detection.edges, setback_map)


def compute_simple_envelope(
    parcel_geom_sp: Polygon,
    front: float,
    side: float,
    rear: float,
) -> Optional[BuildableEnvelope]:
    """
    Convenience wrapper: supply front/side/rear in feet, edge-detect
    internally to map to edges.
    """
    sb = Setbacks(street_yard_ft=front, side_yard_ft=side, rear_yard_ft=rear)
    return compute_buildable_envelope(parcel_geom_sp, sb)


def compute_uniform_envelope(
    parcel_geom_sp: Polygon,
    buffer_ft: float,
) -> Optional[BuildableEnvelope]:
    """
    Quick uniform inward buffer — ignores per-edge differences.
    Useful as a conservative lower-bound estimate.
    """
    if parcel_geom_sp is None or parcel_geom_sp.is_empty:
        return None
    return _envelope_from_uniform_buffer(
        parcel_geom_sp,
        Setbacks(street_yard_ft=buffer_ft, side_yard_ft=buffer_ft, rear_yard_ft=buffer_ft),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _envelope_from_uniform_buffer(
    parcel: Polygon,
    setbacks: Setbacks,
) -> Optional[BuildableEnvelope]:
    """Fallback: use the largest setback as a uniform buffer."""
    buf_dist = max(setbacks.street_yard_ft, setbacks.side_yard_ft, setbacks.rear_yard_ft)
    envelope = parcel.buffer(-buf_dist)
    return _wrap_envelope(envelope, "uniform buffer fallback")


def _offset_edges(
    parcel: Polygon,
    labeled_edges: list,
    setback_map: dict[EdgeLabel, float],
) -> Optional[BuildableEnvelope]:
    """
    For each labeled edge, create a half-plane by offsetting the edge inward.
    The buildable area is the intersection of all half-planes with the parcel.
    """
    if not labeled_edges:
        return None

    buffered_lines: list[Polygon] = []
    for edge in labeled_edges:
        sb_dist = setback_map.get(edge.label, 0)
        if sb_dist <= 0:
            continue

        offset = _offset_line_inward(edge.geometry, sb_dist, parcel)
        if offset is not None:
            buffered_lines.append(offset)

    if not buffered_lines:
        return _wrap_envelope(parcel, "no setbacks applied")

    # Start with the parcel, subtract each setback strip
    exclusion = unary_union(buffered_lines)
    envelope = parcel.difference(exclusion)
    return _wrap_envelope(envelope, "per-edge setback")


def _offset_line_inward(
    edge: LineString,
    distance: float,
    parcel: Polygon,
) -> Optional[Polygon]:
    """
    Create a setback strip: buffer the edge outward then clip to parcel.
    The strip is the area within `distance` of the edge, inside the parcel.
    """
    strip = edge.buffer(distance, cap_style="flat")
    clipped = strip.intersection(parcel)
    if clipped.is_empty:
        return None
    if isinstance(clipped, (Polygon, MultiPolygon)):
        return clipped
    return None


def _wrap_envelope(geom, notes: str) -> Optional[BuildableEnvelope]:
    """Normalize geometry into a BuildableEnvelope."""
    if geom is None or geom.is_empty:
        return BuildableEnvelope(envelope=None, area_sqft=0, valid=False, notes=notes)

    if isinstance(geom, MultiPolygon):
        # Take the largest polygon
        polys = sorted(geom.geoms, key=lambda p: p.area, reverse=True)
        geom = polys[0]

    if not isinstance(geom, Polygon):
        return BuildableEnvelope(envelope=None, area_sqft=0, valid=False, notes=notes)

    if not geom.is_valid:
        geom = geom.buffer(0)
        if geom.is_empty:
            return BuildableEnvelope(envelope=None, area_sqft=0, valid=False, notes=notes)

    return BuildableEnvelope(
        envelope=geom,
        area_sqft=geom.area,
        valid=True,
        notes=notes,
    )
