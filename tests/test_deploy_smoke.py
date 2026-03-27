"""
Post-deployment smoke tests for the production site.

Run after every deploy to verify the site, API, and data integrity.

Usage:
    py -3.11 -m pytest tests/test_deploy_smoke.py -v
    py -3.11 -m pytest tests/test_deploy_smoke.py -v --prod   # test production
    py -3.11 -m pytest tests/test_deploy_smoke.py -v --local  # test local (default)
"""

import os

import pytest
import requests

LOCAL_URL = "http://localhost:8000"
PROD_URL = os.environ.get("PROD_URL", "https://localhost")

# Known government-owned parcels that must NOT be subdividable
EXCLUDED_OWNER_PINS = [
    "0821646753",  # 1000 S DUKE ST — CITY OF DURHAM
]


@pytest.fixture(scope="session")
def base_url(request):
    custom = request.config.getoption("--base-url")
    if custom:
        return custom.rstrip("/")
    if request.config.getoption("--prod"):
        return PROD_URL
    return LOCAL_URL


@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    s.timeout = 15
    return s


# ─── Site loads ──────────────────────────────────────────────


class TestSiteLoads:
    """These tests verify the nginx + SPA bundle. They only apply when
    running against a full stack (production or local docker compose)
    where nginx serves the frontend at /."""

    def _is_frontend(self, base_url, session):
        r = session.get(f"{base_url}/")
        return "<!doctype html>" in r.text.lower() or "<html" in r.text.lower()

    def test_homepage_returns_html(self, base_url, session):
        """Frontend SPA loads and returns the React app shell."""
        r = session.get(f"{base_url}/")
        assert r.status_code == 200
        if not self._is_frontend(base_url, session):
            pytest.skip("Backend-only (no nginx) — frontend tests not applicable")
        assert "Durham Subdividable Lots" in r.text

    def test_static_assets_referenced(self, base_url, session):
        """Built JS/CSS assets are referenced in the HTML."""
        r = session.get(f"{base_url}/")
        if not self._is_frontend(base_url, session):
            pytest.skip("Backend-only (no nginx) — frontend tests not applicable")
        assert "/assets/" in r.text, "No bundled assets found in HTML"


# ─── Core API endpoints ─────────────────────────────────────


class TestAnalysisStats:
    def test_stats_returns_200(self, base_url, session):
        r = session.get(f"{base_url}/api/analysis/stats")
        assert r.status_code == 200

    def test_stats_has_expected_fields(self, base_url, session):
        data = session.get(f"{base_url}/api/analysis/stats").json()
        for key in ["total_parcels", "total_analyzed", "total_subdividable",
                     "by_quick_filter", "by_subdivision_type", "by_zoning"]:
            assert key in data, f"Missing field: {key}"

    def test_parcels_analyzed(self, base_url, session):
        data = session.get(f"{base_url}/api/analysis/stats").json()
        assert data["total_parcels"] > 100_000, "Expected 100k+ parcels"
        assert data["total_analyzed"] > 100_000, "Expected 100k+ analyzed"

    def test_subdividable_count_reasonable(self, base_url, session):
        data = session.get(f"{base_url}/api/analysis/stats").json()
        assert 100 < data["total_subdividable"] < 10_000, (
            f"Subdividable count {data['total_subdividable']} outside expected range"
        )


class TestParcelsAPI:
    def test_list_parcels(self, base_url, session):
        r = session.get(f"{base_url}/api/parcels?limit=3")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert len(data["items"]) > 0

    def test_subdividable_filter(self, base_url, session):
        r = session.get(f"{base_url}/api/parcels?subdividable=true&limit=5")
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) > 0
        for item in items:
            assert item["quick_filter_result"].startswith("SUBDIVIDABLE") or \
                   item["quick_filter_result"] == "NEEDS_GEOMETRY"

    def test_address_search(self, base_url, session):
        r = session.get(f"{base_url}/api/parcels/search?q=Duke+St")
        assert r.status_code == 200
        results = r.json()
        assert len(results) > 0
        assert all("address" in item for item in results)

    def test_parcel_detail(self, base_url, session):
        listing = session.get(f"{base_url}/api/parcels?limit=1").json()["items"][0]
        parcel_id = listing["id"]
        r = session.get(f"{base_url}/api/parcels/{parcel_id}")
        assert r.status_code == 200
        detail = r.json()
        assert detail["id"] == parcel_id
        assert "analysis" in detail
        assert "pin" in detail
        assert "zoning" in detail

    def test_geojson_endpoint(self, base_url, session):
        r = session.get(
            f"{base_url}/api/parcels/geojson",
            params={"bbox": "-78.92,35.98,-78.88,36.02", "limit": 5},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) > 0
        feat = data["features"][0]
        assert feat["type"] == "Feature"
        assert "geometry" in feat
        assert "properties" in feat


class TestZoningRules:
    def test_valid_district(self, base_url, session):
        r = session.get(f"{base_url}/api/zoning-rules/RS-10")
        assert r.status_code == 200
        data = r.json()
        assert data["zone_code"] == "RS-10"
        assert data["min_lot_area_sqft"] == 10_000

    def test_invalid_district_404(self, base_url, session):
        r = session.get(f"{base_url}/api/zoning-rules/FAKE-99")
        assert r.status_code == 404


class TestForSaleListings:
    def test_for_sale_endpoint(self, base_url, session):
        r = session.get(f"{base_url}/api/parcels/for-sale?limit=3")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data


class TestUtilities:
    def test_utility_stats(self, base_url, session):
        r = session.get(f"{base_url}/api/utilities/stats")
        assert r.status_code == 200


# ─── Data integrity ──────────────────────────────────────────


class TestOwnerExclusions:
    """Government-owned parcels must never appear as subdividable."""

    def test_known_city_parcel_excluded(self, base_url, session):
        """1000 S DUKE ST (PIN 0821646753) is City of Durham — must not be subdividable."""
        r = session.get(f"{base_url}/api/parcels/search?q=1000+S+Duke")
        results = r.json()
        assert len(results) > 0
        parcel = results[0]
        assert parcel["is_subdividable"] is False, (
            f"City of Durham parcel {parcel['pin']} still showing as subdividable!"
        )

    def test_no_excluded_owners_in_subdividable_list(self, base_url, session):
        """Fetch subdividable parcels and verify none are government-owned."""
        r = session.get(f"{base_url}/api/parcels?subdividable=true&limit=50")
        items = r.json()["items"]
        for item in items:
            parcel_detail = session.get(f"{base_url}/api/parcels/{item['id']}").json()
            owner = (parcel_detail.get("property_owner") or "").upper()
            for pattern in ["CITY OF DURHAM", "COUNTY OF DURHAM", "DURHAM COUNTY",
                            "DURHAM PUBLIC SCHOOLS", "STATE OF NORTH CAROLINA",
                            "UNITED STATES", "HOUSING AUTHORITY", "DUKE UNIVERSITY",
                            "NORTH CAROLINA CENTRAL"]:
                assert pattern not in owner, (
                    f"Excluded owner '{owner}' found in subdividable parcel {item['id']}"
                )


# ─── Response time sanity checks ─────────────────────────────


class TestPerformance:
    def test_stats_under_3s(self, base_url, session):
        r = session.get(f"{base_url}/api/analysis/stats")
        assert r.elapsed.total_seconds() < 3, f"Stats took {r.elapsed.total_seconds():.1f}s"

    def test_parcel_list_under_2s(self, base_url, session):
        r = session.get(f"{base_url}/api/parcels?limit=20")
        assert r.elapsed.total_seconds() < 2, f"Parcel list took {r.elapsed.total_seconds():.1f}s"

    def test_geojson_under_5s(self, base_url, session):
        r = session.get(
            f"{base_url}/api/parcels/geojson",
            params={"bbox": "-78.92,35.98,-78.88,36.02", "limit": 500},
        )
        assert r.elapsed.total_seconds() < 5, f"GeoJSON took {r.elapsed.total_seconds():.1f}s"

    def test_search_under_2s(self, base_url, session):
        r = session.get(f"{base_url}/api/parcels/search?q=Main+St")
        assert r.elapsed.total_seconds() < 2, f"Search took {r.elapsed.total_seconds():.1f}s"
