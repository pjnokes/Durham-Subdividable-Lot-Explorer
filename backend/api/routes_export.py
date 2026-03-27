from __future__ import annotations

import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db

router = APIRouter(prefix="/api/export", tags=["export"])

CSV_COLUMNS = [
    "id",
    "pin",
    "address",
    "zoning",
    "area_sqft",
    "acreage",
    "property_owner",
    "owner_mail_1",
    "owner_mail_2",
    "owner_mail_city",
    "owner_mail_state",
    "owner_mail_zip",
    "total_prop_value",
    "total_land_value",
    "total_bldg_value",
    "heated_area",
    "quick_filter_result",
    "is_subdividable",
    "subdivision_type",
    "num_possible_lots",
    "confidence_score",
]


@router.get("/csv")
async def export_csv(
    zoning: Optional[str] = Query(None, max_length=20, pattern=r"^[A-Za-z0-9\-/ ]+$"),
    subdividable: Optional[bool] = None,
    min_area: Optional[float] = Query(None, ge=0, le=100_000_000),
    max_area: Optional[float] = Query(None, ge=0, le=100_000_000),
    limit: int = Query(10000, ge=1, le=25000),
    db: AsyncSession = Depends(get_db),
):
    """Export filtered parcels as CSV with owner mailing info."""

    clauses: list[str] = ["1=1"]
    params: dict = {"limit": limit}

    if zoning:
        clauses.append("p.zoning ILIKE :zoning")
        params["zoning"] = f"%{zoning}%"
    if subdividable is True:
        clauses.append("sa.is_subdividable = true")
    elif subdividable is False:
        clauses.append("(sa.is_subdividable = false OR sa.id IS NULL)")
    if min_area is not None:
        clauses.append("p.area_sqft >= :min_area")
        params["min_area"] = min_area
    if max_area is not None:
        clauses.append("p.area_sqft <= :max_area")
        params["max_area"] = max_area

    where = " AND ".join(clauses)

    sql = text(f"""
        SELECT
            p.id,
            p.pin,
            p.location_addr AS address,
            p.zoning,
            p.area_sqft,
            p.acreage,
            p.property_owner,
            p.owner_mail_1,
            p.owner_mail_2,
            p.owner_mail_city,
            p.owner_mail_state,
            p.owner_mail_zip,
            p.total_prop_value,
            p.total_land_value,
            p.total_bldg_value,
            p.heated_area,
            sa.quick_filter_result,
            sa.is_subdividable,
            sa.subdivision_type,
            sa.num_possible_lots,
            sa.confidence_score
        FROM parcels p
        LEFT JOIN subdivision_analysis sa ON sa.parcel_id = p.id
        WHERE {where}
        ORDER BY p.id
        LIMIT :limit
    """)

    rows = await db.execute(sql, params)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow(row)

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=durham_parcels_export.csv"},
    )
