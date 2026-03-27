"""
Download building footprints for Durham County.

Uses Microsoft Building Footprints global dataset, finding quadkeys
that cover the Durham bounding box.

Quadkey reference: https://learn.microsoft.com/en-us/bingmaps/articles/bing-maps-tile-system
"""

import csv
import gzip
import io
import json
import math
import os
import time
from pathlib import Path

import psycopg2
import requests
from dotenv import load_dotenv
from shapely.geometry import shape, box

load_dotenv()
DB_URL = os.environ["DATABASE_URL"]
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "buildings"

# Durham County approximate bounding box (WGS84)
DURHAM_BBOX = box(-79.05, 35.85, -78.68, 36.15)
DURHAM_LAT_RANGE = (35.85, 36.15)
DURHAM_LON_RANGE = (-79.05, -78.68)

DATASET_LINKS_URL = "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"


def lat_lon_to_quadkey(lat: float, lon: float, level: int) -> str:
    """Convert lat/lon to a Bing Maps quadkey at the given zoom level."""
    sin_lat = math.sin(lat * math.pi / 180)
    x = ((lon + 180) / 360) * (2 ** level)
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * (2 ** level)
    tile_x = int(min(max(x, 0), 2 ** level - 1))
    tile_y = int(min(max(y, 0), 2 ** level - 1))

    quadkey = ""
    for i in range(level, 0, -1):
        digit = 0
        mask = 1 << (i - 1)
        if tile_x & mask:
            digit += 1
        if tile_y & mask:
            digit += 2
        quadkey += str(digit)
    return quadkey


def get_durham_quadkeys(level: int = 9) -> set[str]:
    """Get quadkeys covering Durham at the specified zoom level."""
    quadkeys = set()
    lat_step = (DURHAM_LAT_RANGE[1] - DURHAM_LAT_RANGE[0]) / 10
    lon_step = (DURHAM_LON_RANGE[1] - DURHAM_LON_RANGE[0]) / 10

    for i in range(11):
        for j in range(11):
            lat = DURHAM_LAT_RANGE[0] + i * lat_step
            lon = DURHAM_LON_RANGE[0] + j * lon_step
            qk = lat_lon_to_quadkey(lat, lon, level)
            quadkeys.add(qk)

    return quadkeys


def get_matching_links() -> list[str]:
    """Find download links for quadkeys covering Durham."""
    print("Fetching dataset links catalog...", flush=True)
    resp = requests.get(DATASET_LINKS_URL, timeout=60)
    resp.raise_for_status()

    # Get quadkey prefixes at a lower zoom level to match more tiles
    durham_qk_prefixes = set()
    for level in [6, 7, 8, 9]:
        for qk in get_durham_quadkeys(level):
            durham_qk_prefixes.add(qk)

    links = []
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        if row.get("Location") != "UnitedStates":
            continue
        quadkey = row.get("QuadKey", "")
        for prefix in durham_qk_prefixes:
            if quadkey.startswith(prefix) or prefix.startswith(quadkey):
                links.append((quadkey, row["Url"]))
                break

    print(f"Found {len(links)} tiles covering Durham area", flush=True)
    return links


def download_and_parse_tile(url: str) -> list[dict]:
    """Download a compressed CSV tile and parse buildings in Durham bbox."""
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()

    decompressed = gzip.decompress(resp.content).decode("utf-8")
    buildings = []

    for line in decompressed.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            # Format: latitude,longitude,height,confidence,geometry_json
            # or just GeoJSON lines
            if line.startswith("{"):
                feat = json.loads(line)
            else:
                # CSV format: geometry is the last column in WKT or JSON
                parts = line.split("\t")
                if len(parts) >= 2:
                    geom_str = parts[-1]
                    if geom_str.startswith("{"):
                        feat = {"type": "Feature", "geometry": json.loads(geom_str), "properties": {}}
                    else:
                        continue
                else:
                    continue

            geom = shape(feat.get("geometry", {}))
            centroid = geom.centroid
            if (DURHAM_LAT_RANGE[0] <= centroid.y <= DURHAM_LAT_RANGE[1] and
                    DURHAM_LON_RANGE[0] <= centroid.x <= DURHAM_LON_RANGE[1]):
                buildings.append(feat)
        except Exception:
            continue

    return buildings


def insert_buildings(conn, buildings: list[dict]) -> int:
    """Insert building footprints into PostGIS."""
    cur = conn.cursor()
    inserted = 0
    for feat in buildings:
        geom_json = json.dumps(feat["geometry"])
        try:
            cur.execute(
                """
                INSERT INTO building_footprints (geom, geom_stateplane, area_sqft)
                VALUES (
                    ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                    ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 2264),
                    ST_Area(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), 2264))
                )
                """,
                (geom_json, geom_json, geom_json),
            )
            inserted += 1
        except Exception as e:
            conn.rollback()
            continue

    conn.commit()
    return inserted


def associate_parcels(conn):
    """Associate building footprints with parcels via spatial join."""
    print("\nAssociating buildings with parcels (this may take a while)...", flush=True)
    cur = conn.cursor()
    cur.execute("""
        UPDATE building_footprints bf
        SET parcel_id = sub.pid
        FROM (
            SELECT bf2.id AS bfid, p.id AS pid
            FROM building_footprints bf2
            JOIN parcels p ON ST_Within(ST_Centroid(bf2.geom), p.geom)
            WHERE bf2.parcel_id IS NULL
        ) sub
        WHERE bf.id = sub.bfid;
    """)
    conn.commit()
    updated = cur.rowcount
    print(f"  Associated {updated:,} buildings with parcels", flush=True)


def run():
    conn = psycopg2.connect(DB_URL)

    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM building_footprints;")
        existing = cur.fetchone()[0]
        if existing > 0:
            print(f"Already have {existing:,} building footprints, skipping download.", flush=True)
        else:
            links = get_matching_links()

            total_inserted = 0
            for i, (quadkey, url) in enumerate(links):
                print(f"  Tile {i + 1}/{len(links)} (qk={quadkey})...", end=" ", flush=True)
                try:
                    buildings = download_and_parse_tile(url)
                    if buildings:
                        count = insert_buildings(conn, buildings)
                        total_inserted += count
                        print(f"{count:,} buildings (total: {total_inserted:,})", flush=True)
                    else:
                        print("0 in Durham", flush=True)
                except Exception as e:
                    print(f"Error: {e}", flush=True)
                    continue

                time.sleep(0.2)

            # Cache results
            DATA_DIR.mkdir(parents=True, exist_ok=True)

        cur.execute("SELECT COUNT(*) FROM building_footprints;")
        total = cur.fetchone()[0]
        print(f"\nTotal building footprints: {total:,}", flush=True)

        if total > 0:
            associate_parcels(conn)

            cur.execute("SELECT COUNT(*) FROM building_footprints WHERE parcel_id IS NOT NULL;")
            assoc = cur.fetchone()[0]
            print(f"Buildings with parcel association: {assoc:,} / {total:,}", flush=True)

    finally:
        conn.close()

    print("Done!", flush=True)


if __name__ == "__main__":
    run()
