"""
Download street centerlines from Durham County's Roads_Clip ArcGIS layer.

Stores them in PostGIS with both WGS84 (4326) and NC State Plane (2264)
geometries for fast spatial queries against parcels.
"""

from __future__ import annotations

import json
import os
import time

import psycopg2
import requests
from dotenv import load_dotenv
from shapely.geometry import LineString, mapping

load_dotenv()
DB_URL = os.environ["DATABASE_URL"]

BASE_URL = (
    "https://services2.arcgis.com/G5vR3cOjh6g2Ed8E/arcgis/rest/services"
    "/Roads_Clip/FeatureServer/5/query"
)

PAGE_SIZE = 1000


def _fetch_page(offset: int) -> list[dict]:
    """Fetch one page of road features."""
    params = {
        "where": "1=1",
        "outFields": "OBJECTID,FACILITYID,FTRCODE,SURFACE,LANES,STRNAME",
        "outSR": "4326",
        "f": "json",
        "resultRecordCount": PAGE_SIZE,
        "resultOffset": offset,
    }
    resp = requests.get(BASE_URL, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data.get("features", [])


def run():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM street_centerlines")
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"Already have {existing:,} street centerlines, skipping download.")
        conn.close()
        return

    print("Downloading Durham street centerlines...", flush=True)
    total_inserted = 0
    offset = 0

    while True:
        features = _fetch_page(offset)
        if not features:
            break

        for feat in features:
            attrs = feat.get("attributes", {})
            geom = feat.get("geometry", {})
            paths = geom.get("paths", [])

            if not paths:
                continue

            for path in paths:
                if len(path) < 2:
                    continue

                coords = [(p[0], p[1]) for p in path]
                line = LineString(coords)
                if line.is_empty:
                    continue

                geojson = json.dumps(mapping(line))

                try:
                    cur.execute(
                        """
                        INSERT INTO street_centerlines
                            (object_id, road_name, ftr_code, surface, lanes, geom, geom_stateplane)
                        VALUES (
                            %s, %s, %s, %s, %s,
                            ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                            ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 2264)
                        )
                        """,
                        (
                            attrs.get("OBJECTID"),
                            attrs.get("STRNAME"),
                            attrs.get("FTRCODE"),
                            attrs.get("SURFACE"),
                            attrs.get("LANES"),
                            geojson,
                            geojson,
                        ),
                    )
                    total_inserted += 1
                except Exception as e:
                    conn.rollback()
                    continue

        conn.commit()
        print(
            f"  offset={offset}, batch={len(features)}, total={total_inserted:,}",
            flush=True,
        )

        if len(features) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(0.3)

    conn.commit()
    print(f"\nInserted {total_inserted:,} street centerlines", flush=True)

    # Build a buffered street polygon for fast adjacency checks
    print("Building road-buffer union (50ft each side)...", flush=True)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS street_buffers AS
        SELECT
            id,
            ftr_code,
            ST_Buffer(geom_stateplane, 50) AS geom_buffered
        FROM street_centerlines
        WHERE ftr_code NOT IN ('RAMP', 'INTERSTATE')
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_street_buf ON street_buffers USING GIST(geom_buffered)")
    conn.commit()
    print("Done!", flush=True)

    conn.close()


if __name__ == "__main__":
    run()
