"""Unit tests for the UDO rules engine."""

import pytest
from backend.udo.rules_engine import (
    get_base_zone,
    get_district_rules,
    get_flag_lot_rules,
    get_lot_averaging_rules,
    get_max_structure_size,
    get_min_lot_size,
    get_setbacks,
    is_small_lot_eligible,
)


class TestBaseZoneParsing:
    def test_simple_zone(self):
        assert get_base_zone("RS-10") == "RS-10"

    def test_compound_pdr(self):
        assert get_base_zone("RS-10/PDR") == "RS-10"

    def test_compound_cu(self):
        assert get_base_zone("RU-5 CU") == "RU-5"

    def test_compound_ol(self):
        assert get_base_zone("RS-M OL") == "RS-M"

    def test_non_residential(self):
        assert get_base_zone("C-1") is None

    def test_industrial(self):
        assert get_base_zone("I-2") is None

    def test_office(self):
        assert get_base_zone("OI") is None

    def test_ru5_2(self):
        assert get_base_zone("RU-5(2)") == "RU-5(2)"


class TestMinLotSize:
    def test_rs10_conventional(self):
        assert get_min_lot_size("RS-10", "conventional") == 10_000

    def test_rs20_conventional(self):
        assert get_min_lot_size("RS-20", "conventional") == 20_000

    def test_rs8_conventional(self):
        assert get_min_lot_size("RS-8", "conventional") == 8_000

    def test_rsm_conventional(self):
        assert get_min_lot_size("RS-M", "conventional") == 5_000

    def test_ru5_conventional(self):
        assert get_min_lot_size("RU-5", "conventional") == 5_000

    def test_rum_conventional(self):
        assert get_min_lot_size("RU-M", "conventional") == 3_500

    def test_ru5_small_lot(self):
        assert get_min_lot_size("RU-5", "small_lot") == 2_000

    def test_rs10_small_lot(self):
        assert get_min_lot_size("RS-10", "small_lot") == 2_000

    def test_rs20_small_lot_not_allowed(self):
        assert get_min_lot_size("RS-20", "small_lot") is None

    def test_rs10_cluster(self):
        assert get_min_lot_size("RS-10", "cluster") == 5_000

    def test_non_residential(self):
        assert get_min_lot_size("C-1", "conventional") is None


class TestSmallLotEligibility:
    def test_rs20_never(self):
        assert is_small_lot_eligible("RS-20", "urban") is False
        assert is_small_lot_eligible("RS-20", "suburban") is False

    def test_rs10_urban_only(self):
        assert is_small_lot_eligible("RS-10", "urban") is True
        assert is_small_lot_eligible("RS-10", "suburban") is False

    def test_rs8_urban_only(self):
        assert is_small_lot_eligible("RS-8", "urban") is True
        assert is_small_lot_eligible("RS-8", "suburban") is False

    def test_rsm_any_tier(self):
        assert is_small_lot_eligible("RS-M", "urban") is True
        assert is_small_lot_eligible("RS-M", "suburban") is True

    def test_ru5_any_tier(self):
        assert is_small_lot_eligible("RU-5", "urban") is True
        assert is_small_lot_eligible("RU-5", "suburban") is True

    def test_ru52_any_tier(self):
        assert is_small_lot_eligible("RU-5(2)", "urban") is True
        assert is_small_lot_eligible("RU-5(2)", "suburban") is True

    def test_rum_any_tier(self):
        assert is_small_lot_eligible("RU-M", "urban") is True
        assert is_small_lot_eligible("RU-M", "suburban") is True

    def test_compound_code(self):
        assert is_small_lot_eligible("RU-5 CU", "urban") is True

    def test_non_residential(self):
        assert is_small_lot_eligible("C-1", "urban") is False


class TestSetbacks:
    def test_rs10_standard(self):
        sb = get_setbacks("RS-10", "standard")
        assert sb.street_yard_ft == 25
        assert sb.side_yard_ft == 10
        assert sb.rear_yard_ft == 25

    def test_small_lot_setbacks(self):
        sb = get_setbacks("RU-5", "small_lot")
        assert sb.street_yard_ft == 10
        assert sb.side_yard_ft == 5
        assert sb.rear_yard_ft == 15

    def test_flag_lot_front_equals_side(self):
        sb = get_setbacks("RS-10", "flag_lot")
        assert sb.street_yard_ft == 10  # equals side yard of RS-10

    def test_non_residential(self):
        assert get_setbacks("C-1", "standard") is None


class TestStructureLimits:
    def test_small_lot_max_footprint(self):
        limits = get_max_structure_size("RU-5", "small_lot")
        assert limits.max_footprint_sqft == 800

    def test_small_lot_max_total(self):
        limits = get_max_structure_size("RU-5", "small_lot")
        assert limits.max_total_sqft == 1200

    def test_small_lot_max_height(self):
        limits = get_max_structure_size("RU-5", "small_lot")
        assert limits.max_height_ft == 25

    def test_standard_no_footprint_limit(self):
        limits = get_max_structure_size("RS-10", "standard")
        assert limits.max_footprint_sqft is None
        assert limits.max_height_ft == 40
        assert limits.max_height_stories == 3


class TestFlagLotRules:
    def test_pole_width(self):
        rules = get_flag_lot_rules()
        assert rules["min_pole_width_ft"] == 20

    def test_front_setback_equals_side(self):
        rules = get_flag_lot_rules()
        assert rules["front_setback_equals"] == "side_yard_setback_of_district"


class TestDistrictRules:
    def test_rs10_full(self):
        dr = get_district_rules("RS-10")
        assert dr is not None
        assert dr.zone_code == "RS-10"
        assert dr.min_lot_area_sqft == 10_000
        assert dr.min_lot_width_ft == 75
        assert dr.setbacks.street_yard_ft == 25
        assert dr.small_lot_eligible is True
        assert dr.small_lot_urban_only is True

    def test_rs20_no_small_lot(self):
        dr = get_district_rules("RS-20")
        assert dr is not None
        assert dr.small_lot_eligible is False

    def test_compound_code(self):
        dr = get_district_rules("RS-10/PDR")
        assert dr is not None
        assert dr.zone_code == "RS-10"

    def test_non_residential_returns_none(self):
        assert get_district_rules("OI-1") is None


class TestLotAveraging:
    def test_max_reduction(self):
        rules = get_lot_averaging_rules()
        assert rules["max_reduction_pct"] == 15
