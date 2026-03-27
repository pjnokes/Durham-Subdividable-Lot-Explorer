CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS parcels (
    id SERIAL PRIMARY KEY,
    objectid INTEGER UNIQUE,
    pin VARCHAR(14),
    reid VARCHAR(20),
    zoning VARCHAR(255),
    land_class VARCHAR(50),
    acreage DOUBLE PRECISION,
    calculated_acres DOUBLE PRECISION,
    location_addr VARCHAR(100),
    property_owner VARCHAR(600),
    owner_mail_1 VARCHAR(50),
    owner_mail_2 VARCHAR(50),
    owner_mail_city VARCHAR(50),
    owner_mail_state VARCHAR(20),
    owner_mail_zip VARCHAR(6),
    total_prop_value DOUBLE PRECISION,
    total_land_value DOUBLE PRECISION,
    total_bldg_value DOUBLE PRECISION,
    heated_area INTEGER,
    total_units DOUBLE PRECISION,
    deed_date TIMESTAMP,
    geom GEOMETRY(Geometry, 4326),
    geom_stateplane GEOMETRY(Geometry, 2264),
    area_sqft DOUBLE PRECISION,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parcels_geom ON parcels USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_parcels_geom_sp ON parcels USING GIST (geom_stateplane);
CREATE INDEX IF NOT EXISTS idx_parcels_zoning ON parcels (zoning);
CREATE INDEX IF NOT EXISTS idx_parcels_pin ON parcels (pin);
CREATE INDEX IF NOT EXISTS idx_parcels_addr ON parcels USING gin (location_addr gin_trgm_ops);

CREATE TABLE IF NOT EXISTS zoning_districts (
    id SERIAL PRIMARY KEY,
    zone_code VARCHAR(50),
    zone_name VARCHAR(255),
    geom GEOMETRY(MultiPolygon, 4326),
    geom_stateplane GEOMETRY(MultiPolygon, 2264)
);

CREATE INDEX IF NOT EXISTS idx_zoning_geom ON zoning_districts USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_zoning_code ON zoning_districts (zone_code);

CREATE TABLE IF NOT EXISTS building_footprints (
    id SERIAL PRIMARY KEY,
    area_sqft DOUBLE PRECISION,
    parcel_id INTEGER REFERENCES parcels(id),
    geom GEOMETRY(Polygon, 4326),
    geom_stateplane GEOMETRY(Polygon, 2264)
);

CREATE INDEX IF NOT EXISTS idx_buildings_geom ON building_footprints USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_buildings_parcel ON building_footprints (parcel_id);

CREATE TABLE IF NOT EXISTS subdivision_analysis (
    id SERIAL PRIMARY KEY,
    parcel_id INTEGER REFERENCES parcels(id) UNIQUE,
    is_subdividable BOOLEAN,
    quick_filter_result VARCHAR(50),
    subdivision_type VARCHAR(50),
    num_possible_lots INTEGER,
    min_new_lot_area_sqft DOUBLE PRECISION,
    max_structure_footprint_sqft DOUBLE PRECISION,
    confidence_score DOUBLE PRECISION,
    proposed_lot_lines GEOMETRY(MultiLineString, 4326),
    proposed_lots GEOMETRY(MultiPolygon, 4326),
    proposed_structures GEOMETRY(MultiPolygon, 4326),
    existing_structure_conflict BOOLEAN,
    notes TEXT,
    analyzed_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analysis_parcel ON subdivision_analysis (parcel_id);
CREATE INDEX IF NOT EXISTS idx_analysis_subdividable ON subdivision_analysis (is_subdividable);

CREATE TABLE IF NOT EXISTS utility_lines (
    id SERIAL PRIMARY KEY,
    layer_type VARCHAR(30) NOT NULL,  -- 'fire_hydrant', 'stormwater_pipe', 'stormwater_structure'
    facility_id VARCHAR(50),
    owner VARCHAR(50),
    diameter DOUBLE PRECISION,
    material VARCHAR(50),
    geom GEOMETRY(Geometry, 4326),
    fetched_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_utility_geom ON utility_lines USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_utility_type ON utility_lines (layer_type);

CREATE TABLE IF NOT EXISTS redfin_listings (
    id SERIAL PRIMARY KEY,
    parcel_id INTEGER REFERENCES parcels(id),
    redfin_url TEXT,
    mls_number VARCHAR(50),
    list_price DOUBLE PRECISION,
    property_type VARCHAR(50),
    address VARCHAR(200),
    city VARCHAR(50),
    state VARCHAR(10),
    zip_code VARCHAR(10),
    beds INTEGER,
    baths DOUBLE PRECISION,
    sqft INTEGER,
    lot_size_sqft INTEGER,
    year_built INTEGER,
    days_on_market INTEGER,
    hoa_month DOUBLE PRECISION,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    status VARCHAR(50),
    photo_url TEXT,
    fetched_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_listings_parcel ON redfin_listings (parcel_id);

-- Ensure photo_url column exists (added after initial schema)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'redfin_listings' AND column_name = 'photo_url'
    ) THEN
        ALTER TABLE redfin_listings ADD COLUMN photo_url TEXT;
    END IF;
END $$;
