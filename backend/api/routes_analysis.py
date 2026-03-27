from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.schemas import AnalysisStats, ZoningRules, SetbacksSchema
from backend.database import get_db
from backend.udo.rules_engine import get_district_rules

router = APIRouter(tags=["analysis"])


@router.get("/api/analysis/stats", response_model=AnalysisStats)
async def analysis_stats(db: AsyncSession = Depends(get_db)):
    """Summary statistics across all analyzed parcels."""

    total_sql = text("SELECT count(*) FROM parcels")
    total = (await db.execute(total_sql)).scalar_one()

    analyzed_sql = text("SELECT count(*) FROM subdivision_analysis")
    analyzed = (await db.execute(analyzed_sql)).scalar_one()

    subdividable_sql = text(
        "SELECT count(*) FROM subdivision_analysis WHERE is_subdividable = true"
    )
    subdividable = (await db.execute(subdividable_sql)).scalar_one()

    not_subdividable = analyzed - subdividable

    qf_sql = text("""
        SELECT quick_filter_result, count(*)
        FROM subdivision_analysis
        WHERE quick_filter_result IS NOT NULL
        GROUP BY quick_filter_result
    """)
    by_quick_filter = {r[0]: r[1] for r in (await db.execute(qf_sql)).all()}

    st_sql = text("""
        SELECT subdivision_type, count(*)
        FROM subdivision_analysis
        WHERE subdivision_type IS NOT NULL
        GROUP BY subdivision_type
    """)
    by_subdivision_type = {r[0]: r[1] for r in (await db.execute(st_sql)).all()}

    zoning_sql = text("""
        SELECT p.zoning, count(*)
        FROM subdivision_analysis sa
        JOIN parcels p ON p.id = sa.parcel_id
        WHERE sa.is_subdividable = true
        GROUP BY p.zoning
        ORDER BY count(*) DESC
    """)
    by_zoning = {r[0]: r[1] for r in (await db.execute(zoning_sql)).all()}

    return AnalysisStats(
        total_parcels=total,
        total_analyzed=analyzed,
        total_subdividable=subdividable,
        total_not_subdividable=not_subdividable,
        by_quick_filter=by_quick_filter,
        by_subdivision_type=by_subdivision_type,
        by_zoning=by_zoning,
    )


@router.get("/api/zoning-rules/{district}", response_model=ZoningRules)
async def zoning_rules(
    district: str = Path(..., max_length=20, pattern=r"^[A-Za-z0-9\-/]+$"),
):
    """Return UDO dimensional standards for a zoning district."""
    rules = get_district_rules(district)
    if rules is None:
        raise HTTPException(
            status_code=404,
            detail=f"No residential rules found for district '{district}'",
        )

    return ZoningRules(
        zone_code=rules.zone_code,
        full_name=rules.full_name,
        tier=rules.tier,
        min_lot_area_sqft=rules.min_lot_area_sqft,
        min_lot_width_ft=rules.min_lot_width_ft,
        setbacks=SetbacksSchema(
            street_yard_ft=rules.setbacks.street_yard_ft,
            side_yard_ft=rules.setbacks.side_yard_ft,
            rear_yard_ft=rules.setbacks.rear_yard_ft,
        ),
        max_density_per_acre=rules.max_density_per_acre,
        max_height_stories=rules.max_height_stories,
        max_height_ft=rules.max_height_ft,
        allowed_housing_types=rules.allowed_housing_types,
        small_lot_eligible=rules.small_lot_eligible,
        small_lot_urban_only=rules.small_lot_urban_only,
    )
