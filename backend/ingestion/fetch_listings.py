"""
Download active for-sale listings from Redfin's Stingray API (gis-csv endpoint)
and match them to Durham parcels via PostGIS point-in-polygon.

Usage:
    python -u -m backend.ingestion.fetch_listings
"""

import csv
import io
import re
import sys
import time
from datetime import datetime

import psycopg2
import requests

import os
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.environ["DATABASE_URL"]

GIS_CSV_URL = "https://www.redfin.com/stingray/api/gis-csv"

DURHAM_MARKET = "raleigh"
# Durham city bounding box (SW to NE, closed polygon for Redfin's poly param)
DURHAM_POLY = (
    "-78.9796 36.0884,"
    "-78.7706 36.0884,"
    "-78.7706 35.8739,"
    "-78.9796 35.8739,"
    "-78.9796 36.0884"
)

LISTING_STATUS_ACTIVE = "9"
MAX_PER_REQUEST = 350


def _make_session() -> requests.Session:
    """Create a session with browser-like headers and cookies."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/csv,text/html,application/xhtml+xml,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.redfin.com/city/4626/NC/Durham",
        "Origin": "https://www.redfin.com",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-CH-UA": '"Chromium";v="131", "Not_A Brand";v="24"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
    })
    # Warm up the session to get cookies
    try:
        s.get("https://www.redfin.com/", timeout=15)
        time.sleep(0.5)
    except Exception:
        pass
    return s


_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _make_session()
    return _session


def fetch_csv_page(
    min_price: int | None = None,
    max_price: int | None = None,
) -> list[dict]:
    """Fetch a single gis-csv page from Redfin using polygon search."""
    params = {
        "al": "1",
        "market": DURHAM_MARKET,
        "num_homes": str(MAX_PER_REQUEST),
        "status": LISTING_STATUS_ACTIVE,
        "uipt": "1,2,3,4,5,6,7,8",
        "v": "8",
        "poly": DURHAM_POLY,
    }
    if min_price is not None:
        params["min_price"] = str(min_price)
    if max_price is not None:
        params["max_price"] = str(max_price)

    session = _get_session()
    for attempt in range(3):
        try:
            resp = session.get(GIS_CSV_URL, params=params, timeout=30)
            resp.raise_for_status()
            break
        except requests.exceptions.HTTPError:
            if resp.status_code == 403 and attempt < 2:
                print(f"  Got 403, refreshing session (attempt {attempt + 1})...")
                global _session
                _session = _make_session()
                session = _session
                time.sleep(3)
            elif attempt < 2:
                wait = 2 ** (attempt + 1)
                print(f"  Retry {attempt + 1}, waiting {wait}s...")
                time.sleep(wait)
            else:
                raise

    reader = csv.DictReader(io.StringIO(resp.text))
    rows = [
        r for r in reader
        if r.get("ADDRESS") and r.get("ADDRESS").strip()
        and r.get("STATUS", "").strip() == "Active"
    ]
    return rows


def fetch_all_listings(
    min_price: int | None = None,
    max_price: int | None = None,
    depth: int = 0,
) -> list[dict]:
    """
    Recursively fetch all listings. If a single request hits the 350-row cap,
    split the price range in half and recurse.
    """
    label = f"${min_price or 0:,}-${max_price or '∞':,}" if max_price else f"${min_price or 0:,}+"
    print(f"{'  ' * depth}Fetching {label}...", end=" ", flush=True)

    rows = fetch_csv_page(min_price, max_price)
    print(f"{len(rows)} listings", flush=True)

    if len(rows) < MAX_PER_REQUEST or depth > 8:
        time.sleep(1.5)
        return rows

    lo = min_price or 0
    hi = max_price or 10_000_000
    mid = (lo + hi) // 2

    if mid <= lo or mid >= hi:
        time.sleep(1.5)
        return rows

    time.sleep(1.5)
    left = fetch_all_listings(lo, mid, depth + 1)
    right = fetch_all_listings(mid, hi, depth + 1)

    seen_urls = set()
    combined = []
    for r in left + right:
        url = r.get("URL (SEE https://www.redfin.com/buy-a-home/comparative-market-analysis FOR INFO ON PRICING)", "")
        if url not in seen_urls:
            seen_urls.add(url)
            combined.append(r)
    return combined


def safe_int(val: str | None) -> int | None:
    if not val or val.strip() == "":
        return None
    try:
        return int(float(val.replace(",", "")))
    except (ValueError, TypeError):
        return None


def safe_float(val: str | None) -> float | None:
    if not val or val.strip() == "":
        return None
    try:
        return float(val.replace(",", ""))
    except (ValueError, TypeError):
        return None


def create_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS redfin_listings (
            id SERIAL PRIMARY KEY,
            parcel_id INTEGER REFERENCES parcels(id),
            redfin_url TEXT,
            mls_number VARCHAR(50),
            list_price DOUBLE PRECISION,
            property_type VARCHAR(50),
            address VARCHAR(200),
            city VARCHAR(50),
            state VARCHAR(10),
            zip_code VARCHAR(10),
            beds INTEGER,
            baths DOUBLE PRECISION,
            sqft INTEGER,
            lot_size_sqft INTEGER,
            year_built INTEGER,
            days_on_market INTEGER,
            hoa_month DOUBLE PRECISION,
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            status VARCHAR(50),
            photo_url TEXT,
            fetched_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_listings_parcel ON redfin_listings (parcel_id);
    """)
    cur.execute("""
        DO $$ BEGIN
            ALTER TABLE redfin_listings ADD COLUMN photo_url TEXT;
        EXCEPTION WHEN duplicate_column THEN NULL;
        END $$;
    """)
    conn.commit()


def load_listings(conn, rows: list[dict]) -> int:
    """Clear old listings and insert new ones. Returns inserted count."""
    cur = conn.cursor()
    cur.execute("DELETE FROM redfin_listings;")

    url_col = None
    for key in rows[0].keys() if rows else []:
        if "URL" in key.upper():
            url_col = key
            break

    inserted = 0
    for r in rows:
        lat = safe_float(r.get("LATITUDE"))
        lng = safe_float(r.get("LONGITUDE"))
        url = r.get(url_col, "") if url_col else ""

        cur.execute(
            """
            INSERT INTO redfin_listings (
                redfin_url, mls_number, list_price, property_type,
                address, city, state, zip_code,
                beds, baths, sqft, lot_size_sqft, year_built,
                days_on_market, hoa_month, latitude, longitude, status
            ) VALUES (
                %(url)s, %(mls)s, %(price)s, %(ptype)s,
                %(addr)s, %(city)s, %(state)s, %(zip)s,
                %(beds)s, %(baths)s, %(sqft)s, %(lot)s, %(year)s,
                %(dom)s, %(hoa)s, %(lat)s, %(lng)s, %(status)s
            )
            """,
            {
                "url": url,
                "mls": r.get("MLS#", ""),
                "price": safe_float(r.get("PRICE")),
                "ptype": r.get("PROPERTY TYPE", ""),
                "addr": r.get("ADDRESS", ""),
                "city": r.get("CITY", ""),
                "state": r.get("STATE OR PROVINCE", ""),
                "zip": r.get("ZIP OR POSTAL CODE", ""),
                "beds": safe_int(r.get("BEDS")),
                "baths": safe_float(r.get("BATHS")),
                "sqft": safe_int(r.get("SQUARE FEET")),
                "lot": safe_int(r.get("LOT SIZE")),
                "year": safe_int(r.get("YEAR BUILT")),
                "dom": safe_int(r.get("DAYS ON MARKET")),
                "hoa": safe_float(r.get("HOA/MONTH")),
                "lat": lat,
                "lng": lng,
                "status": r.get("STATUS", "Active"),
            },
        )
        inserted += 1

    conn.commit()
    return inserted


def match_to_parcels(conn) -> int:
    """
    Spatial join: match each listing's lat/lng to the parcel polygon that
    contains it. Uses ST_Contains on the 4326 geometries.
    """
    cur = conn.cursor()
    cur.execute("""
        UPDATE redfin_listings rl
        SET parcel_id = p.id
        FROM parcels p
        WHERE rl.latitude IS NOT NULL
          AND rl.longitude IS NOT NULL
          AND ST_Contains(
              p.geom,
              ST_SetSRID(ST_MakePoint(rl.longitude, rl.latitude), 4326)
          );
    """)
    matched = cur.rowcount
    conn.commit()
    return matched


def scrape_photo_urls(conn) -> int:
    """Fetch og:image from Redfin listing pages and store as photo_url."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, redfin_url FROM redfin_listings
        WHERE redfin_url IS NOT NULL AND redfin_url != ''
          AND (photo_url IS NULL OR photo_url = '')
    """)
    rows = cur.fetchall()
    if not rows:
        return 0

    session = _get_session()
    updated = 0
    for listing_id, url in rows:
        try:
            resp = session.get(url, timeout=15)
            match = re.search(
                r'<meta\s+property="og:image"\s+content="([^"]+)"',
                resp.text,
                re.IGNORECASE,
            )
            if not match:
                match = re.search(
                    r'content="([^"]+)"\s+property="og:image"',
                    resp.text,
                    re.IGNORECASE,
                )
            if match:
                photo_url = match.group(1)
                cur.execute(
                    "UPDATE redfin_listings SET photo_url = %s WHERE id = %s",
                    (photo_url, listing_id),
                )
                updated += 1
            time.sleep(1)
        except Exception as e:
            print(f"  Photo scrape failed for listing {listing_id}: {e}")
            continue

    conn.commit()
    return updated


def run():
    print("=" * 60)
    print("Redfin Listings Downloader — Durham, NC")
    print(f"  Market: {DURHAM_MARKET}, method: polygon search")
    print("=" * 60)

    print(f"\n1. Establishing session with Redfin...")
    _get_session()
    print("   Session ready.")

    print(f"\n2. Downloading active listings...")
    rows = fetch_all_listings()
    print(f"\n   Total unique listings: {len(rows)}")

    if not rows:
        print("No listings found. Exiting.")
        return

    print(f"\n3. Loading into database...")
    conn = psycopg2.connect(DB_URL)
    try:
        create_table(conn)
        inserted = load_listings(conn, rows)
        print(f"   Inserted {inserted} listings")

        print(f"\n4. Matching listings to parcels (spatial join via ST_Contains)...")
        matched = match_to_parcels(conn)
        print(f"   Matched {matched}/{inserted} listings to parcels")

        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(DISTINCT rl.parcel_id)
            FROM redfin_listings rl
            JOIN subdivision_analysis sa ON sa.parcel_id = rl.parcel_id
            WHERE sa.is_subdividable = true
              AND rl.parcel_id IS NOT NULL;
        """)
        subdiv_for_sale = cur.fetchone()[0]
        print(f"   Of those, {subdiv_for_sale} are subdividable parcels currently for sale")

        print(f"\n5. Scraping listing photos (og:image)...")
        scraped = scrape_photo_urls(conn)
        print(f"   Scraped {scraped}/{inserted} listing photos")

    finally:
        conn.close()

    print(f"\nDone! Run the API server to see 'For Sale' badges on the map.")


if __name__ == "__main__":
    run()
