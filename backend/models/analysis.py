from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from backend.database import Base


class SubdivisionAnalysis(Base):
    __tablename__ = "subdivision_analysis"

    id = Column(Integer, primary_key=True)
    parcel_id = Column(Integer, ForeignKey("parcels.id"), unique=True, index=True)
    is_subdividable = Column(Boolean, index=True)
    quick_filter_result = Column(String(50))
    subdivision_type = Column(String(50))
    num_possible_lots = Column(Integer)
    min_new_lot_area_sqft = Column(Double)
    max_structure_footprint_sqft = Column(Double)
    confidence_score = Column(Double)

    proposed_lot_lines = Column(Geometry("MULTILINESTRING", srid=4326))
    proposed_lots = Column(Geometry("MULTIPOLYGON", srid=4326))
    proposed_structures = Column(Geometry("MULTIPOLYGON", srid=4326))

    existing_structure_conflict = Column(Boolean)
    notes = Column(Text)
    num_street_frontages = Column(Integer)
    is_corner_lot = Column(Boolean)
    street_access_notes = Column(Text)
    analyzed_at = Column(DateTime, default=datetime.utcnow, server_default=func.now())

    parcel = relationship("Parcel", back_populates="analysis")
