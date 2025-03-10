from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class System(Base):
    __tablename__ = "systems"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    projects = relationship("Project", back_populates="system")


class StationRequirement(Base):
    __tablename__ = "station_requirements"
    id = Column(Integer, primary_key=True, index=True)
    tier = Column(String(100), nullable=False)  # Level 1: Tier
    location = Column(String(100), nullable=False)  # Level 2: Location
    category = Column(String(100), nullable=False)  # Level 3: Category
    listed_type = Column(String(100), nullable=False)  # Level 4: Listed Type
    building_type = Column(String(100), nullable=False)  # Level 5: Building Type
    layout = Column(String(100), nullable=False)  # Level 6: Facility Layouts
    commodities = Column(JSONB)  # Commodity amounts stored as JSON
    __table_args__ = (
        UniqueConstraint("tier", "location", "category", "listed_type", "building_type", "layout",
                         name="uix_station_req"),
    )


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    system_id = Column(Integer, ForeignKey("systems.id"), nullable=False)
    station_requirement_id = Column(Integer, ForeignKey("station_requirements.id"), nullable=True)
    # New fields: 'requirements' holds the user-specified target required amounts;
    # 'progress' holds the current remaining amounts.
    requirements = Column(JSONB)
    progress = Column(JSONB)

    system = relationship("System", back_populates="projects")
    station_requirement = relationship("StationRequirement")
