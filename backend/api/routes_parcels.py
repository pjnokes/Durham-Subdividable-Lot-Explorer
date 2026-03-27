from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.schemas import (
    AddressSearchResult,
    ForSaleListItem,
    ForSaleResponse,
    ListingDetail,
    PaginatedResponse,
    ParcelDetail,
    ParcelListItem,
)
from backend.database import get_db
from backend.models.analysis import SubdivisionAnalysis
from backend.models.parcel import Parcel

router = APIRouter(prefix="/api/parcels", tags=["parcels"])


@router.get("", response_model=PaginatedResponse)
async def list_parcels(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    zoning: Optional[str] = Query(None, max_length=20, pattern=r"^[A-Za-z0-9\-/ ]+$"),
    subdividable: Optional[bool] = None,
    min_area: Optional[float] = Query(None, ge=0, le=100_000_000),
    max_area: Optional[float] = Query(None, ge=0, le=100_000_000),
    db: AsyncSession = Depends(get_db),
):
    """Paginated parcel list with optional filters."""

    clauses: list[str] = ["1=1"]
    params: dict = {}

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

    count_sql = text(f"""
        SELECT count(*)
        FROM parcels p
        LEFT JOIN subdivision_analysis sa ON sa.parcel_id = p.id
        WHERE {where}
    """)
    result = await db.execute(count_sql, params)
    total = result.scalar_one()

    offset = (page - 1) * page_size
    params["limit"] = page_size
    params["offset"] = offset

    data_sql = text(f"""
        SELECT
            p.id,
            p.pin,
            p.location_addr AS address,
            p.zoning,
            p.area_sqft,
            sa.quick_filter_result
        FROM parcels p
        LEFT JOIN subdivision_analysis sa ON sa.parcel_id = p.id
        WHERE {where}
        ORDER BY p.id
        LIMIT :limit OFFSET :offset
    """)
    rows = await db.execute(data_sql, params)
    items = [
        ParcelListItem(
            id=r.id,
            pin=r.pin,
            address=r.address,
            zoning=r.zoning,
            area_sqft=r.area_sqft,
            quick_filter_result=r.quick_filter_result,
        )
        for r in rows
    ]

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


@router.get("/geojson")
async def parcels_geojson(
    bbox: str = Query(
        ...,
        description="minlon,minlat,maxlon,maxlat",
        examples=["−78.95,35.95,−78.85,36.05"],
    ),
    subdividable: Optional[bool] = None,
    zoning: Optional[str] = Query(None, max_length=20, pattern=r"^[A-Za-z0-9\-/ ]+$"),
    for_sale: Optional[bool] = None,
    include_for_sale: Optional[bool] = None,
    limit: int = Query(5000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
):
    """
    GeoJSON FeatureCollection for the map viewport.
    Uses raw SQL + PostGIS ST_Intersects for performance.
    """
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="bbox must be minlon,minlat,maxlon,maxlat")

    try:
        minlon, minlat, maxlon, maxlat = (float(v) for v in parts)
    except ValueError:
        raise HTTPException(status_code=400, detail="bbox values must be numeric")

    extra_clauses: list[str] = []
    params: dict = {
        "minlon": minlon,
        "minlat": minlat,
        "maxlon": maxlon,
        "maxlat": maxlat,
        "limit": limit,
    }

    if subdividable is True and include_for_sale is True:
        extra_clauses.append("(sa.is_subdividable = true OR rl.id IS NOT NULL)")
    elif subdividable is True:
        extra_clauses.append("sa.is_subdividable = true")
    elif subdividable is False:
        extra_clauses.append("(sa.is_subdividable = false OR sa.id IS NULL)")

    if zoning:
        extra_clauses.append("p.zoning ILIKE :zoning")
        params["zoning"] = f"%{zoning}%"

    if for_sale is True:
        extra_clauses.append("rl.id IS NOT NULL")

    extra_where = (" AND " + " AND ".join(extra_clauses)) if extra_clauses else ""

    sql = text(f"""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(f.feature), '[]'::json)
        ) AS geojson
        FROM (
            SELECT json_build_object(
                'type', 'Feature',
                'id', p.id,
                'geometry', ST_AsGeoJSON(p.geom)::json,
                'properties', json_build_object(
                    'id', p.id,
                    'pin', p.pin,
                    'address', p.location_addr,
                    'zoning', p.zoning,
                    'area_sqft', p.area_sqft,
                    'property_owner', p.property_owner,
                    'total_prop_value', p.total_prop_value,
                    'total_land_value', p.total_land_value,
                    'total_bldg_value', p.total_bldg_value,
                    'heated_area', p.heated_area,
                    'land_class', p.land_class,
                    'acreage', p.acreage,
                    'quick_filter_result', sa.quick_filter_result,
                    'is_subdividable', sa.is_subdividable,
                    'subdivision_type', sa.subdivision_type,
                    'num_possible_lots', sa.num_possible_lots,
                    'confidence_score', sa.confidence_score,
                    'num_street_frontages', sa.num_street_frontages,
                    'is_corner_lot', sa.is_corner_lot,
                    'proposed_lots', ST_AsGeoJSON(sa.proposed_lots)::json,
                    'proposed_structures', ST_AsGeoJSON(sa.proposed_structures)::json,
                    'for_sale', (rl.id IS NOT NULL),
                    'list_price', rl.list_price,
                    'redfin_url', rl.redfin_url,
                    'days_on_market', rl.days_on_market,
                    'photo_url', rl.photo_url
                )
            ) AS feature
            FROM parcels p
            LEFT JOIN subdivision_analysis sa ON sa.parcel_id = p.id
            LEFT JOIN redfin_listings rl ON rl.parcel_id = p.id AND rl.status = 'Active'
            WHERE ST_Intersects(
                p.geom,
                ST_MakeEnvelope(:minlon, :minlat, :maxlon, :maxlat, 4326)
            )
            {extra_where}
            LIMIT :limit
        ) f
    """)

    result = await db.execute(sql, params)
    row = result.scalar_one_or_none()
    if row is None:
        return {"type": "FeatureCollection", "features": []}
    return row


@router.get("/search", response_model=list[AddressSearchResult])
async def search_addresses(
    q: str = Query("", min_length=3, max_length=200, description="Address search text"),
    limit: int = Query(10, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Autocomplete address search across all parcels."""
    sql = text("""
        SELECT
            p.id,
            p.location_addr AS address,
            p.pin,
            p.zoning,
            p.area_sqft,
            sa.is_subdividable,
            ST_X(ST_Centroid(p.geom)) AS lng,
            ST_Y(ST_Centroid(p.geom)) AS lat
        FROM parcels p
        LEFT JOIN subdivision_analysis sa ON sa.parcel_id = p.id
        WHERE p.location_addr ILIKE :q
          AND p.geom IS NOT NULL
        ORDER BY
            p.location_addr ILIKE :q_prefix DESC,
            p.location_addr
        LIMIT :limit
    """)
    result = await db.execute(sql, {
        "q": f"%{q}%",
        "q_prefix": f"{q}%",
        "limit": limit,
    })
    return [
        AddressSearchResult(
            id=r.id,
            address=r.address,
            pin=r.pin,
            zoning=r.zoning,
            area_sqft=r.area_sqft,
            is_subdividable=r.is_subdividable,
            lng=r.lng,
            lat=r.lat,
        )
        for r in result
    ]


@router.get("/for-sale", response_model=ForSaleResponse)
async def list_for_sale(
    subdividable_only: bool = Query(False),
    limit: int = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
):
    """Active for-sale listings with parcel and analysis data."""
    extra = "AND sa.is_subdividable = true" if subdividable_only else ""
    sql = text(f"""
        SELECT
            p.id, p.pin, p.location_addr AS address, p.zoning, p.area_sqft,
            sa.is_subdividable, sa.subdivision_type, sa.num_possible_lots,
            rl.list_price, rl.redfin_url, rl.photo_url,
            rl.beds, rl.baths, rl.sqft, rl.days_on_market,
            ST_X(ST_Centroid(p.geom)) AS lng,
            ST_Y(ST_Centroid(p.geom)) AS lat
        FROM redfin_listings rl
        JOIN parcels p ON p.id = rl.parcel_id
        LEFT JOIN subdivision_analysis sa ON sa.parcel_id = p.id
        WHERE rl.status = 'Active'
          AND rl.parcel_id IS NOT NULL
          {extra}
        ORDER BY
            sa.is_subdividable DESC NULLS LAST,
            rl.list_price ASC NULLS LAST
        LIMIT :limit
    """)
    result = await db.execute(sql, {"limit": limit})
    rows = result.fetchall()
    items = [
        ForSaleListItem(
            id=r.id,
            pin=r.pin,
            address=r.address,
            zoning=r.zoning,
            area_sqft=r.area_sqft,
            is_subdividable=r.is_subdividable,
            subdivision_type=r.subdivision_type,
            num_possible_lots=r.num_possible_lots,
            list_price=r.list_price,
            redfin_url=r.redfin_url,
            photo_url=r.photo_url,
            beds=r.beds,
            baths=r.baths,
            sqft=r.sqft,
            days_on_market=r.days_on_market,
            lng=r.lng,
            lat=r.lat,
        )
        for r in rows
    ]
    return ForSaleResponse(items=items, total=len(items))


@router.get("/{parcel_id}", response_model=ParcelDetail)
async def get_parcel(
    parcel_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Full parcel detail with analysis + listing results."""
    stmt = (
        select(Parcel)
        .outerjoin(SubdivisionAnalysis, SubdivisionAnalysis.parcel_id == Parcel.id)
        .where(Parcel.id == parcel_id)
    )
    result = await db.execute(stmt)
    parcel = result.scalars().first()
    if parcel is None:
        raise HTTPException(status_code=404, detail="Parcel not found")

    listing_sql = text("""
        SELECT list_price, redfin_url, mls_number, property_type,
               beds, baths, sqft, lot_size_sqft, year_built,
               days_on_market, hoa_month, status, photo_url
        FROM redfin_listings
        WHERE parcel_id = :pid AND status = 'Active'
        LIMIT 1
    """)
    listing_result = await db.execute(listing_sql, {"pid": parcel_id})
    listing_row = listing_result.mappings().first()

    detail = ParcelDetail.model_validate(parcel)
    if listing_row:
        detail.listing = ListingDetail(**listing_row)

    return detail
