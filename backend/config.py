from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    database_url_sync: str

    arcgis_parcels_url: str = (
        "https://services2.arcgis.com/G5vR3cOjh6g2Ed8E/arcgis/rest/services/"
        "Parcels_NEW/FeatureServer/0"
    )
    arcgis_zoning_url: str = (
        "https://webgis2.durhamnc.gov/server/rest/services/"
        "PublicServices/Planning/MapServer/12"
    )
    nc_sdd_buildings_url: str = (
        "https://sdd.nc.gov/DownloadFiles.aspx?path=BuildingFootprintsbyCounty/2021"
    )
    udo_base_url: str = "https://udo.durhamnc.gov/udo"

    arcgis_page_size: int = 2000
    min_structure_footprint_sqft: float = 600.0
    small_lot_max_footprint_sqft: float = 800.0
    small_lot_max_total_sqft: float = 1200.0
    small_lot_max_height_ft: float = 25.0

    model_config = {"env_file": ".env", "env_prefix": "DURHAM_"}


settings = Settings()
