# Subdivision Algorithm — How It Works

This document describes the complete algorithm for determining whether a Durham
residential parcel can be subdivided, and how proposed lot geometries are
generated. Every threshold is either sourced from the Durham UDO or explicitly
marked as a practical assumption.

---

## Table of Contents

1. [High-Level Pipeline](#1-high-level-pipeline)
2. [Step 1: Eligibility Screening](#2-step-1-eligibility-screening)
3. [Step 2: Street Edge Detection](#3-step-2-street-edge-detection)
4. [Step 3: Subdivision Strategies](#4-step-3-subdivision-strategies)
   - [3a: Small Lot Split](#3a-small-lot-split)
   - [3b: Standard Split](#3b-standard-split)
   - [3c: Flag Lot Split](#3c-flag-lot-split)
5. [Step 4: Structure Fitting](#5-step-4-structure-fitting)
6. [Step 5: Real Street Access Validation](#6-step-5-real-street-access-validation)
7. [UDO Rules Reference](#7-udo-rules-reference)
8. [Practical Assumptions (Not from UDO)](#8-practical-assumptions-not-from-udo)
9. [Known Limitations](#9-known-limitations)

---

## 1. High-Level Pipeline

For each parcel in the database, the algorithm runs these steps in order.
If any step fails, the parcel is marked as not subdividable.

```
┌─────────────────────────────────────────────────────────┐
│  1. ELIGIBILITY SCREENING                               │
│     Is this a residential parcel with enough area?      │
│     Does it have a building footprint we can work with? │
│     Is it near a real street?                           │
├─────────────────────────────────────────────────────────┤
│  2. STREET EDGE DETECTION                               │
│     Which edges of the parcel face a street?            │
│     This determines split orientation.                  │
├─────────────────────────────────────────────────────────┤
│  3. TRY SUBDIVISION STRATEGIES (in priority order)      │
│     a) Small lot split (most lots, smallest allowed)    │
│     b) Standard split (district minimums)               │
│     c) Flag lot (rear lot with driveway pole)           │
├─────────────────────────────────────────────────────────┤
│  4. STRUCTURE FITTING                                   │
│     Can a real building fit on each new lot?            │
│     (within setbacks, ≥600 sf, reasonable shape)        │
├─────────────────────────────────────────────────────────┤
│  5. REAL STREET ACCESS VALIDATION                       │
│     Does each proposed lot actually abut a real street  │
│     with enough frontage per UDO?                       │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Step 1: Eligibility Screening

**Source files:** `batch_processor.py`, `rules_engine.py`

Before any geometry is computed, the parcel must pass these gates:

| Check | Criteria | Source |
|-------|----------|--------|
| Residential zoning | Zoning code starts with RS-, RU-, or RC | UDO Art. 6 |
| District rules exist | `udo_rules.json` has rules for the base zone code (after stripping overlays like /PDR, /CU, etc.) | UDO |
| Building footprint | If the parcel has `heated_area > 0` in tax records, it must have a building footprint geometry (real from Microsoft/OSM, or synthetic) | Practical |
| Nearby streets | At least one street centerline segment within 65 ft of the parcel boundary | Durham GIS |

If the parcel has no building footprint but has heated area, we generate a
**synthetic footprint** — a rectangle sized to 65% of the heated area (assuming
~1.5 stories), placed front-center within the buildable envelope.

---

## 3. Step 2: Street Edge Detection

**Source file:** `street_detection.py`

This is a **heuristic** that labels each edge of the parcel polygon as STREET,
SIDE_LEFT, SIDE_RIGHT, or REAR. It determines which direction the lot
"faces" and therefore which direction split lines should run.

### How it works

1. Extract all edges of the parcel polygon with their lengths and compass
   azimuths (0° = North, 90° = East).
2. Group edges by parallel orientation (within ±15° tolerance, mod 180°).
3. Sort groups by total length.
4. **Shortest total-length group** → these are the street/rear edges (the
   "width" of the lot). Within this group, edges **farther from the parcel
   centroid** are labeled STREET; edges **closer** are labeled REAR.
5. **Longest total-length group** → these are the side edges (the "depth"
   of the lot). Left vs. right is determined by cross product relative to
   the street edge midpoint.
6. Unclassified edges (on irregular parcels) get labeled by proximity to
   known street vs. rear edges.

**Output:** A `street_azimuth_deg` that tells the splitter which direction
the street runs. Split lines will be drawn **perpendicular** to this.

### Why heuristic?

The parcel data doesn't explicitly say which edge faces a street. This
heuristic works well for rectangular and near-rectangular lots (the vast
majority in Durham). Irregular parcels may get wrong labels, which is why
real street access is validated separately in Step 5.

---

## 4. Step 3: Subdivision Strategies

**Source files:** `lot_splitter.py`, `flag_lot.py`

Three strategies are tried in priority order. The first one that produces
2+ valid lots wins.

### 3a: Small Lot Split

**UDO source:** Small Lot Option (UDO §6.3)

Tried first because it allows the most lots from a given parcel.

**Eligibility:**
- District must allow small lots (see table in §7 below)
- RS-8 and RS-10 only in Urban Tier
- RS-20 never

**Dimensional requirements (from UDO):**
- Minimum lot area: **2,000 sf**
- Minimum lot width: **25 ft**
- Setbacks: street **10 ft**, side **5 ft**, rear **15 ft**
- Max building footprint: **800 sf**
- Max building total: **1,200 sf**
- Max height: **25 ft**

**How the split works:**

1. Calculate max possible lots: `floor(parcel_area / 2,000)`, capped at 8.
2. Try from max down to 2 lots.
3. For each count, draw split lines **perpendicular to the street direction**
   so each resulting lot retains a strip of street frontage.
4. Split lines are positioned to divide the parcel into roughly equal strips
   along the street-facing axis.
5. Multiple offset positions are tried: 0%, ±3%, ±7%, ±12% of the lot depth
   to find configurations that avoid the existing structure.

### 3b: Standard Split

**UDO source:** Conventional subdivision (UDO §6.3, per district)

Same split mechanics as small lot, but using district-specific minimums:

| District | Min Area (sf) | Min Width (ft) | Street Setback | Side Setback | Rear Setback |
|----------|--------------|----------------|----------------|--------------|--------------|
| RS-20    | 20,000       | 100            | 35             | 12           | 25           |
| RS-10    | 10,000       | 75             | 25             | 10           | 25           |
| RS-8     | 8,000        | 60             | 25             | 9            | 25           |
| RS-M     | 5,000        | 35             | 20             | 5            | 25           |
| RU-5     | 5,000        | 45             | 20             | 5            | 25           |
| RU-5(2)  | 5,000        | 45             | 20             | 5            | 25           |
| RU-M     | 3,500        | 35             | 15             | 5            | 25           |

### How split lines are drawn (both strategies)

```
  STREET (e.g., facing south)
  ┌──────────┬──────────┬──────────┐
  │          │          │          │
  │  Lot A   │  Lot B   │  Lot C   │  ← Each lot has street frontage
  │          │          │          │
  └──────────┴──────────┴──────────┘
        Split lines run front-to-back
        (perpendicular to street)
```

Split lines always run **perpendicular to the street** (i.e., from street edge
toward rear edge). This ensures every resulting lot keeps a portion of the
original street frontage.

For **corner lots** (2+ street edges detected), both street directions are
tried and the configuration producing the best score wins.

### Primary structure protection

The existing primary structure (largest building footprint on the parcel)
must not be bisected by any split line. The algorithm:

1. Projects the primary structure's bounding box onto the split axis.
2. Creates an **exclusion zone** = structure extent ± `2 × side_yard_setback`
   on each side. The doubling accounts for the new lot line needing side
   yard setback on **both** sides (the existing structure's lot and the new lot).
3. If a split position falls within this exclusion zone, it's shifted to the
   nearest edge of the zone. If shifting pushes it outside the parcel, that
   configuration is rejected.

**UDO basis:** Side yard setback per district. The `×2` is correct UDO
application — a new property line requires setback compliance from structures
on both adjacent lots.

### 3c: Flag Lot Split

**UDO source:** Flag Lot standards (UDO §13.5)

Tried when the standard/small lot split doesn't produce 2+ lots (typically
because the lot doesn't have enough width to split side-by-side).

A flag lot creates a front lot (with street frontage) and a rear lot connected
to the street by a narrow "pole" (driveway corridor).

```
  STREET
  ┌────────────────────────┐
  │                        │
  │      FRONT LOT         │
  │   (existing house)     │
  │                        │
  ├────┬───────────────────┤
  │POLE│                   │
  │20ft│    REAR LOT       │
  │wide│   (new house)     │
  │    │                   │
  └────┴───────────────────┘
```

**Dimensional requirements (from UDO):**
- Pole width: **≥ 20 ft** (UDO `flag_lot.min_pole_width_ft`)
- Front lot setback from pole: uses district **side yard** setback
  (UDO: "front setback equals side_yard_setback_of_district")
- Both lots must independently meet district dimensional standards
- Cannot make parent lot nonconforming

**How the flag lot is generated:**

1. Detect street edges (same heuristic as above).
2. Try pole on the **left side**, **right side**, and **center** of the parcel.
3. For each pole position, scan front lot depths from 30% to 80% of the
   parcel depth (in 5% increments).
4. At each depth:
   a. Draw a split line parallel to the street at that depth.
   b. Pieces closer to the street = front lot; farther = rear lot.
   c. Create pole geometry: buffer the side edge (or center line) by the
      pole width, clipped to the parcel.
   d. Subtract the pole from both front and rear lots.
   e. Validate: both lots meet min area, min width, primary structure
      is fully contained in one lot, pole doesn't intersect primary structure.
5. For each valid configuration, fit structures on lots that don't contain
   the primary structure.
6. Keep the configuration with the highest score (lot count × 10 + total area / 1000).

---

## 5. Step 4: Structure Fitting

**Source files:** `structure_fitter.py`, `setback_engine.py`

After lots are proposed, the algorithm verifies that a real building can
actually fit on each new lot (lots containing the existing primary structure
skip this — the house is already there).

### Buildable envelope computation

**Source file:** `setback_engine.py`

1. Label each edge of the proposed lot (STREET, SIDE, REAR) using the
   same street detection heuristic.
2. For each edge, create a setback strip: buffer the edge inward by the
   appropriate setback distance, clipped to the lot boundary.
3. The **buildable envelope** = lot polygon minus all setback strips.

```
  ┌────────────────────────┐
  │ ← street setback       │
  │  ┌──────────────────┐  │
  │  │                  │  │ ← side setback
  │  │  BUILDABLE       │  │
  │  │  ENVELOPE        │  │
  │  │                  │  │
  │  └──────────────────┘  │
  │ ← rear setback         │
  └────────────────────────┘
```

Setback distances come from `udo_rules.json` per district and lot type:
- Standard lots: district conventional setbacks
- Small lots: 10/5/15 ft (street/side/rear)
- Flag lots: side yard used as front setback (per UDO)

### Inscribed rectangle search

**Source file:** `structure_fitter.py`

Within the buildable envelope, find the largest axis-aligned rectangle:

1. Create a 12×12 grid of candidate center points within the envelope bounds.
2. At each center point, binary-search outward along both axes to find the
   maximum width and depth that still fits within the envelope.
3. Constrain aspect ratio to ≤ 2.5:1 during search.
4. If the rectangle exceeds the max allowed area (800 sf for small lots),
   scale it down proportionally.
5. Keep the largest valid rectangle across all grid points.
6. **Pass criteria:** area ≥ 600 sf AND aspect ratio ≤ 3.0.

### Why 600 sf minimum?

**This is a practical assumption, not from the UDO.** The UDO does not
specify a minimum structure footprint for standard lots. However:
- Durham building code requires habitable space minimums
- No builder would construct a single-family home under 600 sf
- The user explicitly rejected 138 sf results as unrealistic

For small lots, the UDO caps the footprint at **800 sf** and total at
**1,200 sf**.

---

## 6. Step 5: Real Street Access Validation

**Source files:** `street_access.py`, `batch_processor.py`

This is the final gate. Even if the geometry looks good, every proposed lot
must physically abut a real public street with sufficient frontage.

### Data source

Street centerline geometry is downloaded from Durham County's `Roads_Clip`
ArcGIS FeatureServer (layer 5). Each segment has:
- Centerline geometry (LineString)
- Pavement width in feet
- Road classification (LOCAL, NC_STATE_RD, US_HIGHWAY, etc.)

### Right-of-way (ROW) computation

The street centerline is in the middle of the road. The property line is at
the edge of the right-of-way. The ROW half-width (centerline to property line)
is computed per road segment:

**If actual pavement width is available** (from ArcGIS data):
```
ROW half-width = pavement_width / 2 + 12 ft
```
The 12 ft accounts for curb (2 ft), utility strip (5 ft), and sidewalk (5 ft)
on one side — per Durham Construction Standard Details, Sheets 401.09–401.11.

**If pavement width is missing or bad data** (e.g., 999 ft sentinel), fall
back to a lookup by road classification:

| Road Type | ROW Half-Width | Based On |
|-----------|---------------|----------|
| LOCAL | 25 ft | Durham std: 50 ft ROW |
| NC_STATE_RD | 30 ft | ~60 ft ROW |
| NC_HIGHWAY | 40 ft | ~80 ft ROW |
| US_HIGHWAY | 45 ft | ~90 ft ROW |
| PRIVATE | 20 ft | ~40 ft ROW |
| ALLEY | 10 ft | ~20 ft ROW |

**Source:** Durham Construction Standard Details (Sheets 401.03–401.16). Local
residential streets have 50 ft ROW with 26-32 ft back-to-back curb width.

An **alignment tolerance of 8 ft** is added to account for GIS data precision,
survey variation, and older neighborhoods with non-standard ROWs.

### Access check

For each proposed lot:
1. Buffer each nearby street centerline by `ROW_half_width + 8 ft`.
2. Union all buffers into a single ROW polygon.
3. Intersect the lot's boundary with the ROW polygon.
4. **Pass criteria:** intersection length ≥ `min_frontage_ft`.

The required `min_frontage_ft` comes from the UDO:
- **Standard lots:** district `min_lot_width_ft` (e.g., RS-10 = 75 ft, RU-5 = 45 ft)
- **Small lots:** 25 ft (UDO small_lot_option.min_lot_width_ft)
- **Flag lot pole:** must intersect the ROW polygon (UDO: pole connects to street)
- **Flag lot front lot:** district `min_lot_width_ft`

Ramps and interstate segments are excluded from the street data.

---

## 7. UDO Rules Reference

All dimensional standards are stored in `backend/udo/udo_rules.json` and
accessed via `backend/udo/rules_engine.py`. The JSON was extracted from
Durham UDO Sections 6.3, 6.4, 7.1, and 13.5.

### Residential districts

| District | Tier | Min Area | Min Width | Street Yard | Side Yard | Rear Yard | Small Lot? |
|----------|------|----------|-----------|-------------|-----------|-----------|------------|
| RS-20 | Suburban | 20,000 sf | 100 ft | 35 ft | 12 ft | 25 ft | No |
| RS-10 | Suburban | 10,000 sf | 75 ft | 25 ft | 10 ft | 25 ft | Urban only |
| RS-8 | Suburban | 8,000 sf | 60 ft | 25 ft | 9 ft | 25 ft | Urban only |
| RS-M | Suburban | 5,000 sf | 35 ft | 20 ft | 5 ft | 25 ft | Yes |
| RU-5 | Urban | 5,000 sf | 45 ft | 20 ft | 5 ft | 25 ft | Yes |
| RU-5(2) | Urban | 5,000 sf | 45 ft | 20 ft | 5 ft | 25 ft | Yes |
| RU-M | Urban | 3,500 sf | 35 ft | 15 ft | 5 ft | 25 ft | Yes |

### Small lot option

| Parameter | Value | UDO Source |
|-----------|-------|------------|
| Min lot area | 2,000 sf | §6.3 |
| Min lot width | 25 ft | §6.3 |
| Street yard setback | 10 ft | §6.3 |
| Side yard setback | 5 ft | §6.3 |
| Rear yard setback | 15 ft | §6.3 |
| Max building footprint | 800 sf | §6.3 |
| Max building total | 1,200 sf | §6.3 |
| Max height | 25 ft | §6.3 |
| Max density | 12 units/acre | §6.3 |

### Flag lot

| Parameter | Value | UDO Source |
|-----------|-------|------------|
| Min pole width | 20 ft | §13.5 |
| Front setback | = district side yard | §13.5 |
| Side lot line angle | 60°–90° to ROW | §13.5 |
| Both lots meet district standards | Required | §13.5 |

### General lot standards

| Rule | Value | UDO Source |
|------|-------|------------|
| Access requirement | Must abut public/private street or allowed driveway | §13.5 |
| No structure violation | Split cannot make existing structure nonconforming | §13.5 |

---

## 8. Practical Assumptions (Not from UDO)

These values are engineering judgments, not UDO requirements. They are
documented here so they can be reviewed and adjusted.

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Min structure footprint | 600 sf | No builder constructs SFD homes under this. Durham building code has habitable space minimums. |
| Max aspect ratio | 3:1 | A 20×180 ft structure is not a viable home. Most houses are between 1:1 and 2:1. |
| Synthetic footprint ratio | 65% of heated area | Assumes ~1.5 stories average for parcels missing real footprint geometry. |
| ROW offset (curb+utility+sidewalk) | 12 ft per side | From Durham Construction Std 401.09: 26ft B-to-B in 50ft ROW → (50-26)/2 = 12ft. |
| Alignment tolerance | 8 ft | Accounts for GIS data precision, survey variation, and older Durham neighborhoods with non-standard ROWs. |
| Max lots to try | 8 | Diminishing returns beyond this; most residential parcels yield 2-4 lots. |
| Split offset sweep | 0%, ±3%, ±7%, ±12% | Empirically covers the range needed to avoid existing structures while keeping lots balanced. |
| Structure exclusion zone | 2× side yard setback | Correct UDO application: new lot line needs side setback from structures on BOTH sides. |

---

## 9. Known Limitations

1. **Street detection is heuristic.** Very irregular parcels, cul-de-sac lots,
   or parcels with curved boundaries may get incorrect edge labels. The real
   street access check in Step 5 catches most errors, but split orientation
   may not be optimal.

2. **Building footprints may be incomplete.** Microsoft Building Footprints
   and OSM don't cover every structure. Synthetic footprints are generated
   for parcels with tax-record heated area but no geometry, but the placement
   is approximate.

3. **Topography is not considered.** Steep slopes, floodplains, and wetlands
   may prevent subdivision in practice. The algorithm only works with 2D
   parcel geometry.

4. **Easements and deed restrictions are not checked.** Utility easements,
   conservation easements, or HOA restrictions could prevent subdivision
   even when the geometry allows it.

5. **Tree preservation is not modeled.** Durham's tree ordinance may require
   preserving significant trees, reducing buildable area.

6. **Only single-family detached is analyzed.** The algorithm doesn't
   consider duplexes, townhouses, or other housing types that some districts
   allow.

7. **Cluster subdivision not implemented.** Some districts allow smaller lots
   in exchange for common open space. This is not currently modeled.

8. **Lot averaging not implemented.** UDO allows up to 15% reduction in
   individual lot area if the average meets the minimum. This would allow
   more subdivisions.

9. **Density cap not enforced.** Some districts have max units per acre.
   The algorithm checks lot minimums but doesn't verify overall density
   compliance.

10. **Single-threaded processing.** The batch runs at ~1.4 parcels/sec on
    Windows. A full rerun of ~900 parcels takes ~11 minutes.
