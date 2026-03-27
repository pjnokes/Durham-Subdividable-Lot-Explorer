from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db

router = APIRouter(prefix="/api/utilities", tags=["utilities"])


@router.get("/geojson")
async def utility_lines_geojson(
    bbox: str = Query(
        ...,
        description="minlon,minlat,maxlon,maxlat",
    ),
    layer_type: Optional[str] = Query(
        None,
        max_length=30,
        pattern=r"^[a-z_]+$",
        description="Filter by layer type: sewer_main, sewer_lateral, water_main",
    ),
    limit: int = Query(5000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
):
    """GeoJSON FeatureCollection of utility lines within a bounding box."""
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="bbox must be minlon,minlat,maxlon,maxlat")

    try:
        minlon, minlat, maxlon, maxlat = (float(v) for v in parts)
    except ValueError:
        raise HTTPException(status_code=400, detail="bbox values must be numeric")

    type_clause = ""
    params: dict = {
        "minlon": minlon,
        "minlat": minlat,
        "maxlon": maxlon,
        "maxlat": maxlat,
        "limit": limit,
    }

    if layer_type:
        type_clause = "AND ul.layer_type = :layer_type"
        params["layer_type"] = layer_type

    sql = text(f"""
        SELECT json_build_object(
            'type', 'FeatureCollection',
            'features', COALESCE(json_agg(f.feature), '[]'::json)
        ) AS geojson
        FROM (
            SELECT json_build_object(
                'type', 'Feature',
                'geometry', ST_AsGeoJSON(ul.geom)::json,
                'properties', json_build_object(
                    'layer_type', ul.layer_type,
                    'facility_id', ul.facility_id,
                    'owner', ul.owner,
                    'diameter', ul.diameter,
                    'material', ul.material
                )
            ) AS feature
            FROM utility_lines ul
            WHERE ST_Intersects(
                ul.geom,
                ST_MakeEnvelope(:minlon, :minlat, :maxlon, :maxlat, 4326)
            )
            {type_clause}
            LIMIT :limit
        ) f
    """)

    result = await db.execute(sql, params)
    row = result.scalar_one_or_none()
    if row is None:
        return {"type": "FeatureCollection", "features": []}
    return row


@router.get("/stats")
async def utility_stats(db: AsyncSession = Depends(get_db)):
    """Summary counts of utility lines by type."""
    sql = text("""
        SELECT layer_type, COUNT(*) AS count
        FROM utility_lines
        GROUP BY layer_type
        ORDER BY layer_type
    """)
    result = await db.execute(sql)
    rows = result.all()
    return {r.layer_type: r.count for r in rows}
