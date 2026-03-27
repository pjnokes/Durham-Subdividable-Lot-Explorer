# Subdivision Validation Rubric

Every proposed subdivision must pass ALL of these checks. If any check fails,
the subdivision is invalid and should not be presented to the user.

## Per-Lot Checks (every proposed lot must pass)

### 1. Street Access
- [ ] The lot has direct street frontage (shares a non-trivial edge with the
      parcel's street-facing boundary), OR
- [ ] The lot is a flag lot with a pole of at least 20 ft width connecting
      it to a street
- **Why**: You can't build on a lot you can't drive to

### 2. Minimum Lot Area
- [ ] Standard lots: meets district minimum (e.g. RS-10 = 10,000 sf)
- [ ] Small lots: at least 2,000 sf
- **Source**: UDO Article 6

### 3. Minimum Lot Width
- [ ] Standard lots: meets district minimum (e.g. RS-10 = 75 ft)
- [ ] Small lots: at least 25 ft
- [ ] Width measured along the street frontage, not diagonally
- **Source**: UDO Article 6

### 4. Structure Fits
- [ ] A structure of at least 600 sf footprint fits within setbacks
- [ ] Small lots: structure between 600 sf and 800 sf footprint
- [ ] Structure aspect ratio ≤ 3:1 (no absurdly long skinny buildings)
- [ ] Structure is roughly rectangular (not a sliver)
- **Why**: A 138 sf or 10x1 ft structure is not a real building

### 5. Setbacks (UDO-compliant, no arbitrary buffers)
- [ ] Street yard: per district rules (e.g. RS-10 = 25 ft)
- [ ] Side yard: per district rules (e.g. RS-10 = 10 ft)
- [ ] Rear yard: per district rules (e.g. RS-10 = 25 ft)
- [ ] Small lot setbacks: street=10, side=5, rear=15
- **Source**: UDO Articles 6 and 7

## Parcel-Level Checks

### 6. Primary Structure Preserved
- [ ] The existing primary structure is fully contained within one lot
- [ ] No split line crosses the primary structure
- [ ] Exclusion zone around primary structure uses the district's side yard
      setback (NOT an arbitrary buffer)

### 7. Lot Count is Realistic
- [ ] Number of lots makes physical sense given parcel shape
- [ ] Each lot is roughly rectangular (not bizarre shapes)
- [ ] Total lot area approximately equals original parcel area

### 8. Access Makes Visual Sense
- [ ] If I were driving to each lot, could I actually get there?
- [ ] No lots hidden behind other lots with no road connection
- [ ] For flag lots, the pole connects to an actual street

## Human Sanity Check

When reviewing a subdivision on the map, ask:
1. Does the structure size make sense? (square-ish, at least 600 sf, not a sliver)
2. Can I drive to every lot?
3. Does the existing house stay intact on its lot?
4. Are the lot shapes reasonable? (no super thin strips, no weird slivers)
5. Do the lot sizes make sense for the neighborhood?
6. Are proposed structures oriented sensibly? (aligned with lot, not at crazy angles)
