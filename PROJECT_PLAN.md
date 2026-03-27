# Durham Subdividable Lots Finder

## Overview

A tool that analyzes every residential lot in Durham, NC to determine if it can be legally subdivided under the Unified Development Ordinance (UDO). For viable lots, it algorithmically fits new lot lines and structure footprints, then displays results on an interactive map.

---

## Feasibility Assessment

### Is the geometry/subdivision fitting feasible?

**Yes, with caveats.** Here's the honest breakdown:

**What's straightforward (80% of the value):**
- Filtering lots by area vs. minimum lot size for their zoning district (the "quick filter" Devin suggested)
- Computing whether a lot has enough area to split into 2+ lots meeting minimums
- Applying setback buffers inward from lot boundaries using Shapely
- Checking if a rectangular structure footprint fits inside the setback-buffered area
- Rectangular and near-rectangular lots (the majority of suburban lots)

**What's harder but doable (the interesting 20%):**
- Irregular polygon subdivision — finding the optimal split line that creates two conforming lots
- Flag lot detection and fitting — the "pole" geometry connecting the rear lot to the street
- Lots with curves, easements, or odd shapes
- Determining which edge of a lot is the "street" frontage (needed for setback direction)

**What would require significant effort (stretch goals):**
- Topography/slope analysis (steep lots may not be buildable)
- Floodplain/wetland overlay (data exists but adds a layer)
- Utility easement detection
- Tree preservation requirements

**Recommendation:** Start with the "quick filter" approach (Phase 1-2) which gets you 80% of the value, then layer on geometric fitting (Phase 3). Even the basic filter creates a useful mailer list.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│          Frontend (React + deck.gl + MapLibre GL JS)     │
│  GPU-accelerated map rendering 120k+ parcel polygons     │
│  Color-coded subdivision overlays, detail panels         │
└──────────────────┬───────────────────────────────────────┘
                   │ REST API
┌──────────────────▼───────────────────────────────────────┐
│              Backend (Python / FastAPI)                    │
│  - API endpoints for lot queries and filtering            │
│  - Subdivision analysis engine                            │
│  - UDO rules engine                                       │
└──────────┬───────────────────┬───────────────────────────┘
           │                   │
┌──────────▼─────────┐ ┌──────▼──────────────────────┐
│  PostgreSQL +      │ │  UDO Rules Config            │
│  PostGIS (Docker)  │ │  (udo_rules.json — hand-     │
│  - Parcels         │ │   verified from UDO)         │
│  - Zoning          │ │                              │
│  - Building ftprts │ │                              │
│  - Analysis results│ └─────────────────────────────┘
└────────────────────┘
```

### Tech Stack (Finalized)

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Backend | Python 3.12 + FastAPI | Owner preference; excellent geo libraries |
| Database | PostgreSQL 16 + PostGIS 3.4 | Industry standard for geospatial; spatial indexes and queries |
| Database hosting | Docker Compose | One-command PostGIS setup, no local install needed |
| Geometry Engine | Shapely + GeoPandas | Polygon operations, setback buffers, intersection tests |
| Data Ingestion | GDAL/OGR + requests | Shapefile/GDB parsing, ArcGIS API queries |
| Frontend | React + TypeScript + Vite | Fast to scaffold, great ecosystem |
| Map Renderer | deck.gl + MapLibre GL JS | GPU-accelerated (1M+ items at 60fps), no API key, fully open source |
| Containerization | Docker Compose | PostgreSQL + PostGIS in one command |

---

## Data Sources

### 1. Parcel/Lot Data (Primary)

- **Source:** Durham Open Data Portal — ArcGIS FeatureServer
- **URL:** `https://services2.arcgis.com/G5vR3cOjh6g2Ed8E/arcgis/rest/services/Parcels_NEW/FeatureServer/0`
- **Format:** GeoJSON via REST API (paginated, 2000 records per request)
- **Key Fields:**
  - `OBJECTID_1` — unique ID
  - `PIN` — parcel identification number
  - `ZONING` — zoning district code (e.g., "RS-10", "RU-5")
  - `ACREAGE` / `CALCULATED_ACRES` / `DEEDED_ACRES` — lot size
  - `LAND_CLASS` — land classification
  - `LOCATION_ADDR` — street address
  - `PROPERTY_OWNER` — owner name
  - `OWNER_MAIL_*` — mailing address fields (for direct mail campaigns)
  - `TOTAL_PROP_VALUE` / `TOTAL_LAND_VALUE_ASSESSED` — assessed values
  - `HEATED_AREA` — existing structure size
  - `Shape__Area` / `Shape__Length` — computed geometry metrics (in feet, SRID 2264)
  - Geometry: polygon (lot boundary)
- **Spatial Reference:** WKID 102719 / EPSG:2264 (NC State Plane, feet)
- **Estimated records:** ~120,000+ parcels

### 2. Zoning Districts (Overlay)

- **Source:** Durham Open Data Portal
- **URL:** `https://live-durhamnc.opendata.arcgis.com/datasets/zoning-1`
- **Also:** ArcGIS MapServer Layer 12: `https://webgis2.durhamnc.gov/server/rest/services/PublicServices/Planning/MapServer/12`
- **Format:** GeoJSON
- **Purpose:** Spatial zoning boundaries (parcels have a ZONING field, but this provides the authoritative geometry and handles split-zoned parcels)

### 3. Building Footprints (Existing Structures)

- **Source:** NC Emergency Management Spatial Data Download
- **URL:** `https://sdd.nc.gov/DownloadFiles.aspx?path=BuildingFootprintsbyCounty/2021`
- **Format:** File Geodatabase (.gdb) by county — download Durham County
- **Key Fields:** Polygon geometry, square footage
- **Purpose:** Know where existing structures sit on a lot; determine if subdivision is possible without demolition

### 4. UDO Rules (Regulatory)

- **Source:** Durham UDO website `https://udo.durhamnc.gov/udo/Home.htm`
- **Also available as:** PDF hardcopy from `https://www.durhamnc.gov/5220/UDO-Archive`
- **Key Sections to Parse:**
  - **Article 4** — Zoning Districts (which districts exist)
  - **Article 6** — District Intensity Standards
    - Sec. 6.3 — RS (Residential Suburban) dimensional standards
    - Sec. 6.4 — RU (Residential Urban) dimensional standards
  - **Article 7** — Design Standards
    - Sec. 7.1 — Housing Types (lot dimensions, setbacks per housing type)
  - **Article 13** — Subdivision Requirements
    - Sec. 13.5 — Lot Standards (flag lots, access, side lot lines)
- **Approach:** Scrape HTML pages from udo.durhamnc.gov and extract tables into structured JSON. The UDO is already online as individual HTML pages per section — much easier to parse than the giant PDF.

---

## UDO Rules Summary (What the Engine Must Encode)

### Zoning District Dimensional Standards

#### RS Districts — Conventional Subdivision (Single-Family Detached)

| District | Min Lot Area | Min Lot Width | Street Yard | Side Yard | Rear Yard | Max Density |
|----------|-------------|--------------|-------------|-----------|-----------|-------------|
| RS-20 | 20,000 sf | 100 ft | 35 ft | 12 ft | 25 ft | 2.0 du/ac |
| RS-10 | 10,000 sf | 75 ft | 25 ft | 10 ft | 25 ft | 4.0 du/ac |
| RS-8 | 8,000 sf | 60 ft | 25 ft | 9 ft | 25 ft | 5.0 du/ac |
| RS-M | 5,000 sf | 35 ft | 20 ft | 5 ft | 25 ft | 8.0 du/ac |

#### RS Districts — Cluster Subdivision

| District | Min Lot Area | Min Lot Width | Street Yard | Side Yard | Rear Yard |
|----------|-------------|--------------|-------------|-----------|-----------|
| RS-20 | 10,000 sf | 75 ft | 25 ft | 9 ft | 25 ft |
| RS-10 | 5,000 sf | 40 ft | 20 ft | 6 ft | 25 ft |
| RS-8 | 4,000 sf | 40 ft | 20 ft | 6 ft | 25 ft |

#### RU Districts — Conventional Subdivision

| District | Min Lot Area | Min Lot Width | Street Yard | Side Yard | Rear Yard |
|----------|-------------|--------------|-------------|-----------|-----------|
| RU-5 / RU-5(2) | 5,000 sf | 45 ft | 20 ft | 5 ft | 25 ft |
| RU-M | 3,500 sf | 35 ft | 15 ft | 5 ft | 25 ft |

#### Small Lot Option

**Applies in any tier:** RC, RS-M, RU-M, RU-5, RU-5(2)
**Applies in Urban Tier ONLY:** RS-8, RS-10
**NOT allowed:** RS-20

| Standard | Value |
|----------|-------|
| Min Lot Area | 2,000 sf |
| Min Lot Width | 25 ft |
| Street Yard | 10 ft |
| Side Yard | 5 ft |
| Rear Yard | 15 ft |
| **Max Building Footprint** | **800 sf** |
| **Max Building Total Area** | **1,200 sf** |
| **Max Height** | **25 ft** |

#### Flag Lot Standards

- Minimum pole width: 20 ft (proposed reduction to 12 ft for Urban Tier)
- Both resulting lots must meet district dimensional standards
- Front setback of flag lot = side yard setback of district
- Cannot make parent lot nonconforming

#### Lot Averaging

- Up to 15% reduction in min lot area allowed
- Average of all lots in subdivision must meet minimum
- Overall density cannot exceed maximum

### Height Limits

- RS districts: 3 stories / 40 ft max
- Additional height allowed with additional setback (1 story per 10 ft of additional setback)

---

## Phased Build Plan

### Phase 0: Project Setup (Day 1, ~2 hours)

- [ ] Initialize git repo, Python project structure
- [ ] Set up Docker Compose for PostgreSQL + PostGIS
- [ ] Create `requirements.txt` / `pyproject.toml`
- [ ] Establish database schema (parcels, zoning, buildings, analysis_results)
- [ ] Write basic configuration management

### Phase 1: Data Ingestion Pipeline (Days 1-2, ~6-8 hours)

**Goal:** Get all raw data into PostGIS

- [ ] **1a: Parcel Data Ingestion** — Script to paginate through ArcGIS FeatureServer, download all parcels as GeoJSON, load into PostGIS
  - Handle pagination (2000 record limit per request)
  - Transform SRID 2264 → 4326 (WGS84) for display, keep original for area calculations
  - Store both raw geometry and useful computed fields
- [ ] **1b: Zoning Data Ingestion** — Download zoning polygons, load into PostGIS
  - Spatial join parcels ↔ zoning for split-zoned parcels
- [ ] **1c: Building Footprints** — Download Durham County .gdb from NC SDD, extract with GDAL, load into PostGIS
  - Spatial join footprints → parcels
- [ ] **1d: Data Validation** — QA queries to verify counts, coverage, orphaned records

### Phase 2: UDO Rules Engine (Days 2-3, ~4-6 hours)

**Goal:** Encode all subdivision rules as queryable logic

- [ ] **2a: UDO Scraper** — Scrape the HTML pages from `udo.durhamnc.gov` for Articles 4, 6, 7, 13
  - Parse dimensional standards tables into structured data
  - Store as `udo_rules.json` or YAML config file
- [ ] **2b: Rules Engine** — Python module that takes a parcel + zoning and returns:
  - Minimum lot size for the district
  - All setback values (street, side, rear)
  - Whether small lot option applies
  - Whether flag lot is possible
  - Maximum density
  - Allowed housing types
- [ ] **2c: Quick Filter** — SQL/Python logic to immediately classify parcels:
  - `NOT_SUBDIVIDABLE` — lot is at or below minimum for its zoning
  - `POTENTIALLY_SUBDIVIDABLE` — lot area ≥ 2x minimum lot size
  - `LIKELY_SUBDIVIDABLE` — lot area ≥ 2x minimum AND lot width ≥ 2x minimum width
  - `NEEDS_GEOMETRIC_ANALYSIS` — lot is large enough but irregular shape

### Phase 3: Geometric Subdivision Engine (Days 3-5, ~8-12 hours)

**Goal:** For "potentially subdividable" lots, find actual lot line configurations

- [ ] **3a: Street Frontage Detection**
  - Identify which edge(s) of the parcel polygon are on a street
  - Use adjacency analysis: edges that touch right-of-way polygons or have no neighboring parcel
  - Alternative: use parcel address geocoding + nearest edge
- [ ] **3b: Setback Buffer Engine**
  - Given a parcel polygon and its setbacks, compute the "buildable envelope"
  - Inward buffer with different distances per edge (street vs side vs rear)
  - Uses Shapely's `buffer()` and `parallel_offset()`
- [ ] **3c: Lot Splitting Algorithms**
  - **Simple split:** For rectangular-ish lots, split with a line parallel to the narrower dimension
  - **Flag lot split:** Carve out a rear lot with a 20ft-wide "pole" to the street
  - **Multiple splits:** For large lots, try 2-way, 3-way, etc. splits
  - **Optimization:** Try multiple split positions, score by:
    - Do both/all resulting lots meet minimums?
    - Can a reasonable structure fit in each lot?
    - Minimize wasted space
- [ ] **3d: Structure Fitting**
  - For each proposed new lot, compute the buildable area (lot minus setbacks)
  - Check if a minimum viable structure fits (e.g., 800-1200 sf footprint rectangle)
  - Try rotations aligned with lot edges
  - Report: max structure footprint that fits
- [ ] **3e: Existing Structure Conflict Detection**
  - Overlay existing building footprints
  - Flag if proposed lot lines would bisect an existing structure
  - Determine if subdivision is possible WITHOUT demolishing the existing house

### Phase 4: Analysis Pipeline (Day 5, ~4 hours)

**Goal:** Run the full analysis and store results

- [ ] **4a: Batch Processor** — Run analysis across all "potentially subdividable" parcels
  - Parallel processing with multiprocessing
  - Store results in `analysis_results` table:
    - `parcel_id`, `is_subdividable`, `subdivision_type` (standard/flag/small_lot/cluster)
    - `proposed_lot_lines` (geometry)
    - `proposed_structure_footprints` (geometry)
    - `num_new_lots`, `min_new_lot_area`, `confidence_score`
    - `notes` (human-readable explanation)
- [ ] **4b: Summary Statistics** — Generate counts by zoning district, neighborhood, etc.

### Phase 5: API Layer (Day 6, ~4 hours)

**Goal:** FastAPI backend serving data to the frontend

- [ ] **5a: Core Endpoints**
  - `GET /api/parcels` — paginated list with filters (zoning, subdividable, area range)
  - `GET /api/parcels/{id}` — full detail including analysis results
  - `GET /api/parcels/geojson` — GeoJSON FeatureCollection for map display (with bbox filter)
  - `GET /api/stats` — summary statistics
  - `GET /api/zoning-rules/{district}` — UDO rules for a district
- [ ] **5b: Spatial Queries**
  - Bounding box queries for map viewport
  - Vector tile endpoint (or use pg_tileserv / Martin)
- [ ] **5c: Export**
  - `GET /api/export/csv` — filtered list as CSV (for mailer campaigns)
  - `GET /api/export/geojson` — filtered results as downloadable GeoJSON

### Phase 6: Frontend Map UI (Days 6-8, ~8-10 hours)

**Goal:** Interactive map showing all analyzed lots

- [ ] **6a: Map Setup**
  - React + Vite project with deck.gl + MapLibre GL JS (no API key needed)
  - Base map centered on Durham, NC (35.994, -78.8986)
  - Load parcels via deck.gl GeoJsonLayer (GPU-accelerated, handles 120k+ polygons at 60fps)
  - Color-code by subdividability result
- [ ] **6b: Lot Interaction**
  - Click a lot → show detail panel:
    - Address, owner, zoning, assessed value
    - Current lot dimensions
    - Subdivision analysis result
    - Proposed lot lines (overlaid on map)
    - Proposed structure footprint(s)
  - Hover highlight
- [ ] **6c: Filtering**
  - Filter panel: zoning district, min/max lot size, subdividable only, subdivision type
  - Search by address
- [ ] **6d: Visualization**
  - Green: subdividable lots
  - Yellow: potentially subdividable (needs geometric review)
  - Gray: not subdividable
  - Blue outlines: proposed new lot lines
  - Red outlines: proposed structure footprints

### Phase 7: Polish & Stretch Goals (Ongoing)

- [ ] Add Raleigh / Wake Forest / Cary support (different UDOs, same architecture)
- [ ] MLS/Zillow integration for "for sale" status
- [ ] Likelihood-to-sell scoring (via Connected Investors or similar API)
- [ ] Mailing list export with owner contact info
- [ ] Floodplain overlay (FEMA data available from same NC SDD source)
- [ ] Topography analysis
- [ ] ADU (Accessory Dwelling Unit) analysis — can an ADU be added without subdividing?

---

## Database Schema (PostgreSQL + PostGIS)

```sql
-- Enable PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;

-- Raw parcel data from Durham
CREATE TABLE parcels (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    pin VARCHAR(14),
    reid VARCHAR(20),
    zoning VARCHAR(255),
    land_class VARCHAR(50),
    acreage DOUBLE PRECISION,
    calculated_acres DOUBLE PRECISION,
    location_addr VARCHAR(100),
    property_owner VARCHAR(600),
    owner_mail_1 VARCHAR(50),
    owner_mail_2 VARCHAR(50),
    owner_mail_city VARCHAR(50),
    owner_mail_state VARCHAR(20),
    owner_mail_zip VARCHAR(6),
    total_prop_value DOUBLE PRECISION,
    total_land_value DOUBLE PRECISION,
    total_bldg_value DOUBLE PRECISION,
    heated_area INTEGER,
    total_units DOUBLE PRECISION,
    deed_date TIMESTAMP,
    geom GEOMETRY(Polygon, 4326),         -- WGS84 for display
    geom_stateplane GEOMETRY(Polygon, 2264), -- NC State Plane for calculations (feet)
    area_sqft DOUBLE PRECISION GENERATED ALWAYS AS (ST_Area(geom_stateplane)) STORED,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_parcels_geom ON parcels USING GIST (geom);
CREATE INDEX idx_parcels_geom_sp ON parcels USING GIST (geom_stateplane);
CREATE INDEX idx_parcels_zoning ON parcels (zoning);

-- Zoning district polygons
CREATE TABLE zoning_districts (
    id SERIAL PRIMARY KEY,
    zone_code VARCHAR(50),
    zone_name VARCHAR(255),
    geom GEOMETRY(MultiPolygon, 4326),
    geom_stateplane GEOMETRY(MultiPolygon, 2264)
);
CREATE INDEX idx_zoning_geom ON zoning_districts USING GIST (geom);

-- Building footprints
CREATE TABLE building_footprints (
    id SERIAL PRIMARY KEY,
    area_sqft DOUBLE PRECISION,
    parcel_id INTEGER REFERENCES parcels(id),
    geom GEOMETRY(Polygon, 4326),
    geom_stateplane GEOMETRY(Polygon, 2264)
);
CREATE INDEX idx_buildings_geom ON building_footprints USING GIST (geom);
CREATE INDEX idx_buildings_parcel ON building_footprints (parcel_id);

-- Analysis results
CREATE TABLE subdivision_analysis (
    id SERIAL PRIMARY KEY,
    parcel_id INTEGER REFERENCES parcels(id) UNIQUE,
    is_subdividable BOOLEAN,
    quick_filter_result VARCHAR(50),   -- NOT_SUBDIVIDABLE, POTENTIALLY, LIKELY, etc.
    subdivision_type VARCHAR(50),       -- standard, flag_lot, small_lot, cluster
    num_possible_lots INTEGER,
    min_new_lot_area_sqft DOUBLE PRECISION,
    max_structure_footprint_sqft DOUBLE PRECISION,
    confidence_score DOUBLE PRECISION,  -- 0.0 - 1.0
    proposed_lot_lines GEOMETRY(MultiLineString, 4326),
    proposed_lots GEOMETRY(MultiPolygon, 4326),
    proposed_structures GEOMETRY(MultiPolygon, 4326),
    existing_structure_conflict BOOLEAN,
    notes TEXT,
    analyzed_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_analysis_parcel ON subdivision_analysis (parcel_id);
CREATE INDEX idx_analysis_subdividable ON subdivision_analysis (is_subdividable);
```

---

## Project Structure

```
durham_subdividable_lots/
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
├── README.md
├── PROJECT_PLAN.md
│
├── backend/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app entry point
│   ├── config.py                  # Settings, DB connection
│   ├── database.py                # SQLAlchemy + PostGIS setup
│   │
│   ├── ingestion/                 # Phase 1: Data loading
│   │   ├── __init__.py
│   │   ├── fetch_parcels.py       # ArcGIS FeatureServer pagination
│   │   ├── fetch_zoning.py        # Zoning district download
│   │   ├── fetch_buildings.py     # NC SDD building footprints
│   │   └── load_to_postgis.py     # Common GeoJSON → PostGIS loader
│   │
│   ├── udo/                       # Phase 2: UDO rules
│   │   ├── __init__.py
│   │   ├── scraper.py             # Scrape udo.durhamnc.gov HTML pages
│   │   ├── parser.py              # Extract tables → structured data
│   │   ├── rules_engine.py        # Given parcel+zone → return rules
│   │   └── udo_rules.json         # Parsed UDO data (generated)
│   │
│   ├── analysis/                  # Phase 3-4: Subdivision analysis
│   │   ├── __init__.py
│   │   ├── quick_filter.py        # Fast area-based filtering
│   │   ├── street_detection.py    # Identify street frontage edges
│   │   ├── setback_engine.py      # Compute buildable envelopes
│   │   ├── lot_splitter.py        # Lot subdivision algorithms
│   │   ├── structure_fitter.py    # Fit building footprints
│   │   ├── flag_lot.py            # Flag lot specific logic
│   │   └── batch_processor.py     # Run analysis on all parcels
│   │
│   ├── api/                       # Phase 5: REST API
│   │   ├── __init__.py
│   │   ├── routes_parcels.py
│   │   ├── routes_analysis.py
│   │   ├── routes_export.py
│   │   └── schemas.py             # Pydantic models
│   │
│   └── models/                    # SQLAlchemy models
│       ├── __init__.py
│       ├── parcel.py
│       ├── zoning.py
│       ├── building.py
│       └── analysis.py
│
├── frontend/                      # Phase 6: React map UI
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── Map.tsx
│   │   │   ├── ParcelDetail.tsx
│   │   │   ├── FilterPanel.tsx
│   │   │   └── StatsPanel.tsx
│   │   ├── hooks/
│   │   │   └── useParcelData.ts
│   │   └── api/
│   │       └── client.ts
│   └── index.html
│
├── scripts/                       # One-off utility scripts
│   ├── init_db.sql                # Database setup
│   ├── run_ingestion.py           # Full data pipeline
│   └── run_analysis.py            # Full analysis pipeline
│
└── data/                          # Local data cache (gitignored)
    ├── parcels/
    ├── zoning/
    └── buildings/
```

---

## Finalized Decisions

| Decision | Answer |
|----------|--------|
| Database hosting | Docker Compose (PostGIS) |
| Map library | MapLibre GL JS + deck.gl (no API key, GPU-accelerated, open source) |
| Geometric fitting depth | Full — quick filter + geometric subdivision + structure fitting |
| Scope | Durham Phase 1; abstract rules engine for multi-jurisdiction later |
| Min structure footprint | 600 sf footprint (duplex on small lot), 1,200 sf total (2 story) |
| Small lot max | 800 sf footprint / 1,200 sf total / 25 ft height (per UDO Sec. 7.1) |
| Goal | Maximize number of lots per subdivision — more lots = more money |
| UI priority | Slick, interactive map — drag/zoom, highlighted lots, proposed subdivision overlays |

---

## Estimated Timeline

| Phase | Effort | Can Run Independently |
|-------|--------|-----------------------|
| Phase 0: Setup | 2 hrs | — |
| Phase 1: Data Ingestion | 6-8 hrs | — |
| Phase 2: UDO Rules Engine | 4-6 hrs | After Phase 0 |
| Phase 3: Geometry Engine | 8-12 hrs | After Phase 1+2 |
| Phase 4: Batch Analysis | 4 hrs | After Phase 3 |
| Phase 5: API | 4 hrs | After Phase 1 |
| Phase 6: Frontend | 8-10 hrs | After Phase 5 |
| **Total** | **~36-46 hrs** | |

With AI-assisted development, realistically 2-3 focused weekends or 1 solid week.

---

## Risk Factors

1. **ArcGIS API rate limiting** — The parcel FeatureServer may throttle. Mitigation: cache locally, respect pagination, add delays.
2. **UDO complexity** — There are edge cases (overlay districts, historic districts, neighborhood protection overlays) that modify base rules. V1 ignores these; they can be layered in.
3. **Data quality** — Some parcels may have missing zoning codes or incorrect geometries. Need validation/cleanup step.
4. **Split-zoned parcels** — Some parcels span multiple zoning districts. Need to handle with spatial intersection against zoning polygons.
5. **New UDO incoming** — Durham is rewriting its entire UDO (draft expected end of 2026, adoption early 2027). The rules engine should be data-driven so it can be updated.
