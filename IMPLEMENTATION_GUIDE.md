# Implementation Guide — Autonomous Execution Reference

This document is designed so a Cursor agent can work through each task sequentially using subagents. Each task is self-contained with clear inputs, outputs, and acceptance criteria.

Read `PROJECT_PLAN.md` first for full context. Read `backend/udo/udo_rules.json` for all zoning rules.

---

## Critical Rules

1. **Python 3.11.** Use `py -3.11` for ALL Python commands (Windows). NOT `python` or `python3`. Set up venv with `py -3.11 -m venv .venv` then `.venv\Scripts\activate`.
2. **UDO accuracy is paramount.** The zoning rules in `backend/udo/udo_rules.json` were hand-extracted from the Durham UDO. The rules engine MUST match these exactly. When in doubt, fetch the UDO page and verify: `https://udo.durhamnc.gov/udo/{section}.htm`
3. **Maximize lot count.** When analyzing subdivisions, the goal is to find the maximum number of conforming lots. More lots = more money. Try small lot option first (2,000 sf minimum), then standard, then flag lot.
4. **Use Docker for PostgreSQL.** `docker-compose.yml` is already set up. Just `docker compose up -d`.
5. **Frontend: MapLibre + deck.gl.** No API key needed. No Mapbox.
6. **Small lot building limits:** 800 sf max footprint, 1,200 sf max total, 25 ft max height.
7. **Standard structure assumption:** 600 sf footprint (can be 1,200 sf total as 2-story duplex).
8. **Test with real data.** After each phase, verify with actual Durham parcels.
9. **Cursor rules.** After completing each task or hitting a gotcha, create or update `.cursor/rules/*.mdc` files to help future sessions. Read `.cursor/rules/self-improvement.mdc` for the protocol.
10. **Git commits after every task.** After each task passes its acceptance criteria, stage and commit all changes with a descriptive message. Use conventional commit style: `feat:`, `fix:`, `chore:`, `refactor:`. One commit per task minimum. If a task is large, commit at logical checkpoints within it too.

---

## Task 1: Docker + Database Setup

**Goal:** PostgreSQL + PostGIS running in Docker, schema created, verified working.

**Steps:**
1. Run `docker compose up -d` from project root
2. Wait for healthcheck to pass
3. Connect and verify PostGIS extension: `SELECT PostGIS_Version();`
4. Run `scripts/init_db.sql` if not auto-loaded
5. Verify all 4 tables exist: parcels, zoning_districts, building_footprints, subdivision_analysis

**Acceptance:** Can connect to the database using `DATABASE_URL` from `.env` and run spatial queries.

**Git:** `git add -A && git commit -m "chore: docker + postgis setup with schema"`

---

## Task 2: Parcel Data Ingestion

**Goal:** Download all ~120k Durham parcels from ArcGIS FeatureServer into PostGIS.

**File:** `backend/ingestion/fetch_parcels.py`

**API Details:**
- Base URL: `https://services2.arcgis.com/G5vR3cOjh6g2Ed8E/arcgis/rest/services/Parcels_NEW/FeatureServer/0`
- Query endpoint: `{base}/query`
- Pagination: `resultOffset` + `resultRecordCount` (max 2000 per page)
- Request format: `f=geojson` for GeoJSON output
- Key params: `where=1=1&outFields=*&outSR=4326&f=geojson&resultOffset=0&resultRecordCount=2000`
- Native SRID: 2264 (NC State Plane feet). Request in 4326 for storage, but also store original for area calculations.
- To get count first: `{base}/query?where=1=1&returnCountOnly=true&f=json`

**Key parcel fields to store:**
OBJECTID, PIN, REID, ZONING, LAND_CLASS, ACREAGE, CALCULATED_ACRES, DEEDED_ACRES, LOCATION_ADDR, PROPERTY_OWNER, OWNER_MAIL_1, OWNER_MAIL_2, OWNER_MAIL_CITY, OWNER_MAIL_STATE, OWNER_MAIL_ZIP, TOTAL_PROP_VALUE, TOTAL_LAND_VALUE_ASSESSED, TOTAL_BLDG_VALUE_ASSESSED, HEATED_AREA, TOTAL_UNITS, DEED_DATE, Shape__Area, Shape__Length

**Processing:**
1. Query count first to know total
2. Paginate with offset, downloading GeoJSON pages
3. Cache raw GeoJSON to `data/parcels/` as backup
4. Insert into PostGIS using psycopg2 + ST_GeomFromGeoJSON
5. Also request in `outSR=2264` (NC State Plane) and store as `geom_stateplane` for accurate area calculations in feet
6. Compute `area_sqft` from `Shape__Area` field (already in sq ft from the source)

**Acceptance:** `SELECT COUNT(*) FROM parcels;` returns 100k+ rows. `SELECT ST_AsText(geom) FROM parcels LIMIT 1;` returns valid geometry.

**Git:** `git add -A && git commit -m "feat: parcel data ingestion from ArcGIS FeatureServer"`

---

## Task 3: Zoning Data Ingestion

**Goal:** Download zoning district polygons into PostGIS.

**File:** `backend/ingestion/fetch_zoning.py`

**API Details:**
- MapServer Layer 12: `https://webgis2.durhamnc.gov/server/rest/services/PublicServices/Planning/MapServer/12`
- Query: `{base}/query?where=1=1&outFields=*&outSR=4326&f=geojson&resultOffset=0&resultRecordCount=2000`
- Paginate same as parcels

**Processing:**
1. Download all zoning polygons
2. Insert into `zoning_districts` table
3. After loading, run spatial join to verify parcel ZONING field matches the spatial overlay:
   ```sql
   SELECT p.pin, p.zoning as parcel_zoning, z.zone_code as spatial_zoning
   FROM parcels p
   JOIN zoning_districts z ON ST_Intersects(p.geom, z.geom)
   WHERE p.zoning != z.zone_code
   LIMIT 20;
   ```

**Acceptance:** Zoning polygons loaded. Spatial join query runs successfully.

**Git:** `git add -A && git commit -m "feat: zoning district data ingestion"`

---

## Task 4: Building Footprints Ingestion

**Goal:** Download Durham County building footprints into PostGIS.

**File:** `backend/ingestion/fetch_buildings.py`

**Source:** NC Spatial Data Download — Durham County building footprints
- URL: `https://sdd.nc.gov/DownloadFiles.aspx?path=BuildingFootprintsbyCounty/2021`
- Format: File Geodatabase (.gdb)
- Need to find the direct download link for Durham County specifically

**Alternative approach if direct download is complex:**
- Microsoft Building Footprints (open data) for NC: search for "Microsoft US Building Footprints GeoJSON" — these are freely available on GitHub
- Or use the Durham Open Data portal if they have a buildings layer

**Processing:**
1. Download the .gdb or GeoJSON file
2. Use fiona/geopandas to read
3. Filter to Durham County bounds if needed
4. Insert into `building_footprints` table
5. Run spatial join to associate footprints with parcels:
   ```sql
   UPDATE building_footprints bf
   SET parcel_id = p.id
   FROM parcels p
   WHERE ST_Within(ST_Centroid(bf.geom), p.geom);
   ```

**Acceptance:** Building footprints loaded. Most footprints have a `parcel_id`. Spot-check a few addresses.

**Git:** `git add -A && git commit -m "feat: building footprints ingestion from NC SDD"`

---

## Task 5: UDO Rules Engine

**Goal:** Python module that takes a parcel's zoning code and returns all applicable subdivision rules.

**Files:**
- `backend/udo/rules_engine.py`
- `backend/udo/udo_rules.json` (already created — READ THIS FIRST)

**The rules engine must handle:**

1. **Standard lookup:** Given zoning code (e.g., "RS-10"), return:
   - min_lot_area_sqft, min_lot_width_ft
   - All setbacks (street_yard_ft, side_yard_ft, rear_yard_ft)
   - max_density_per_acre
   - allowed_housing_types
   - max_height_stories, max_height_ft

2. **Small lot option eligibility:** Check if zoning district qualifies:
   - Any tier: RC, RS-M, RU-M, RU-5, RU-5(2)
   - Urban tier ONLY: RS-8, RS-10
   - Never: RS-20
   - When eligible: min 2,000 sf lot, 800 sf max footprint, 1,200 sf max total, 25 ft height

3. **Flag lot rules:** min 20 ft pole width, front setback = side yard of district

4. **Lot averaging:** up to 15% reduction, average must meet minimum

5. **Key method signatures:**
   ```python
   def get_district_rules(zoning_code: str) -> DistrictRules
   def get_min_lot_size(zoning_code: str, subdivision_type: str = "conventional") -> float
   def is_small_lot_eligible(zoning_code: str, tier: str = "urban") -> bool
   def get_setbacks(zoning_code: str, lot_type: str = "standard") -> Setbacks
   def get_max_structure_size(zoning_code: str, lot_type: str = "standard") -> StructureLimits
   ```

6. **Handle compound zoning codes:** Parcels may have values like "RS-10/PDR" or "RU-5 CU". Strip overlays and extract base zone.

7. **Filter to residential only:** Non-residential zones (C, I, OI, etc.) should return `None` — not subdividable for our purposes.

**Write unit tests** that verify:
- RS-10 conventional min lot = 10,000 sf
- RU-5 small lot min = 2,000 sf
- RS-20 small lot NOT eligible
- RS-8 small lot eligible only in urban tier
- Small lot max footprint = 800 sf
- Flag lot pole width = 20 ft

**Acceptance:** All unit tests pass. Rules match the values in `udo_rules.json` exactly.

**Git:** `git add -A && git commit -m "feat: UDO rules engine with unit tests"`

---

## Task 6: Quick Filter Analysis

**Goal:** Classify every parcel as subdividable/not based on area vs. zoning minimums.

**File:** `backend/analysis/quick_filter.py`

**Logic:**
For each residential parcel:
1. Get its zoning code → look up rules
2. Get its area (from `area_sqft` or `Shape__Area`)
3. Get its effective lot width (approximate from geometry: bounding box width or minimum rotated rectangle width)
4. Classify:

| Classification | Criteria |
|----------------|----------|
| `NOT_RESIDENTIAL` | Zoning is not RS-* or RU-* |
| `TOO_SMALL` | Area < min lot size for zone (already nonconforming) |
| `AT_MINIMUM` | Area is between 1x and 1.5x min lot size |
| `SUBDIVIDABLE_SMALL_LOT` | Small lot eligible AND area ≥ min_lot_for_zone + 2000 sf |
| `SUBDIVIDABLE_STANDARD` | Area ≥ 2x min lot size for zone |
| `SUBDIVIDABLE_MULTIPLE` | Area ≥ 3x min lot size (could yield 3+ lots) |
| `NEEDS_GEOMETRY` | Area sufficient but width may be insufficient |

5. Store results in `subdivision_analysis` table (quick_filter_result column)
6. Estimate `num_possible_lots = floor(area / min_lot_size)` as upper bound

**Acceptance:**
- Every residential parcel has a classification
- `SELECT quick_filter_result, COUNT(*) FROM subdivision_analysis GROUP BY 1;` shows reasonable distribution
- Spot-check: a 20,000 sf lot in RS-10 should be `SUBDIVIDABLE_STANDARD` (2x the 10k minimum)

**Git:** `git add -A && git commit -m "feat: quick filter classification for all parcels"`

---

## Task 7: Geometric Subdivision Engine

**Goal:** For lots classified as subdividable, compute actual proposed lot lines and structure placements.

**Files:**
- `backend/analysis/street_detection.py`
- `backend/analysis/setback_engine.py`
- `backend/analysis/lot_splitter.py`
- `backend/analysis/structure_fitter.py`
- `backend/analysis/flag_lot.py`

### 7a: Street Frontage Detection

Determine which edge(s) of the parcel polygon face a street. This is needed to know where the "street yard" (front setback) applies vs side vs rear.

**Approach:**
1. For each parcel polygon, extract edges (line segments between consecutive vertices)
2. The street-facing edge is typically:
   - The edge closest to the parcel's geocoded address point
   - OR the shortest edge on a rectangular lot (lots are usually deeper than wide)
   - OR the edge that does NOT touch an adjacent parcel (use spatial query)
3. Simplest heuristic: use the edge closest to the centroid of the street (derived from the address)
4. Label edges as: STREET, SIDE_LEFT, SIDE_RIGHT, REAR

### 7b: Setback Buffer Engine

Given a parcel polygon and per-edge setbacks, compute the buildable envelope.

**Approach:**
1. For each edge, offset inward by the appropriate setback distance
2. The intersection of all inward-offset half-planes is the buildable area
3. Use Shapely: for simple cases, `polygon.buffer(-min_setback)` works
4. For per-edge setbacks: construct offset lines for each edge, intersect them to form the buildable polygon

### 7c: Lot Splitting

**Strategy — try splits in this order (maximize lot count):**

1. **Multiple small lots:** If small lot eligible, try fitting N lots of 2,000 sf each
   - Split with lines perpendicular to the street edge
   - Each resulting lot must be ≥ 25 ft wide and ≥ 2,000 sf
   - Check that a 600 sf footprint (with 10/5/5/15 ft setbacks) fits in each

2. **Standard subdivision:** Split into lots meeting district minimums
   - Split line parallel to side lot lines (perpendicular to street)
   - Both lots must meet min area AND min width

3. **Flag lot:** For deep lots where a front-back split makes sense
   - Create a 20 ft wide "pole" from street to rear lot
   - Rear lot (the "flag") must meet all dimensional standards
   - Front lot must remain conforming (not become nonconforming)

4. **Score each option:** `score = num_lots * 10 + total_buildable_area / 1000`
   - Pick the option with the highest score (most lots wins)

### 7d: Structure Fitting

For each proposed lot:
1. Compute the buildable envelope (lot minus setbacks)
2. Find the largest axis-aligned rectangle that fits inside the buildable envelope
3. If ≥ 600 sf → structure fits (for small lots, cap at 800 sf footprint)
4. Record the structure footprint polygon

### 7e: Existing Structure Conflict

1. Check if existing building footprints on the parcel overlap with proposed lot lines
2. Flag as `existing_structure_conflict = true` if so
3. Separately check if subdivision is possible while preserving the existing house on one of the resulting lots

**Store all results in `subdivision_analysis` table:**
- `proposed_lots` — MultiPolygon of the resulting lot geometries
- `proposed_lot_lines` — MultiLineString of the new lot lines
- `proposed_structures` — MultiPolygon of where structures could go
- `num_possible_lots`, `subdivision_type`, `confidence_score`
- `notes` — human-readable explanation

**Acceptance:**
- At least a few hundred parcels have geometric analysis results with proposed lot lines
- Proposed lots all meet their district minimums (validate programmatically)
- Structure footprints all fit within setback-buffered buildable areas
- No proposed lot line bisects an existing building (unless flagged)

**Git:** `git add -A && git commit -m "feat: geometric subdivision engine with lot splitting and structure fitting"`

---

## Task 8: Batch Analysis Pipeline

**Goal:** Run the full analysis across all parcels efficiently.

**File:** `backend/analysis/batch_processor.py`

**Steps:**
1. Run quick filter on all parcels (Task 6)
2. For parcels classified as subdividable, run geometric analysis (Task 7)
3. Use multiprocessing (ProcessPoolExecutor) for geometric analysis
4. Progress bar with tqdm
5. Store all results in DB
6. Generate summary stats

**Script:** `scripts/run_analysis.py`

**Acceptance:** Full pipeline runs end-to-end. Summary stats are printed.

**Git:** `git add -A && git commit -m "feat: batch analysis pipeline with multiprocessing"`

---

## Task 9: FastAPI Backend

**Goal:** REST API serving parcel data and analysis results to the frontend.

**Files:**
- `backend/main.py` — FastAPI app
- `backend/database.py` — async SQLAlchemy engine
- `backend/api/routes_parcels.py`
- `backend/api/routes_analysis.py`
- `backend/api/routes_export.py`
- `backend/api/schemas.py`
- `backend/models/*.py`

**Endpoints:**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/parcels` | Paginated parcel list with filters |
| GET | `/api/parcels/{id}` | Full parcel detail + analysis |
| GET | `/api/parcels/geojson?bbox=...` | GeoJSON for map viewport |
| GET | `/api/parcels/geojson?subdividable=true&bbox=...` | Filtered GeoJSON |
| GET | `/api/analysis/stats` | Summary statistics |
| GET | `/api/zoning-rules/{district}` | UDO rules for a district |
| GET | `/api/export/csv?filters...` | CSV export for mailing list |

**Key requirements:**
- GeoJSON endpoint must support `bbox` parameter for map viewport queries (PostGIS `ST_Intersects` with bbox)
- Must include analysis results (proposed lots, structures) in GeoJSON properties
- Proposed geometries should be returned as GeoJSON for frontend rendering
- CORS enabled for frontend dev server
- Run with: `py -3.11 -m uvicorn backend.main:app --reload --port 8000`

**Acceptance:** All endpoints return correct data. GeoJSON endpoint returns valid FeatureCollection. Can filter by subdividable status.

**Git:** `git add -A && git commit -m "feat: FastAPI backend with parcel, analysis, and export endpoints"`

---

## Task 10: Frontend Map UI

**Goal:** Slick interactive map UI showing all lots with subdivision analysis overlays.

**Tech:** React + TypeScript + Vite + deck.gl + MapLibre GL JS

### Setup
```bash
cd frontend
npm create vite@latest . -- --template react-ts
npm install deck.gl @deck.gl/react @deck.gl/layers @deck.gl/geo-layers maplibre-gl react-map-gl @types/maplibre-gl
npm install @deck.gl/mapbox
```

### Map Configuration
- Center: Durham, NC (35.994, -78.8986)
- Default zoom: 12
- Base map style: Use a free tile source — e.g., `https://basemaps.cartocdn.com/gl/positron-gl-style/style.json` or `https://tiles.versatiles.org/assets/styles/colorful.json`

### Layers (deck.gl)

1. **Parcels Layer** (GeoJsonLayer) — all parcel boundaries
   - Fill color based on `quick_filter_result`:
     - `SUBDIVIDABLE_MULTIPLE` → bright green (high value)
     - `SUBDIVIDABLE_STANDARD` → green
     - `SUBDIVIDABLE_SMALL_LOT` → teal
     - `NEEDS_GEOMETRY` → yellow
     - `AT_MINIMUM` / `TOO_SMALL` → transparent/very light gray
     - `NOT_RESIDENTIAL` → hidden by default
   - Stroke: thin dark outline
   - Opacity: 0.6 fill, 1.0 stroke
   - Pickable: true (for click/hover interaction)

2. **Proposed Lots Layer** (GeoJsonLayer) — shown when a parcel is selected
   - Dashed blue outlines for proposed new lot lines
   - Light blue fill for proposed new lots

3. **Proposed Structures Layer** (GeoJsonLayer) — shown when a parcel is selected
   - Semi-transparent orange/red rectangles for proposed structure footprints

4. **Existing Buildings Layer** (GeoJsonLayer) — shown when a parcel is selected
   - Dark gray fill for existing building footprints on the selected parcel

### UI Components

1. **Map** (full viewport, main component)
   - deck.gl DeckGL component with MapLibre base map
   - Load parcels GeoJSON from API based on current viewport bbox
   - Debounced fetch on map move/zoom

2. **Filter Panel** (left sidebar, collapsible)
   - Toggle: Show only subdividable lots
   - Dropdown: Zoning district filter (RS-10, RU-5, etc.)
   - Slider: Min/max lot size
   - Dropdown: Subdivision type (small lot, standard, flag lot)
   - Slider: Min number of possible lots (2, 3, 4+)
   - "Export CSV" button → calls `/api/export/csv`

3. **Parcel Detail Panel** (right sidebar, shown on click)
   - Address, PIN, owner name
   - Zoning district + applicable rules
   - Current lot area and dimensions
   - Assessed value
   - **Analysis Results:**
     - Subdividable: Yes/No
     - Type: Small Lot / Standard / Flag Lot
     - Number of possible new lots
     - Max structure footprint per new lot
     - Existing structure conflict warning
   - The map zooms to the selected parcel and shows proposed lots + structures

4. **Stats Bar** (top bar or bottom bar)
   - Total parcels analyzed
   - Total subdividable
   - Breakdown by type (small lot, standard, flag)

### Design
- Dark mode preferred for slick look
- Use Tailwind CSS or shadcn/ui for clean, modern components
- Smooth transitions on panel open/close
- Loading states with skeleton placeholders
- Responsive — works on desktop (primary) and tablet

**Acceptance:**
- Map loads and displays all Durham parcels color-coded by subdividability
- Clicking a parcel shows the detail panel with analysis results
- Clicking a subdividable parcel shows proposed lot lines and structure footprints overlaid on the map
- Filter panel filters the visible parcels
- Can drag/zoom smoothly with 120k+ polygons
- Looks polished and modern

**Git:** `git add -A && git commit -m "feat: interactive map UI with deck.gl, MapLibre, filtering, and detail panels"`

---

## Task 11: End-to-End Verification

**Goal:** Verify the full pipeline works correctly.

**Checks:**
1. Pick 5 known addresses in Durham, look them up in the app
2. Verify their zoning matches Durham's official zoning map
3. For subdividable lots, verify the proposed lots meet all UDO minimums
4. Check that small lot proposals don't exceed 800 sf footprint
5. Check that flag lot proposals have ≥ 20 ft pole width
6. Verify no proposed lot line cuts through an existing building
7. Check that the "number of possible lots" is actually achievable given the geometry
8. Export CSV and verify it contains owner mailing info

**Git:** `git add -A && git commit -m "chore: end-to-end verification complete"`

---

## Dependency Order

```
Task 1 (Docker/DB)
  └── Task 2 (Parcels) ─────────────────┐
  └── Task 3 (Zoning) ──────────────────┤
  └── Task 4 (Buildings) ───────────────┤
                                         ▼
Task 5 (Rules Engine) ──────────► Task 6 (Quick Filter)
                                         │
                                         ▼
                                  Task 7 (Geometry Engine)
                                         │
                                         ▼
                                  Task 8 (Batch Pipeline)
                                         │
                                         ▼
                                  Task 9 (API) ──► Task 10 (Frontend)
                                                        │
                                                        ▼
                                                  Task 11 (Verify)
```

Tasks 2, 3, 4 can run in parallel after Task 1.
Task 5 can run in parallel with Tasks 2-4 (no DB dependency).
Tasks 6-11 are sequential.
