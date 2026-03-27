from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ParcelListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pin: Optional[str] = None
    address: Optional[str] = None
    zoning: Optional[str] = None
    area_sqft: Optional[float] = None
    quick_filter_result: Optional[str] = None


class AnalysisDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    is_subdividable: Optional[bool] = None
    quick_filter_result: Optional[str] = None
    subdivision_type: Optional[str] = None
    num_possible_lots: Optional[int] = None
    min_new_lot_area_sqft: Optional[float] = None
    max_structure_footprint_sqft: Optional[float] = None
    confidence_score: Optional[float] = None
    existing_structure_conflict: Optional[bool] = None
    notes: Optional[str] = None
    num_street_frontages: Optional[int] = None
    is_corner_lot: Optional[bool] = None
    analyzed_at: Optional[datetime] = None


class ListingDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    list_price: Optional[float] = None
    redfin_url: Optional[str] = None
    mls_number: Optional[str] = None
    property_type: Optional[str] = None
    beds: Optional[int] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    year_built: Optional[int] = None
    days_on_market: Optional[int] = None
    hoa_month: Optional[float] = None
    status: Optional[str] = None
    photo_url: Optional[str] = None


class ForSaleListItem(BaseModel):
    id: int
    pin: Optional[str] = None
    address: Optional[str] = None
    zoning: Optional[str] = None
    area_sqft: Optional[float] = None
    is_subdividable: Optional[bool] = None
    subdivision_type: Optional[str] = None
    num_possible_lots: Optional[int] = None
    list_price: Optional[float] = None
    redfin_url: Optional[str] = None
    photo_url: Optional[str] = None
    beds: Optional[int] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    days_on_market: Optional[int] = None
    lng: float
    lat: float


class ForSaleResponse(BaseModel):
    items: list[ForSaleListItem]
    total: int


class ParcelDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    objectid: Optional[int] = None
    pin: Optional[str] = None
    reid: Optional[str] = None
    zoning: Optional[str] = None
    land_class: Optional[str] = None
    acreage: Optional[float] = None
    calculated_acres: Optional[float] = None
    address: Optional[str] = Field(None, validation_alias="location_addr")
    property_owner: Optional[str] = None
    owner_mail_1: Optional[str] = None
    owner_mail_2: Optional[str] = None
    owner_mail_city: Optional[str] = None
    owner_mail_state: Optional[str] = None
    owner_mail_zip: Optional[str] = None
    total_prop_value: Optional[float] = None
    total_land_value: Optional[float] = None
    total_bldg_value: Optional[float] = None
    heated_area: Optional[int] = None
    total_units: Optional[float] = None
    deed_date: Optional[datetime] = None
    area_sqft: Optional[float] = None

    analysis: Optional[AnalysisDetail] = None
    listing: Optional[ListingDetail] = None


class AnalysisStats(BaseModel):
    total_parcels: int
    total_analyzed: int
    total_subdividable: int
    total_not_subdividable: int

    by_quick_filter: dict[str, int]
    by_subdivision_type: dict[str, int]
    by_zoning: dict[str, int]


class SetbacksSchema(BaseModel):
    street_yard_ft: float
    side_yard_ft: float
    rear_yard_ft: float


class ZoningRules(BaseModel):
    zone_code: str
    full_name: str
    tier: str
    min_lot_area_sqft: float
    min_lot_width_ft: float
    setbacks: SetbacksSchema
    max_density_per_acre: Optional[float] = None
    max_height_stories: int
    max_height_ft: float
    allowed_housing_types: list[str]
    small_lot_eligible: bool
    small_lot_urban_only: bool


class AddressSearchResult(BaseModel):
    id: int
    address: Optional[str] = None
    pin: Optional[str] = None
    zoning: Optional[str] = None
    area_sqft: Optional[float] = None
    is_subdividable: Optional[bool] = None
    lng: float
    lat: float


class PaginatedResponse(BaseModel):
    items: list[ParcelListItem]
    total: int
    page: int
    page_size: int
    pages: int
