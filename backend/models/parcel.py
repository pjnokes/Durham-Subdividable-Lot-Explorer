from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    Column,
    Computed,
    DateTime,
    Double,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import relationship

from backend.database import Base


class Parcel(Base):
    __tablename__ = "parcels"

    id = Column(Integer, primary_key=True)
    objectid = Column(Integer, unique=True)
    pin = Column(String(14))
    reid = Column(String(20))
    zoning = Column(String(255), index=True)
    land_class = Column(String(50))
    acreage = Column(Double)
    calculated_acres = Column(Double)
    location_addr = Column(String(100))
    property_owner = Column(String(600))
    owner_mail_1 = Column(String(50))
    owner_mail_2 = Column(String(50))
    owner_mail_city = Column(String(50))
    owner_mail_state = Column(String(20))
    owner_mail_zip = Column(String(6))
    total_prop_value = Column(Double)
    total_land_value = Column(Double)
    total_bldg_value = Column(Double)
    heated_area = Column(Integer)
    total_units = Column(Double)
    deed_date = Column(DateTime)

    geom = Column(Geometry("POLYGON", srid=4326))
    geom_stateplane = Column(Geometry("POLYGON", srid=2264))
    area_sqft = Column(
        Double,
        Computed("ST_Area(geom_stateplane)", persisted=True),
    )
    created_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())

    analysis = relationship(
        "SubdivisionAnalysis",
        back_populates="parcel",
        uselist=False,
        lazy="joined",
    )
