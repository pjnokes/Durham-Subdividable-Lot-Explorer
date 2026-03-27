"""
Download all Durham parcels from ArcGIS FeatureServer into PostGIS.

Source: https://services2.arcgis.com/G5vR3cOjh6g2Ed8E/arcgis/rest/services/Parcels_NEW/FeatureServer/0
Pagination: resultOffset + resultRecordCount (max 2000 per page)
"""

import json
import os
import sys
import time
from pathlib import Path

import psycopg2
import requests
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

BASE_URL = (
    "https://services2.arcgis.com/G5vR3cOjh6g2Ed8E/arcgis/rest/services/"
    "Parcels_NEW/FeatureServer/0"
)
DB_URL = os.environ["DATABASE_URL"]
PAGE_SIZE = 2000
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "parcels"

FIELDS_TO_STORE = [
    "OBJECTID", "PIN", "REID", "ZONING", "LAND_CLASS", "ACREAGE",
    "CALCULATED_ACRES", "DEEDED_ACRES", "LOCATION_ADDR", "PROPERTY_OWNER",
    "OWNER_MAIL_1", "OWNER_MAIL_2", "OWNER_MAIL_CITY", "OWNER_MAIL_STATE",
    "OWNER_MAIL_ZIP", "TOTAL_PROP_VALUE", "TOTAL_LAND_VALUE_ASSESSED",
    "TOTAL_BLDG_VALUE_ASSESSED", "HEATED_AREA", "TOTAL_UNITS", "DEED_DATE",
    "Shape__Area", "Shape__Length",
]


def get_total_count() -> int:
    resp = requests.get(
        f"{BASE_URL}/query",
        params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["count"]


def fetch_page_geojson(offset: int) -> dict:
    params = {
        "where": "1=1",
        "outFields": ",".join(FIELDS_TO_STORE),
        "outSR": "4326",
        "f": "geojson",
        "resultOffset": str(offset),
        "resultRecordCount": str(PAGE_SIZE),
    }
    for attempt in range(3):
        try:
            resp = requests.get(f"{BASE_URL}/query", params=params, timeout=120)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < 2:
                print(f"  Retry {attempt + 1} after error: {e}", flush=True)
                time.sleep(2 ** attempt)
            else:
                raise


def insert_features(conn, features: list[dict]):
    """Insert features into PostGIS. Fetch 4326, use ST_Transform for 2264."""
    cur = conn.cursor()
    for feat in features:
        props = feat["properties"]
        oid = props.get("OBJECTID")
        geom_json = json.dumps(feat["geometry"]) if feat["geometry"] else None
        area_sqft = props.get("Shape__Area")

        deed_date = None
        if props.get("DEED_DATE"):
            try:
                deed_date = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.gmtime(props["DEED_DATE"] / 1000),
                )
            except Exception:
                pass

        if geom_json is None:
            continue

        try:
            cur.execute(
                """
                INSERT INTO parcels (
                    objectid, pin, reid, zoning, land_class, acreage,
                    calculated_acres, location_addr, property_owner,
                    owner_mail_1, owner_mail_2, owner_mail_city,
                    owner_mail_state, owner_mail_zip,
                    total_prop_value, total_land_value, total_bldg_value,
                    heated_area, total_units, deed_date,
                    geom, geom_stateplane, area_sqft
                ) VALUES (
                    %(objectid)s, %(pin)s, %(reid)s, %(zoning)s, %(land_class)s, %(acreage)s,
                    %(calculated_acres)s, %(location_addr)s, %(property_owner)s,
                    %(owner_mail_1)s, %(owner_mail_2)s, %(owner_mail_city)s,
                    %(owner_mail_state)s, %(owner_mail_zip)s,
                    %(total_prop_value)s, %(total_land_value)s, %(total_bldg_value)s,
                    %(heated_area)s, %(total_units)s, %(deed_date)s,
                    ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326),
                    ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326), 2264),
                    %(area_sqft)s
                )
                ON CONFLICT (objectid) DO NOTHING
                """,
                {
                    "objectid": oid,
                    "pin": props.get("PIN"),
                    "reid": props.get("REID"),
                    "zoning": props.get("ZONING"),
                    "land_class": props.get("LAND_CLASS"),
                    "acreage": props.get("ACREAGE"),
                    "calculated_acres": props.get("CALCULATED_ACRES"),
                    "location_addr": props.get("LOCATION_ADDR"),
                    "property_owner": props.get("PROPERTY_OWNER"),
                    "owner_mail_1": props.get("OWNER_MAIL_1"),
                    "owner_mail_2": props.get("OWNER_MAIL_2"),
                    "owner_mail_city": props.get("OWNER_MAIL_CITY"),
                    "owner_mail_state": props.get("OWNER_MAIL_STATE"),
                    "owner_mail_zip": props.get("OWNER_MAIL_ZIP"),
                    "total_prop_value": props.get("TOTAL_PROP_VALUE"),
                    "total_land_value": props.get("TOTAL_LAND_VALUE_ASSESSED"),
                    "total_bldg_value": props.get("TOTAL_BLDG_VALUE_ASSESSED"),
                    "heated_area": props.get("HEATED_AREA"),
                    "total_units": props.get("TOTAL_UNITS"),
                    "deed_date": deed_date,
                    "geom": geom_json,
                    "area_sqft": area_sqft,
                },
            )
        except Exception as e:
            conn.rollback()
            print(f"  Skip OBJECTID={oid}: {e}", flush=True)
            continue
    conn.commit()


def run():
    print("Fetching total count...", flush=True)
    total = get_total_count()
    print(f"Total parcels to download: {total:,}", flush=True)

    conn = psycopg2.connect(DB_URL)

    try:
        offsets = list(range(0, total, PAGE_SIZE))
        for page_num, offset in enumerate(offsets):
            print(f"Page {page_num + 1}/{len(offsets)} (offset={offset})...", end=" ", flush=True)

            page = fetch_page_geojson(offset)
            features = page.get("features", [])
            print(f"got {len(features)} features,", end=" ", flush=True)

            if not features:
                print("empty page — stopping.", flush=True)
                break

            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(DATA_DIR / f"page_{page_num}.geojson", "w") as f:
                json.dump(page, f)

            insert_features(conn, features)
            print("inserted.", flush=True)

            time.sleep(0.3)

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM parcels;")
        count = cur.fetchone()[0]
        print(f"\nTotal parcels in database: {count:,}", flush=True)

        cur.execute("SELECT ST_AsText(geom) FROM parcels WHERE geom IS NOT NULL LIMIT 1;")
        sample = cur.fetchone()
        if sample:
            print(f"Sample geometry: {sample[0][:100]}...", flush=True)

    finally:
        conn.close()

    print("Done!", flush=True)


if __name__ == "__main__":
    run()
