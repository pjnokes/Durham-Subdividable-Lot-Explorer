"""
Download zoning district polygons from Durham's MapServer into PostGIS.

Source: https://webgis2.durhamnc.gov/server/rest/services/PublicServices/Planning/MapServer/12
"""

import json
import os
import time
from pathlib import Path

import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = (
    "https://webgis2.durhamnc.gov/server/rest/services/"
    "PublicServices/Planning/MapServer/12"
)
DB_URL = os.environ["DATABASE_URL"]
PAGE_SIZE = 1000
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "zoning"


def get_total_count() -> int:
    resp = requests.get(
        f"{BASE_URL}/query",
        params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["count"]


def fetch_page(offset: int) -> dict:
    params = {
        "where": "1=1",
        "outFields": "*",
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
                print(f"  Retry {attempt + 1}: {e}", flush=True)
                time.sleep(2 ** attempt)
            else:
                raise


def insert_features(conn, features: list[dict]):
    cur = conn.cursor()
    for feat in features:
        props = feat["properties"]
        geom_json = json.dumps(feat["geometry"]) if feat["geometry"] else None
        if geom_json is None:
            continue

        zone_code = props.get("ZONE_CODE") or props.get("ZoneCode") or props.get("ZONING") or ""
        zone_name = props.get("ZONE_NAME") or props.get("ZoneName") or props.get("ZONE_DESC") or ""

        if not zone_code:
            for key in props:
                if "zone" in key.lower() or "zoning" in key.lower():
                    zone_code = props[key]
                    break

        try:
            cur.execute(
                """
                INSERT INTO zoning_districts (zone_code, zone_name, geom, geom_stateplane)
                VALUES (
                    %(zone_code)s,
                    %(zone_name)s,
                    ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326)),
                    ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326), 2264))
                )
                """,
                {"zone_code": zone_code, "zone_name": zone_name, "geom": geom_json},
            )
        except Exception as e:
            conn.rollback()
            print(f"  Skip zone {zone_code}: {e}", flush=True)
            continue

    conn.commit()


def run():
    print("Fetching zoning count...", flush=True)
    total = get_total_count()
    print(f"Total zoning districts to download: {total:,}", flush=True)

    conn = psycopg2.connect(DB_URL)

    try:
        # Clear existing data
        cur = conn.cursor()
        cur.execute("TRUNCATE zoning_districts;")
        conn.commit()

        offsets = list(range(0, total, PAGE_SIZE))
        for page_num, offset in enumerate(offsets):
            print(f"Page {page_num + 1}/{len(offsets)} (offset={offset})...", end=" ", flush=True)

            page = fetch_page(offset)
            features = page.get("features", [])
            print(f"got {len(features)} features,", end=" ", flush=True)

            if not features:
                print("empty — stopping.", flush=True)
                break

            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(DATA_DIR / f"zoning_page_{page_num}.geojson", "w") as f:
                json.dump(page, f)

            insert_features(conn, features)
            print("inserted.", flush=True)

            time.sleep(0.3)

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM zoning_districts;")
        count = cur.fetchone()[0]
        print(f"\nTotal zoning districts in database: {count:,}", flush=True)

        cur.execute("SELECT zone_code, COUNT(*) FROM zoning_districts GROUP BY zone_code ORDER BY COUNT(*) DESC LIMIT 10;")
        print("Top 10 zone codes:", flush=True)
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1]}", flush=True)

        # Spatial join verification
        print("\nVerifying spatial join (parcel zoning vs spatial zoning)...", flush=True)
        cur.execute("""
            SELECT p.pin, p.zoning as parcel_zoning, z.zone_code as spatial_zoning
            FROM parcels p
            JOIN zoning_districts z ON ST_Intersects(p.geom, z.geom)
            WHERE p.zoning != z.zone_code
            LIMIT 10;
        """)
        mismatches = cur.fetchall()
        print(f"Mismatches found (sample): {len(mismatches)}", flush=True)
        for row in mismatches:
            print(f"  PIN={row[0]}: parcel={row[1]}, spatial={row[2]}", flush=True)

    finally:
        conn.close()

    print("Done!", flush=True)


if __name__ == "__main__":
    run()
