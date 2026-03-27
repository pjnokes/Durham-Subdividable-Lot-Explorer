# Current Status — Durham Subdividable Lots Finder

## What's Been Built (Tasks 1-11 Complete + Refinements)

### Backend Pipeline
1. **Data Ingestion** — 128,483 parcels, 2,485 zoning districts, 134,996 building footprints in PostGIS
2. **UDO Rules Engine** — `backend/udo/rules_engine.py` with 43 passing unit tests
3. **Quick Filter** — Classifies all parcels by area vs zoning minimums, with:
   - Street frontage checks (landlocked excluded, interior = flag lot only)
   - Flag lot width validation (20ft pole + min district width)
   - Owner exclusions (City of Durham, Durham Public Schools, Durham County, State of NC, US Govt, Housing Authority, Duke University, NC Central)
   - Land class filtering (only `RES/` and `VAC RES/` prefixes qualify)
4. **Street Access Analysis** — `backend/analysis/street_access.py` detects corner vs interior lots via spatial adjacency
5. **Geometric Analysis** — Street detection → setback buffering → lot splitting → structure fitting → flag lot analysis
6. **Batch Processor** — Parallel processing with `ProcessPoolExecutor` (8 workers). Each worker gets parcel IDs only, opens its own DB connection, loads geometry locally. Avoids WKB serialization crashes on Windows.
7. **FastAPI** — REST API with parcel GeoJSON, analysis stats, zoning rules, CSV export
8. **Building Footprint Logic** — Primary structure preserved, accessory structures (sheds) can be demolished

### Frontend
- React + TypeScript + Vite + deck.gl + MapLibre GL JS + Tailwind CSS
- Dark mode map with color-coded parcels by classification
- All parcel lot lines visible (not just highlighted ones)
- Proposed lot lines (blue) and proposed structures (orange) render when clicking a processed parcel
- Filter panel: subdividable toggle, corner lots only, zoning dropdown, min lots slider
- Parcel detail panel with analysis results, street access info, corner/interior badges
- CSV export with owner mailing info

## Current Numbers
- **128,483** total parcels
- **21,501** classified as subdividable
- **4,965** with full geometric analysis + proposed lot geometry
  - 2,181 small lot | 1,577 flag lot | 1,207 standard
- **2,655** with existing structure conflicts
- **2,297** excluded as government/institutional owners

## What's Working Well
- Parallel batch processing: 8 workers, ~370 parcels/min, full run ~45 min
- Street access classification is accurate for corner vs interior lots
- Flag lot width validation prevents unrealistic narrow-lot subdivisions
- Owner/land class exclusions remove government and non-residential parcels

## Recent Changes (Batch Re-run Required)

### Primary Structure Preservation
- **`lot_splitter.py`**: `split_parcel()` now accepts `primary_structure` parameter
  - Split lines are projected onto the perpendicular axis; an exclusion zone is computed from the structure's extent (+ 5 ft buffer)
  - Positions that fall within the exclusion zone are shifted to the nearest safe side
  - Final validation: primary structure must be fully contained within exactly one lot
  - More jitter offsets tried (±2%, ±5%, ±8%, ±12%) for better structure-avoiding configurations
- **`flag_lot.py`**: `try_flag_lot()` now accepts `primary_structure`
  - Split lines and pole geometry are validated against the primary structure
  - Pole cannot intersect the primary structure
  - Structure fitting is only required on lots that don't contain the existing structure
- **`batch_processor.py`**: Passes `primary_structure` to both `split_parcel()` and `try_flag_lot()`
  - Only proposes new structures on lots that DON'T hold the primary
  - Notes now indicate which lot keeps the existing structure (e.g. "existing structure kept on lot 1")
  - Flag lot pole geometry is included in `proposed_lots` MultiPolygon (renders as the "flag" shape)

### Frontend Improvements
- **All parcels now visible** by default (subdividableOnly=false) — non-subdividable lots shown with subtle outlines, all are clickable
- **Proposed lots rendered individually** — MultiPolygon exploded into individual features with distinct colors (blue, purple, pink, green, orange, sky)
- **Flag lot pole** visible as part of the proposed lots geometry
- **Address fallback** — ParcelDetail shows mailing address when site address is missing, with "(using mailing address)" note
- **Richer tooltip** — shows acreage, assessed value, and cleaner formatting
- **API GeoJSON** now includes `total_land_value`, `total_bldg_value`, `land_class`, `acreage`
- **Pydantic schema** `location_addr` aliased as `address` for consistent frontend mapping

### Documentation
- `FUTURE_FEATURES.md` created with plans for:
  - Mobile responsiveness (bottom sheet, collapsible panels, responsive breakpoints)
  - City sewer & water overlay (Durham ArcGIS REST services identified)
  - Other potential features (address search, floodplain, ADU analysis)

## Redfin "For Sale" Integration
- **`backend/ingestion/fetch_listings.py`** — downloads active listings from Redfin's Stingray API (gis-csv endpoint)
  - Uses polygon-based search covering Durham's bounding box
  - Recursive price-band splitting when results hit the 350-row cap
  - Strictly filters to `status = 'Active'` only (no pending/contingent/pre-market)
  - Spatial join: matches listing lat/lng to parcel polygons via PostGIS `ST_Contains`
  - Stores in `redfin_listings` table with FK to `parcels`
  - DB_URL configurable via `DATABASE_URL` env var (for Docker)
- **Docker cron service** (`listings-cron`): runs `fetch_listings.py` at startup then every 24 hours
  - `Dockerfile.cron` + `scripts/cron_listings.sh`
  - Added to `docker-compose.yml` as `listings-cron` service, depends on `db` health
- **API changes**: GeoJSON + parcel detail endpoints join `redfin_listings` with `AND status = 'Active'`; GeoJSON includes `for_sale`, `list_price`, `redfin_url`, `days_on_market`
- **Frontend**:
  - Gold fill + 8px glow for subdividable+for-sale parcels; muted red for for-sale only
  - "FOR SALE · SUBDIVIDABLE" tooltip in gold; "FOR SALE" in red for non-subdividable
  - Rich listing detail panel: large price hero, beds/baths/sqft/year stat bar, $/sqft, DOM with stale highlight, lot size, HOA, MLS#
  - "View Full Listing on Redfin" button + "Show Listing Preview" toggle with embedded Redfin iframe
  - Gold highlight banner on subdividable+for-sale parcels
  - "For sale only" toggle in filter panel (red accent)
  - Map legend in bottom-right corner
- **To populate**: `python -u -m backend.ingestion.fetch_listings` (or let Docker cron handle it)

## "For Sale Now" Browseable View
- **Backend**: `GET /api/parcels/for-sale` endpoint returns all active listings with parcel + analysis data + coordinates
- **Frontend**: `ForSalePanel` component with:
  - "For Sale" button in StatsBar opens dedicated browseable list panel
  - List/card view of all active listings sorted by subdividable-first, then price
  - "All" / "Subdividable" tab filtering
  - Prev/Next arrow navigation that flies the map to each listing
  - Listing photos displayed on cards (from og:image scraping)
  - Redfin link on each card
  - Clicking a card selects the parcel and opens the detail panel
- **Enhanced Map Tooltip**: For-sale parcels show rich tooltip with listing photo (when available), price, bedroom/bath count, and subdividable badge
- **Listing Photo Scraping**: `fetch_listings.py` now scrapes og:image URLs from Redfin listing pages and stores in `photo_url` column
- **Notification Bell** (demo): Top-right bell icon with subscribe-to-alerts dropdown
  - Email input, subdividable-only checkbox, max price filter
  - "Subscribe" button shows success message (UI demo only — no backend yet)
  - See `FUTURE_FEATURES.md` for making this functional

## Next Steps
- **Re-run batch processor** — algorithm changes require re-running `batch_processor.py` to recompute all subdivision geometries with structure preservation
- **Email alerts backend** — see `FUTURE_FEATURES.md`
- **Sewer/water overlay** — see `FUTURE_FEATURES.md`

## How to Run Things

### Services
```bash
# Database + daily listing cron (always running)
docker compose up -d

# API server
source .venv/Scripts/activate && python -u -m uvicorn backend.main:app --port 8000 --host 0.0.0.0

# Frontend dev server
cd frontend && npm run dev -- --host 0.0.0.0 --port 5173

# Or serve production build
cd frontend && npx serve dist -l 5173

# Check listing cron logs
docker compose logs -f listings-cron
```

### Analysis Pipeline (run in order)
```bash
source .venv/Scripts/activate

# 1. Street access analysis (spatial adjacency, ~70 sec)
python -u -m backend.analysis.street_access

# 2. Quick filter (area + zoning + owner + land class, ~2.5 min)
python -u -m backend.analysis.quick_filter

# 3. Geometric analysis (parallel, 8 workers, ~45 min for all)
python -u -m backend.analysis.batch_processor        # all subdividable
python -u -m backend.analysis.batch_processor 500     # or limit to N

# 4. Redfin for-sale listings (downloads + spatial match, ~1-2 min)
python -u -m backend.ingestion.fetch_listings
```

### Monitor Batch Progress via DB
```sql
SELECT COUNT(*) FROM subdivision_analysis WHERE proposed_lots IS NOT NULL;
SELECT COUNT(*) FROM subdivision_analysis WHERE notes IS NOT NULL AND notes != '';
```

## Architecture Notes
- All geometry in EPSG:2264 (NC State Plane, feet) for analysis, stored as both 2264 and 4326 in PostGIS
- GeoJSON API uses raw SQL for performance (not ORM)
- Frontend fetches by viewport bbox with debounced requests
- `backend/udo/udo_rules.json` is the source of truth for zoning dimensional standards
- Batch processor workers only receive parcel ID lists (no WKB) — each opens its own DB connection
- Python 3.11 — use `py -3.11` for all Python commands on Windows
