"""
Download utility infrastructure from Durham's public ArcGIS REST services
and load into PostGIS.

Publicly accessible layers:
  - Fire hydrants (water system indicator)
  - Stormwater pipes
  - Stormwater structures (catch basins, manholes)

Sewer gravity mains and water mains are behind CityworksServices tokens.
If you have credentials, add them to LAYERS below.

Usage:
    python -u -m backend.ingestion.fetch_utilities
    python -u -m backend.ingestion.fetch_utilities --layer fire_hydrant
"""

import argparse
import json
import os
import time

import psycopg2
import requests

from dotenv import load_dotenv

load_dotenv()
DB_URL = os.environ["DATABASE_URL"]

LAYERS = {
    "fire_hydrant": {
        "url": "https://webgis.durhamnc.gov/server/rest/services/PublicWorksServices/FireFlow2/MapServer/2",
        "out_fields": "OBJECTID,FACILITYID,OWNER,DIAMETER,TYPE,LIFECYCLESTATUS",
        "geometry_type": "point",
    },
    "stormwater_pipe": {
        "url": "https://webgis.durhamnc.gov/server/rest/services/PublicWorksServices/StormwaterUtilitiesMapService/MapServer/6",
        "out_fields": "OBJECTID,FACILITYID,OWNER,DIAMETER,MATERIAL,TYPE",
        "geometry_type": "line",
    },
    "stormwater_structure": {
        "url": "https://webgis.durhamnc.gov/server/rest/services/PublicWorksServices/StormwaterUtilitiesMapService/MapServer/2",
        "out_fields": "OBJECTID,FACILITYID,OWNER,TYPE,MATERIAL",
        "geometry_type": "point",
    },
}

# Durham county bounding box (EPSG:4326)
DURHAM_BBOX = {
    "xmin": -79.01,
    "ymin": 35.85,
    "xmax": -78.73,
    "ymax": 36.14,
}

MAX_RECORD_COUNT = 2000


def query_layer(url: str, out_fields: str, offset: int = 0) -> dict | None:
    params = {
        "where": "1=1",
        "geometry": f"{DURHAM_BBOX['xmin']},{DURHAM_BBOX['ymin']},{DURHAM_BBOX['xmax']},{DURHAM_BBOX['ymax']}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "outFields": out_fields,
        "f": "geojson",
        "resultRecordCount": str(MAX_RECORD_COUNT),
        "resultOffset": str(offset),
    }
    try:
        resp = requests.get(f"{url}/query", params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if data.get("type") == "FeatureCollection":
            return data
        if "error" in data:
            print(f"    ArcGIS error: {data['error'].get('message', data['error'])}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"    Request failed: {e}")
        return None


def fetch_all_features(url: str, out_fields: str) -> list[dict]:
    all_features = []
    offset = 0
    while True:
        print(f"    Fetching offset {offset}...", end=" ", flush=True)
        data = query_layer(url, out_fields, offset)
        if data is None:
            print("failed")
            break
        features = data.get("features", [])
        print(f"{len(features)} features")
        if not features:
            break
        all_features.extend(features)
        if len(features) < MAX_RECORD_COUNT:
            break
        offset += len(features)
        time.sleep(0.5)
    return all_features


def create_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS utility_lines (
            id SERIAL PRIMARY KEY,
            layer_type VARCHAR(30) NOT NULL,
            facility_id VARCHAR(50),
            owner VARCHAR(50),
            diameter DOUBLE PRECISION,
            material VARCHAR(50),
            geom GEOMETRY(Geometry, 4326),
            fetched_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_utility_geom ON utility_lines USING GIST (geom);
        CREATE INDEX IF NOT EXISTS idx_utility_type ON utility_lines (layer_type);
    """)
    conn.commit()


def load_features(conn, layer_type: str, features: list[dict]) -> int:
    cur = conn.cursor()
    cur.execute("DELETE FROM utility_lines WHERE layer_type = %s", (layer_type,))
    deleted = cur.rowcount
    if deleted:
        print(f"    Deleted {deleted} old {layer_type} rows")

    inserted = 0
    for f in features:
        geom = f.get("geometry")
        props = f.get("properties", {})
        if not geom:
            continue

        geom_json = json.dumps(geom)

        cur.execute(
            """
            INSERT INTO utility_lines (layer_type, facility_id, owner, diameter, material, geom)
            VALUES (
                %s, %s, %s, %s, %s,
                ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)
            )
            """,
            (
                layer_type,
                props.get("FACILITYID"),
                props.get("OWNER"),
                props.get("DIAMETER"),
                props.get("MATERIAL"),
                geom_json,
            ),
        )
        inserted += 1

    conn.commit()
    return inserted


def run(only_layer: str | None = None):
    layers_to_fetch = {only_layer: LAYERS[only_layer]} if only_layer else LAYERS

    print("=" * 60)
    print("Durham Utility Infrastructure Downloader")
    print(f"  Layers: {', '.join(layers_to_fetch.keys())}")
    print("=" * 60)

    conn = psycopg2.connect(DB_URL)
    try:
        create_table(conn)

        for layer_type, config in layers_to_fetch.items():
            print(f"\n--- {layer_type} ---")
            print(f"  URL: {config['url']}")

            features = fetch_all_features(config["url"], config["out_fields"])
            if not features:
                print(f"  No features returned for {layer_type}")
                continue

            print(f"  Total features: {len(features)}")
            inserted = load_features(conn, layer_type, features)
            print(f"  Inserted: {inserted}")

        # Print summary
        cur = conn.cursor()
        cur.execute("SELECT layer_type, COUNT(*) FROM utility_lines GROUP BY layer_type ORDER BY layer_type")
        print("\n--- Summary ---")
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1]:,} features")

    finally:
        conn.close()

    print("\nDone!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Durham utility lines into PostGIS")
    parser.add_argument(
        "--layer",
        choices=list(LAYERS.keys()),
        default=None,
        help="Fetch only a specific layer (default: all)",
    )
    args = parser.parse_args()
    run(only_layer=args.layer)
