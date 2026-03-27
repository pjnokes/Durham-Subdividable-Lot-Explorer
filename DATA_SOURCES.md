# Data Sources & Refresh Schedule

All external datasets used by the Durham Subdividable Lots Finder, their sources, update cadences, and how they flow through the system.

---

## Dataset Inventory

### 1. Tax Parcels (primary lot layer)

| | |
|---|---|
| **Source** | Durham County ArcGIS FeatureServer |
| **URL** | `https://services2.arcgis.com/G5vR3cOjh6g2Ed8E/arcgis/rest/services/Parcels_NEW/FeatureServer/0` |
| **Table** | `parcels` |
| **Records** | ~100,000+ polygons (all Durham parcels) |
| **Ingestion script** | `backend/ingestion/fetch_parcels.py` |
| **Load strategy** | Paginated GeoJSON (2,000/page), `ON CONFLICT (objectid) DO NOTHING` — additive only |
| **Source update cadence** | Weekly to quarterly (county GIS maintenance; bulk updates after reappraisals) |
| **Our refresh schedule** | **Monthly** |
| **Run command** | `py -3.11 -u -m backend.ingestion.fetch_parcels` |
| **Notes** | Core dataset — zoning, geometry, owner info, land class. Drives all downstream analysis. After refresh, re-run analysis batch. |

### 2. Zoning Districts

| | |
|---|---|
| **Source** | Durham Planning MapServer |
| **URL** | `https://webgis2.durhamnc.gov/server/rest/services/PublicServices/Planning/MapServer/12` |
| **Table** | `zoning_districts` |
| **Records** | ~2,500 polygons |
| **Ingestion script** | `backend/ingestion/fetch_zoning.py` |
| **Load strategy** | `TRUNCATE` + full reload (paginated GeoJSON, 1,000/page) |
| **Source update cadence** | Infrequent bulk updates; small ongoing changes with rezonings |
| **Our refresh schedule** | **Monthly** |
| **Run command** | `py -3.11 -u -m backend.ingestion.fetch_zoning` |
| **Notes** | Zoning determines which UDO rules apply. Changes are rare but impactful. |

### 3. Building Footprints

| | |
|---|---|
| **Source** | Microsoft Global Building Footprints |
| **Catalog** | `https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv` |
| **Table** | `building_footprints` |
| **Records** | ~150,000+ polygons (Durham County extent) |
| **Ingestion script** | `backend/ingestion/fetch_buildings.py` |
| **Load strategy** | Download quadkey tiles from catalog CSV, filter to Durham bbox, bulk insert. **Skips entirely if table has rows** — must `TRUNCATE` to force re-download. |
| **Source update cadence** | Rare — Microsoft releases dataset updates roughly annually |
| **Our refresh schedule** | **Manual / yearly** (check for new Microsoft release) |
| **Run command** | `py -3.11 -u -m backend.ingestion.fetch_buildings` |
| **Notes** | Used to detect existing structures on parcels. Supplemented by synthetic footprints (see below). |

### 4. Synthetic Building Footprints

| | |
|---|---|
| **Source** | Derived internally from parcel attributes (`heated_area`) + street detection |
| **Table** | `building_footprints` (with `source = 'synthetic'`) |
| **Ingestion script** | `backend/ingestion/generate_synthetic_footprints.py` |
| **Load strategy** | Generates footprints for parcels that have `heated_area` but no Microsoft footprint |
| **Source update cadence** | N/A — derived from parcel data |
| **Our refresh schedule** | **After parcel refresh** (when parcel attributes change) |
| **Run command** | `py -3.11 -u -m backend.ingestion.generate_synthetic_footprints` |

### 5. Street Centerlines & Buffers

| | |
|---|---|
| **Source** | Durham County ArcGIS FeatureServer |
| **URL** | `https://services2.arcgis.com/G5vR3cOjh6g2Ed8E/arcgis/rest/services/Roads_Clip/FeatureServer/5` |
| **Tables** | `street_centerlines`, `street_buffers` (50ft buffer union, derived) |
| **Ingestion script** | `backend/ingestion/fetch_streets.py` |
| **Load strategy** | Paginated Esri JSON (1,000/page). **Skips if table has rows** — must truncate to force re-download. Builds `street_buffers` as a derived table after load. |
| **Source update cadence** | Ongoing through road construction/maintenance; not daily at city scale |
| **Our refresh schedule** | **Quarterly** |
| **Run command** | `py -3.11 -u -m backend.ingestion.fetch_streets` |
| **Notes** | Used for street frontage detection and flag lot access validation. |

### 6. Utility Infrastructure

Stored in a single `utility_lines` table with `layer_type` discriminator.

| Layer | Source URL | `layer_type` |
|-------|-----------|--------------|
| Fire hydrants | `https://webgis.durhamnc.gov/.../FireFlow2/MapServer/2` | `fire_hydrant` |
| Stormwater pipes | `https://webgis.durhamnc.gov/.../StormwaterUtilitiesMapService/MapServer/6` | `stormwater_pipe` |
| Stormwater structures | `https://webgis.durhamnc.gov/.../StormwaterUtilitiesMapService/MapServer/2` | `stormwater_structure` |

| | |
|---|---|
| **Table** | `utility_lines` |
| **Ingestion script** | `backend/ingestion/fetch_utilities.py` |
| **Load strategy** | `DELETE FROM utility_lines WHERE layer_type = X` then insert per layer |
| **Source update cadence** | Ongoing GIS edits; weekly-to-monthly changes typical |
| **Our refresh schedule** | **Monthly** |
| **Run command** | `py -3.11 -u -m backend.ingestion.fetch_utilities` (all layers) or `--layer fire_hydrant` |
| **Notes** | Sewer/water mains are behind CityworksServices auth — not currently fetched. |

### 7. Redfin For-Sale Listings

| | |
|---|---|
| **Source** | Redfin Stingray API (gis-csv endpoint) |
| **URL** | `https://www.redfin.com/stingray/api/gis-csv` |
| **Table** | `redfin_listings` |
| **Records** | ~200-600 active listings (varies) |
| **Ingestion script** | `backend/ingestion/fetch_listings.py` |
| **Load strategy** | `DELETE FROM redfin_listings` then full reload. Matches to parcels via PostGIS `ST_Contains`. Scrapes listing photo URLs. |
| **Source update cadence** | Listings change throughout the day |
| **Our refresh schedule** | **Daily** (automated via `listings-cron` Docker service) |
| **Run command** | `py -3.11 -u -m backend.ingestion.fetch_listings` |
| **Notes** | Only automated dataset. Runs as a `while true; sleep 86400` loop in Docker. |

### 8. UDO Dimensional Standards (rules engine)

| | |
|---|---|
| **Source** | Hand-verified from [Durham UDO](https://udo.durhamnc.gov/) |
| **File** | `backend/udo/udo_rules.json` |
| **Load strategy** | Read from disk at runtime — no database table |
| **Source update cadence** | Episodic — UDO amendments happen roughly annually |
| **Our refresh schedule** | **Manual** — update JSON when ordinance changes are adopted |
| **Notes** | UDO accuracy is paramount. Always verify against the official UDO site before changing. |

---

## Refresh Schedule Summary

| Dataset | Frequency | Automated? | Triggers re-analysis? |
|---------|-----------|------------|-----------------------|
| Redfin listings | **Daily** | Yes (Docker) | No |
| Tax parcels | **Monthly** | Yes (cron) | Yes |
| Zoning districts | **Monthly** | Yes (cron) | Yes |
| Utility layers | **Monthly** | Yes (cron) | No |
| Street centerlines | **Quarterly** | Manual | Yes |
| Building footprints | **Yearly / manual** | Manual | Yes |
| Synthetic footprints | After parcel refresh | Manual | Yes |
| UDO rules JSON | On amendment | Manual | Yes |

---

## Cron Architecture

### Docker Services

The `docker-compose.yml` defines two cron-related services:

1. **`listings-cron`** — Refreshes Redfin listings every 24 hours
2. **`data-cron`** — Refreshes parcels, zoning, and utilities on the 1st of each month

Both use a `while true` + `sleep` loop pattern (not system cron) for simplicity in Docker.

### Cron Scripts

| Script | Schedule | What it does |
|--------|----------|-------------|
| `scripts/cron_listings.sh` | Every 24h | Full Redfin listing refresh |
| `scripts/cron_data.sh` | 1st of month | Parcels + zoning + utilities refresh, then re-run analysis |

### Manual Refresh (ad hoc)

For one-off refreshes outside the schedule:

```bash
# Individual datasets
py -3.11 -u -m backend.ingestion.fetch_parcels
py -3.11 -u -m backend.ingestion.fetch_zoning
py -3.11 -u -m backend.ingestion.fetch_streets
py -3.11 -u -m backend.ingestion.fetch_buildings
py -3.11 -u -m backend.ingestion.fetch_utilities
py -3.11 -u -m backend.ingestion.fetch_listings
py -3.11 -u -m backend.ingestion.generate_synthetic_footprints

# Re-run full analysis after data refresh
py -3.11 -u scripts/run_analysis.py
```

### Quarterly Tasks (manual reminder)

Streets and buildings change rarely. Check for updates quarterly:

```bash
# Truncate + re-download streets
psql $DATABASE_URL -c "TRUNCATE street_centerlines; TRUNCATE street_buffers;"
py -3.11 -u -m backend.ingestion.fetch_streets

# Buildings: check Microsoft release notes, then:
psql $DATABASE_URL -c "TRUNCATE building_footprints;"
py -3.11 -u -m backend.ingestion.fetch_buildings
py -3.11 -u -m backend.ingestion.generate_synthetic_footprints
```

---

## Data Pipeline

```
External Sources                    PostGIS Tables              Analysis            API / Frontend
─────────────────                   ──────────────              ────────            ──────────────

ArcGIS Parcels_NEW ──────────────► parcels ──────────┐
                                                     │
ArcGIS Planning MapServer/12 ────► zoning_districts ─┤
                                                     ├──► batch_processor.py ──► subdivision_analysis
Microsoft Building Footprints ───► building_         │         │                        │
  + generate_synthetic_footprints  footprints ───────┤         │                        │
                                                     │    udo_rules.json                │
ArcGIS Roads_Clip ───────────────► street_           │                                  │
                                   centerlines ──────┘                                  ▼
                                   street_buffers                                 /api/parcels
                                                                                  /api/parcels/geojson
ArcGIS Fire/Stormwater ──────────► utility_lines ─────────────────────────► /api/utilities/geojson

Redfin gis-csv ──────────────────► redfin_listings ───────────────────────► /api/parcels/for-sale

Carto CDN ─────────────────────────────────────────── (browser) ──────────► MapLibre basemap
```

---

## Source URL Index

| Dataset | Full URL |
|---------|----------|
| Parcels | `https://services2.arcgis.com/G5vR3cOjh6g2Ed8E/arcgis/rest/services/Parcels_NEW/FeatureServer/0` |
| Zoning | `https://webgis2.durhamnc.gov/server/rest/services/PublicServices/Planning/MapServer/12` |
| Streets | `https://services2.arcgis.com/G5vR3cOjh6g2Ed8E/arcgis/rest/services/Roads_Clip/FeatureServer/5` |
| Buildings | `https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv` |
| Fire hydrants | `https://webgis.durhamnc.gov/server/rest/services/PublicWorksServices/FireFlow2/MapServer/2` |
| Stormwater pipes | `https://webgis.durhamnc.gov/server/rest/services/PublicWorksServices/StormwaterUtilitiesMapService/MapServer/6` |
| Stormwater structures | `https://webgis.durhamnc.gov/server/rest/services/PublicWorksServices/StormwaterUtilitiesMapService/MapServer/2` |
| Redfin | `https://www.redfin.com/stingray/api/gis-csv` |
| UDO (reference) | `https://udo.durhamnc.gov/` |
| Basemap | `https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json` |
