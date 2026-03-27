"""
UDO Rules Engine — returns applicable subdivision rules for a given zoning code.

Source of truth: backend/udo/udo_rules.json (hand-verified from Durham UDO).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_RULES_PATH = Path(__file__).parent / "udo_rules.json"
_rules_cache: dict | None = None

OVERLAY_PATTERN = re.compile(
    r"[/ ]*(?:PDR|CU|OL|HP|NP|CUD|MU|CBD|CONS|NC|RTP|CC|OI|D|NR)\b",
    re.IGNORECASE,
)

RESIDENTIAL_PREFIXES = ("RS-", "RU-", "RC")


def _load_rules() -> dict:
    global _rules_cache
    if _rules_cache is None:
        with open(_RULES_PATH) as f:
            _rules_cache = json.load(f)
    return _rules_cache


def _strip_overlays(zoning_code: str) -> str:
    """Extract the base residential zone from a compound zoning code."""
    code = zoning_code.strip()
    code = OVERLAY_PATTERN.sub("", code).strip()
    code = re.sub(r"\s+", " ", code).strip()
    if "/" in code:
        code = code.split("/")[0].strip()
    return code


def _is_residential(base_code: str) -> bool:
    return any(base_code.startswith(p) for p in RESIDENTIAL_PREFIXES)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Setbacks:
    street_yard_ft: float
    side_yard_ft: float
    rear_yard_ft: float


@dataclass
class StructureLimits:
    max_footprint_sqft: float | None
    max_total_sqft: float | None
    max_height_ft: float
    max_height_stories: int


@dataclass
class DistrictRules:
    zone_code: str
    full_name: str
    tier: str
    min_lot_area_sqft: float
    min_lot_width_ft: float
    setbacks: Setbacks
    max_density_per_acre: float | None
    max_height_stories: int
    max_height_ft: float
    allowed_housing_types: list[str]
    small_lot_eligible: bool
    small_lot_urban_only: bool


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_base_zone(zoning_code: str) -> str | None:
    """Return the base residential zone code, or None if not residential."""
    base = _strip_overlays(zoning_code)
    if not _is_residential(base):
        return None
    rules = _load_rules()
    if base in rules["residential_districts"]:
        return base
    return None


def get_district_rules(zoning_code: str) -> DistrictRules | None:
    """Full rule set for a zoning district. Returns None for non-residential."""
    base = _strip_overlays(zoning_code)
    if not _is_residential(base):
        return None

    rules = _load_rules()
    district = rules["residential_districts"].get(base)
    if district is None:
        return None

    conv = district["conventional"]["single_family_detached"]
    slo = rules["small_lot_option"]

    any_tier = base in slo["applicable_districts_any_tier"]
    urban_only = base in slo["applicable_districts_urban_tier_only"]

    return DistrictRules(
        zone_code=base,
        full_name=district["full_name"],
        tier=district["tier"],
        min_lot_area_sqft=conv["min_lot_area_sqft"],
        min_lot_width_ft=conv["min_lot_width_ft"],
        setbacks=Setbacks(
            street_yard_ft=conv["street_yard_ft"],
            side_yard_ft=conv["side_yard_ft"],
            rear_yard_ft=conv["rear_yard_ft"],
        ),
        max_density_per_acre=conv.get("max_density_per_acre"),
        max_height_stories=district["max_height_stories"],
        max_height_ft=district["max_height_ft"],
        allowed_housing_types=district["allowed_housing_types"],
        small_lot_eligible=any_tier or urban_only,
        small_lot_urban_only=urban_only,
    )


def get_min_lot_size(zoning_code: str, subdivision_type: str = "conventional") -> float | None:
    """
    Minimum lot area in sqft for the given zone and subdivision type.
    subdivision_type: "conventional", "cluster", or "small_lot"
    """
    base = _strip_overlays(zoning_code)
    rules = _load_rules()
    district = rules["residential_districts"].get(base)
    if district is None:
        return None

    if subdivision_type == "small_lot":
        slo = rules["small_lot_option"]
        if base in slo["not_allowed"]:
            return None
        if base in slo["applicable_districts_any_tier"] or base in slo["applicable_districts_urban_tier_only"]:
            return slo["min_lot_area_sqft"]
        return None

    if subdivision_type == "cluster":
        cluster = district.get("cluster", {})
        sfd = cluster.get("single_family_detached")
        if sfd and "min_lot_area_sqft" in sfd:
            return sfd["min_lot_area_sqft"]
        return None

    conv = district["conventional"]["single_family_detached"]
    return conv["min_lot_area_sqft"]


def is_small_lot_eligible(zoning_code: str, tier: str = "urban") -> bool:
    """Check if the small lot option is available for this zone + tier combo."""
    base = _strip_overlays(zoning_code)
    rules = _load_rules()
    slo = rules["small_lot_option"]

    if base in slo["not_allowed"]:
        return False
    if base in slo["applicable_districts_any_tier"]:
        return True
    if base in slo["applicable_districts_urban_tier_only"]:
        return tier.lower() == "urban"
    return False


def get_setbacks(zoning_code: str, lot_type: str = "standard") -> Setbacks | None:
    """
    Return setbacks for a given zone.
    lot_type: "standard" (conventional), "small_lot", or "flag_lot"
    """
    base = _strip_overlays(zoning_code)
    rules = _load_rules()

    if lot_type == "small_lot":
        slo = rules["small_lot_option"]
        return Setbacks(
            street_yard_ft=slo["street_yard_ft"],
            side_yard_ft=slo["side_yard_ft"],
            rear_yard_ft=slo["rear_yard_ft"],
        )

    district = rules["residential_districts"].get(base)
    if district is None:
        return None

    conv = district["conventional"]["single_family_detached"]

    if lot_type == "flag_lot":
        return Setbacks(
            street_yard_ft=conv["side_yard_ft"],  # front setback = side yard of district
            side_yard_ft=conv["side_yard_ft"],
            rear_yard_ft=conv["rear_yard_ft"],
        )

    return Setbacks(
        street_yard_ft=conv["street_yard_ft"],
        side_yard_ft=conv["side_yard_ft"],
        rear_yard_ft=conv["rear_yard_ft"],
    )


def get_max_structure_size(zoning_code: str, lot_type: str = "standard") -> StructureLimits | None:
    """Return structure size limits for the given zone and lot type."""
    base = _strip_overlays(zoning_code)
    rules = _load_rules()

    if lot_type == "small_lot":
        slo = rules["small_lot_option"]
        return StructureLimits(
            max_footprint_sqft=slo["max_building_footprint_sqft"],
            max_total_sqft=slo["max_building_total_sqft"],
            max_height_ft=slo["max_height_ft"],
            max_height_stories=1,
        )

    district = rules["residential_districts"].get(base)
    if district is None:
        return None

    return StructureLimits(
        max_footprint_sqft=None,  # no explicit footprint limit for standard lots
        max_total_sqft=None,
        max_height_ft=district["max_height_ft"],
        max_height_stories=district["max_height_stories"],
    )


def get_flag_lot_rules() -> dict:
    """Return flag lot specific rules."""
    rules = _load_rules()
    return rules["flag_lot"]


def get_lot_averaging_rules() -> dict:
    """Return lot averaging rules."""
    rules = _load_rules()
    return rules["lot_averaging"]
