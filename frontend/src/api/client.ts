const BASE = "/api";

export interface ParcelGeoJSON {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: GeoJSON.Geometry;
    properties: {
      id: number;
      pin: string;
      address: string;
      zoning: string;
      area_sqft: number;
      property_owner: string;
      total_prop_value: number;
      total_land_value: number | null;
      total_bldg_value: number | null;
      heated_area: number;
      land_class: string | null;
      acreage: number | null;
      quick_filter_result: string;
      is_subdividable: boolean;
      subdivision_type: string | null;
      num_possible_lots: number | null;
      confidence_score: number | null;
      num_street_frontages: number | null;
      is_corner_lot: boolean | null;
      proposed_lots: GeoJSON.Geometry | null;
      proposed_structures: GeoJSON.Geometry | null;
      for_sale: boolean;
      list_price: number | null;
      redfin_url: string | null;
      days_on_market: number | null;
      photo_url: string | null;
    };
  }>;
}

export interface AnalysisStats {
  total_parcels: number;
  total_analyzed: number;
  total_subdividable: number;
  total_not_subdividable: number;
  by_quick_filter: Record<string, number>;
  by_subdivision_type: Record<string, number>;
  by_zoning: Record<string, number>;
}

export interface ListingDetail {
  list_price: number | null;
  redfin_url: string | null;
  mls_number: string | null;
  property_type: string | null;
  beds: number | null;
  baths: number | null;
  sqft: number | null;
  lot_size_sqft: number | null;
  year_built: number | null;
  days_on_market: number | null;
  hoa_month: number | null;
  status: string | null;
  photo_url: string | null;
}

export interface ParcelDetail {
  id: number;
  pin: string;
  reid: string;
  address: string;
  zoning: string;
  land_class: string;
  acreage: number;
  area_sqft: number;
  property_owner: string;
  owner_mail_1: string;
  owner_mail_city: string;
  owner_mail_state: string;
  owner_mail_zip: string;
  total_prop_value: number;
  total_land_value: number;
  total_bldg_value: number;
  heated_area: number;
  analysis: {
    is_subdividable: boolean;
    quick_filter_result: string;
    subdivision_type: string | null;
    num_possible_lots: number | null;
    max_structure_footprint_sqft: number | null;
    confidence_score: number | null;
    existing_structure_conflict: boolean;
    notes: string | null;
    num_street_frontages: number | null;
    is_corner_lot: boolean | null;
  } | null;
  listing: ListingDetail | null;
}

export interface ZoningRules {
  zone_code: string;
  full_name: string;
  tier: string;
  min_lot_area_sqft: number;
  min_lot_width_ft: number;
  setbacks: { street_yard_ft: number; side_yard_ft: number; rear_yard_ft: number };
  max_height_ft: number;
  small_lot_eligible: boolean;
}

export async function fetchParcelsGeoJSON(
  bbox: [number, number, number, number],
  subdividable?: boolean,
  forSale?: boolean,
  includeForSale?: boolean
): Promise<ParcelGeoJSON> {
  const params = new URLSearchParams({
    bbox: bbox.join(","),
  });
  if (subdividable !== undefined) {
    params.set("subdividable", String(subdividable));
  }
  if (forSale !== undefined) {
    params.set("for_sale", String(forSale));
  }
  if (includeForSale !== undefined) {
    params.set("include_for_sale", String(includeForSale));
  }
  const resp = await fetch(`${BASE}/parcels/geojson?${params}`);
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

export async function fetchParcelDetail(id: number): Promise<ParcelDetail> {
  const resp = await fetch(`${BASE}/parcels/${id}`);
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

export async function fetchStats(): Promise<AnalysisStats> {
  const resp = await fetch(`${BASE}/analysis/stats`);
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

export async function fetchZoningRules(district: string): Promise<ZoningRules> {
  const resp = await fetch(`${BASE}/zoning-rules/${encodeURIComponent(district)}`);
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

export interface AddressSearchResult {
  id: number;
  address: string | null;
  pin: string | null;
  zoning: string | null;
  area_sqft: number | null;
  is_subdividable: boolean | null;
  lng: number;
  lat: number;
}

export async function searchAddresses(
  q: string,
  limit = 10
): Promise<AddressSearchResult[]> {
  if (!q.trim()) return [];
  const params = new URLSearchParams({ q, limit: String(limit) });
  const resp = await fetch(`${BASE}/parcels/search?${params}`);
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

export interface ForSaleListing {
  id: number;
  pin: string | null;
  address: string | null;
  zoning: string | null;
  area_sqft: number | null;
  is_subdividable: boolean | null;
  subdivision_type: string | null;
  num_possible_lots: number | null;
  list_price: number | null;
  redfin_url: string | null;
  photo_url: string | null;
  beds: number | null;
  baths: number | null;
  sqft: number | null;
  days_on_market: number | null;
  lng: number;
  lat: number;
}

export interface ForSaleResponse {
  items: ForSaleListing[];
  total: number;
}

export async function fetchForSaleListings(
  subdividableOnly = false
): Promise<ForSaleResponse> {
  const params = new URLSearchParams();
  if (subdividableOnly) params.set("subdividable_only", "true");
  const resp = await fetch(`${BASE}/parcels/for-sale?${params}`);
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

export function getExportCSVUrl(subdividable?: boolean): string {
  const params = new URLSearchParams();
  if (subdividable) params.set("subdividable", "true");
  return `${BASE}/export/csv?${params}`;
}

export interface UtilityGeoJSON {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: GeoJSON.Geometry;
    properties: {
      layer_type: string;
      facility_id: string | null;
      owner: string | null;
      diameter: number | null;
      material: string | null;
    };
  }>;
}

export async function fetchUtilityGeoJSON(
  bbox: [number, number, number, number],
  layerType?: string
): Promise<UtilityGeoJSON> {
  const params = new URLSearchParams({ bbox: bbox.join(",") });
  if (layerType) params.set("layer_type", layerType);
  const resp = await fetch(`${BASE}/utilities/geojson?${params}`);
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}

export async function fetchUtilityStats(): Promise<Record<string, number>> {
  const resp = await fetch(`${BASE}/utilities/stats`);
  if (!resp.ok) throw new Error(`API error: ${resp.status}`);
  return resp.json();
}
