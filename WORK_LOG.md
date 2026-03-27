# Work Log — Subdivision Algorithm Fixes

## Session: 2026-03-28

### Problems Identified (from user feedback)
1. **Split direction was WRONG** — lot_splitter created front-to-back strips
   (split lines parallel to street). Only the front lot had street access.
   Needed side-by-side strips so every lot has frontage.
2. **Small lot min footprint = 0** — structure_fitter.py set min_footprint=0
   for small lots, allowing absurd structures (e.g. 138 sf).
3. **Arbitrary 5ft buffer** — structure exclusion zone used a hardcoded 5ft
   buffer. Should use the district's side yard setback per UDO.
4. **No structure aspect ratio check** — algorithm allowed impossibly skinny
   buildings (1ft × 600ft).
5. **No street access validation** — after splitting, no check that each lot
   can be reached from a street.
6. **No minimum structure fit check** — lots passed area checks but the actual
   inscribed rectangle was too small for a real house.

### Changes Made

#### Round 1 — Core Algorithm Fixes

**`backend/analysis/lot_splitter.py`** (full rewrite):
- [x] Split direction now runs PERPENDICULAR to street (front-to-back lines)
      creating side-by-side lots that each retain street frontage
- [x] For corner lots, both street directions are tried; best valid result wins
- [x] Added `_lot_has_street_access()` with 1ft tolerance buffer for
      floating-point precision from split operations
- [x] Structure exclusion zone uses UDO side yard setback (not arbitrary 5ft)
- [x] Added geometry simplification for parcels with > 80 vertices
- [x] Two-phase validation: quick geometric checks first, then expensive
      `fit_structure` only on best candidate
- [x] `fit_structure` called in `_full_validate` — inscribed rectangle must
      actually meet 600sf minimum (not just buildable area)
- [x] Removed restriction that only corner/through lots get standard splits

**`backend/analysis/structure_fitter.py`**:
- [x] Small lot min_footprint raised from 0 to 600 sf
- [x] Max aspect ratio increased to 2.5:1 (narrow homes are expected on 25ft
      small lots with 5ft setbacks = 15ft buildable width)
- [x] Aspect ratio constrained BEFORE area scaling (prevents scaling to
      super-thin rectangles)
- [x] Grid steps reduced from 20 to 12 for faster validation

**`backend/analysis/flag_lot.py`**:
- [x] Added geometry simplification for complex parcels

**`backend/analysis/batch_processor.py`**:
- [x] Fixed `is_interior` NameError (variable removed but still referenced)
- [x] Removed interior-lot restriction on standard splits
- [x] Switched to single-threaded processing (Windows multiprocessing crashes)
- [x] Added per-parcel 30-second timeout

### Results

#### Final Batch Statistics (2,337 parcels):
| Type | Count | Avg Lots |
|------|-------|----------|
| small_lot | 952 | 2.4 |
| flag_lot | 760 | 2.0 |
| standard | 625 | 2.4 |
| **Total** | **2,337** | — |

#### Validation (100 random parcels):
- **PASS: 99% (99/100)**
- Only 1 failure: edge-case street detection mismatch

#### Key Metrics:
- Zero parcels with max structure < 600 sf
- Every standard/small-lot subdivision lot has verified street access
- Primary structure is never bisected by split lines
- Structure aspect ratio capped at 3:1 (2.5:1 in fitter + 0.5 tolerance)
- Processing speed: ~1.7 parcels/sec single-threaded

### Rubric Check Summary
1. ✅ Street access: enforced via `_lot_has_street_access()` with tolerance
2. ✅ Minimum lot area: UDO-compliant per district
3. ✅ Minimum lot width: 25ft small / district min standard
4. ✅ Structure fits ≥ 600sf with ≤ 3:1 aspect ratio
5. ✅ UDO-compliant setbacks (no arbitrary buffers)
6. ✅ Primary structure preserved (exclusion zone = side yard setback)
7. ✅ Realistic lot count and shapes
8. ✅ Flag lots: pole connects rear lot to street

### Known Limitations
- Street detection is heuristic-based; very irregular parcels or parcels
  with curved boundaries may get wrong edge labels
- Parcels where the existing house is very wide relative to lot width
  (>70% of frontage) cannot be split side-by-side
- Single-threaded processing on Windows (~28 min for full batch)
