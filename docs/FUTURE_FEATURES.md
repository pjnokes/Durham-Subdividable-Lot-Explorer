# Future Features

---

## Email Alerts / Notification System

Demo UI is in place (notification bell in top-right). To make it functional:

- **Backend**: Add `alert_subscriptions` table (email, filters, created_at)
- **API**: `POST /api/alerts/subscribe` and `DELETE /api/alerts/{id}`
- **Daily job**: Compare today's new for-sale+subdividable parcels against subscriptions
- **Email delivery**: SendGrid or SES for transactional email
- **Digest format**: HTML email with top new listings, price, lot details, Redfin link
- **Unsubscribe**: One-click unsubscribe link in every email

Estimated effort: 4–6 hours (backend + email integration).

---

## Sewer & Water Main Overlay

Fire hydrants and stormwater layers are done. Remaining utility layers:

| Layer | Service URL | Type |
|-------|-------------|------|
| Sewer Gravity Main | `https://webgis.durhamnc.gov/server/rest/services/CityworksServices/SewerITPIPES/MapServer/1` | Polyline |
| Water Quality | `https://webgis2.durhamnc.gov/server/rest/services/PublicWorksServices/WaterQualityLayers/MapServer` | Points |

### Remaining work
- Query sewer mains via ArcGIS REST within viewport bbox
- Proximity analysis — for each subdividable parcel, compute distance to nearest sewer/water main
- Hookup feasibility badge — "Sewer available" / "Septic likely" based on ~200 ft threshold
- Water main layer may require exploring CityworksServices or submitting data request to PWGIS@durhamnc.gov

Estimated effort: 4–6 hours.

---

## Listing Photo Improvements

Current: og:image scraping from Redfin listing pages (can be slow/blocked).

Potential improvements:
- **RealtyAPI.io** ($20/mo) — aggregates Zillow + Redfin + Realtor.com with photo URLs included
- **Cached proxy endpoint** — `/api/listings/{id}/photo` that fetches and caches listing images server-side
- **Multiple photos** — show a small gallery in the parcel detail panel

---

## Other Potential Features

- **Floodplain overlay** — FEMA data from NC SDD
- **Topography/slope analysis** — steep lots may not be buildable
- **Parcel comparison** — side-by-side comparison of multiple selected parcels
- **Likelihood-to-sell scoring** — via Connected Investors API
- **ADU analysis** — can an accessory dwelling unit be added without subdividing?
- **Multi-jurisdiction** — Raleigh, Wake Forest, Cary (different UDOs, same architecture)
- **RealtyAPI.io integration** — $20/mo for 20K requests, richer listing data (price history, agent info)
