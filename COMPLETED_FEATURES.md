# Completed Features (Archived)

Features that were previously listed in FUTURE_FEATURES.md and have been implemented.

---

## Address Search (Completed)

- Autocomplete search by address across all parcels
- Fly-to-parcel on selection with zoom based on lot size
- Keyboard navigation (arrow keys + enter)
- Subdividable/not badges on search results

---

## Scheduled Listing Refresh (Completed)

- Docker cron service (`listings-cron`) runs `fetch_listings.py` at startup then every 24 hours
- `Dockerfile.cron` + `scripts/cron_listings.sh`
- Configurable via `DATABASE_URL` env var

---

## Utility Infrastructure Overlay (Partial — Completed Layers)

Implemented layers:
- **Fire Hydrants** — point layer indicating city water main proximity
- **Stormwater Pipes** — polyline layer for storm drainage
- **Stormwater Structures** — catch basins and manholes

Toggle controls in filter panel with zoom-level gating (z15+).

Still remaining (see FUTURE_FEATURES.md):
- Sewer gravity mains
- Water mains
- Proximity analysis / hookup feasibility badge

---

## Mobile Responsiveness (Partial)

Implemented:
- Bottom sheet for parcel detail panel (drag to expand/collapse)
- Filter panel as full-screen drawer on mobile
- Collapsible stats bar with horizontal scroll
- Touch-friendly interactions

---

## Redfin "For Sale" Integration (Completed)

- Polygon-based Redfin Stingray API download (recursive price-band splitting)
- Spatial join to parcels via PostGIS ST_Contains
- Gold map highlighting for subdividable+for-sale parcels
- Rich listing detail panel (price, beds/baths/sqft, DOM, iframe preview)
- "For Sale Now" browseable list panel with prev/next navigation
- Listing photo scraping (og:image) for enhanced tooltips and cards
- Filter toggle for for-sale-only view
