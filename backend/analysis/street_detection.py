"""
Street edge detection for parcel polygons.

Heuristic approach: on typical rectangular residential lots the shortest
edge(s) face the street.  We label every exterior edge as STREET, SIDE_LEFT,
SIDE_RIGHT, or REAR so that downstream modules can orient setbacks correctly.

All geometry is expected in NC State Plane (EPSG:2264, units = feet).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from shapely.geometry import LineString, Point, Polygon


class EdgeLabel(str, Enum):
    STREET = "STREET"
    SIDE_LEFT = "SIDE_LEFT"
    SIDE_RIGHT = "SIDE_RIGHT"
    REAR = "REAR"


@dataclass
class LabeledEdge:
    label: EdgeLabel
    geometry: LineString
    length_ft: float
    azimuth_deg: float


@dataclass
class StreetDetectionResult:
    edges: list[LabeledEdge] = field(default_factory=list)
    street_frontage_ft: float = 0.0
    street_azimuth_deg: float = 0.0
    confidence: str = "low"


def _azimuth(p0: tuple[float, float], p1: tuple[float, float]) -> float:
    """Return compass azimuth in degrees (0=N, 90=E) between two points."""
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    angle = math.degrees(math.atan2(dx, dy)) % 360
    return angle


def _edge_segments(polygon: Polygon) -> list[tuple[LineString, float, float]]:
    """Extract edges from polygon exterior as (LineString, length, azimuth)."""
    coords = list(polygon.exterior.coords)
    segments = []
    for i in range(len(coords) - 1):
        p0, p1 = coords[i], coords[i + 1]
        ls = LineString([p0, p1])
        length = ls.length
        if length < 0.1:
            continue
        az = _azimuth(p0, p1)
        segments.append((ls, length, az))
    return segments


def _normalize_azimuth(az: float) -> float:
    """Normalize azimuth to 0-180 range (treat opposite directions as same)."""
    return az % 180


def _group_parallel_edges(
    segments: list[tuple[LineString, float, float]],
    tolerance_deg: float = 15.0,
) -> list[list[int]]:
    """Group edge indices by roughly parallel orientation."""
    groups: list[list[int]] = []
    norm_azimuths = [_normalize_azimuth(az) for _, _, az in segments]

    assigned = [False] * len(segments)
    for i in range(len(segments)):
        if assigned[i]:
            continue
        group = [i]
        assigned[i] = True
        for j in range(i + 1, len(segments)):
            if assigned[j]:
                continue
            diff = abs(norm_azimuths[i] - norm_azimuths[j])
            if diff > 90:
                diff = 180 - diff
            if diff <= tolerance_deg:
                group.append(j)
                assigned[j] = True
        groups.append(group)

    return groups


def detect_street_edges(parcel_geom_sp: Polygon) -> Optional[StreetDetectionResult]:
    """
    Detect which edges of a parcel polygon face a street.

    Parameters
    ----------
    parcel_geom_sp : Polygon
        Parcel boundary in EPSG:2264 (NC State Plane, feet).

    Returns
    -------
    StreetDetectionResult with labeled edges and street frontage measurement.
    Returns None if the geometry is invalid or degenerate.
    """
    if parcel_geom_sp is None or parcel_geom_sp.is_empty:
        return None
    if not isinstance(parcel_geom_sp, Polygon):
        return None
    if not parcel_geom_sp.is_valid:
        parcel_geom_sp = parcel_geom_sp.buffer(0)
        if parcel_geom_sp.is_empty:
            return None

    segments = _edge_segments(parcel_geom_sp)
    if len(segments) < 3:
        return None

    centroid = parcel_geom_sp.centroid
    groups = _group_parallel_edges(segments)

    # For rectangular-ish lots, we expect two dominant edge groups.
    # The group with shorter total length is the street/rear pair,
    # and the group with longer total length is the side pair.
    # Within the shorter group, the edge closest to "outside" is street.

    group_stats = []
    for g in groups:
        total_len = sum(segments[i][1] for i in g)
        group_stats.append((total_len, g))
    group_stats.sort(key=lambda x: x[0])

    if len(group_stats) < 2:
        # Irregular lot — fall back to shortest-edge-is-street
        return _fallback_detection(segments, centroid, parcel_geom_sp)

    short_group_idxs = group_stats[0][1]  # street/rear candidates
    long_group_idxs = group_stats[1][1]   # side candidates

    # Pick street edge: the one in the short group farthest from centroid
    # (street is on the periphery, rear is closer to centroid for typical lots)
    # Actually reversed: shortest edge nearest to the bounding box edge
    street_idx, rear_idx = _pick_street_and_rear(
        short_group_idxs, segments, centroid, parcel_geom_sp,
    )

    # Assign side edges: left/right relative to street direction
    side_labels = _assign_side_labels(
        long_group_idxs, segments, segments[street_idx],
    )

    labeled: list[LabeledEdge] = []
    street_frontage = 0.0
    street_az = 0.0

    for i, (geom, length, az) in enumerate(segments):
        if i == street_idx:
            label = EdgeLabel.STREET
            street_frontage += length
            street_az = az
        elif i == rear_idx:
            label = EdgeLabel.REAR
        elif i in side_labels:
            label = side_labels[i]
        else:
            # Extra edges on irregular lots — classify by proximity to street/rear
            mid = geom.interpolate(0.5, normalized=True)
            d_street = mid.distance(segments[street_idx][0].interpolate(0.5, normalized=True))
            d_rear = mid.distance(segments[rear_idx][0].interpolate(0.5, normalized=True))
            if d_street < d_rear:
                label = EdgeLabel.STREET
                street_frontage += length
            else:
                label = EdgeLabel.REAR

        labeled.append(LabeledEdge(label=label, geometry=geom, length_ft=length, azimuth_deg=az))

    confidence = "high" if len(segments) == 4 else "medium" if len(segments) <= 6 else "low"

    return StreetDetectionResult(
        edges=labeled,
        street_frontage_ft=street_frontage,
        street_azimuth_deg=street_az,
        confidence=confidence,
    )


def _pick_street_and_rear(
    candidate_idxs: list[int],
    segments: list[tuple[LineString, float, float]],
    centroid: Point,
    polygon: Polygon,
) -> tuple[int, int]:
    """
    Among two roughly-parallel candidate edges, pick which is street and which
    is rear.  The edge farther from centroid is assumed to be the street edge
    (residential lots usually have depth > width, so the centroid is closer to
    the rear than the front).
    """
    if len(candidate_idxs) == 1:
        return candidate_idxs[0], candidate_idxs[0]

    dists = []
    for idx in candidate_idxs:
        mid = segments[idx][0].interpolate(0.5, normalized=True)
        dists.append((mid.distance(centroid), idx))
    dists.sort(key=lambda x: x[0], reverse=True)

    street_idx = dists[0][1]
    rear_idx = dists[-1][1]
    return street_idx, rear_idx


def _assign_side_labels(
    side_idxs: list[int],
    segments: list[tuple[LineString, float, float]],
    street_segment: tuple[LineString, float, float],
) -> dict[int, EdgeLabel]:
    """
    Label side edges as LEFT or RIGHT relative to the street direction.
    Standing on the street looking into the lot: left is LEFT, right is RIGHT.
    """
    if not side_idxs:
        return {}

    street_geom = street_segment[0]
    street_mid = street_geom.interpolate(0.5, normalized=True)
    street_coords = list(street_geom.coords)
    street_dx = street_coords[1][0] - street_coords[0][0]
    street_dy = street_coords[1][1] - street_coords[0][1]

    labels: dict[int, EdgeLabel] = {}
    for idx in side_idxs:
        side_mid = segments[idx][0].interpolate(0.5, normalized=True)
        dx = side_mid.x - street_mid.x
        dy = side_mid.y - street_mid.y
        cross = street_dx * dy - street_dy * dx
        labels[idx] = EdgeLabel.SIDE_LEFT if cross > 0 else EdgeLabel.SIDE_RIGHT

    return labels


def _fallback_detection(
    segments: list[tuple[LineString, float, float]],
    centroid: Point,
    polygon: Polygon,
) -> StreetDetectionResult:
    """Fallback: shortest edge = street, longest opposite = rear."""
    sorted_by_len = sorted(range(len(segments)), key=lambda i: segments[i][1])

    street_idx = sorted_by_len[0]
    rear_idx = sorted_by_len[-1]

    labeled = []
    side_count = 0
    for i, (geom, length, az) in enumerate(segments):
        if i == street_idx:
            label = EdgeLabel.STREET
        elif i == rear_idx:
            label = EdgeLabel.REAR
        else:
            label = EdgeLabel.SIDE_LEFT if side_count % 2 == 0 else EdgeLabel.SIDE_RIGHT
            side_count += 1
        labeled.append(LabeledEdge(label=label, geometry=geom, length_ft=length, azimuth_deg=az))

    return StreetDetectionResult(
        edges=labeled,
        street_frontage_ft=segments[street_idx][1],
        street_azimuth_deg=segments[street_idx][2],
        confidence="low",
    )
