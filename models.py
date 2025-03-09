from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

class System(Base):
    __tablename__ = "systems"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)

    projects = relationship("Project", back_populates="system")


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    system_id = Column(Integer, ForeignKey("systems.id"), nullable=False)

    system = relationship("System", back_populates="projects")
    project_goods = relationship("ProjectGood", back_populates="project")


class Good(Base):
    __tablename__ = "goods"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)

    project_goods = relationship("ProjectGood", back_populates="good")


class ProjectGood(Base):
    __tablename__ = "project_goods"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    good_id = Column(Integer, ForeignKey("goods.id"), nullable=False)
    required = Column(Integer, nullable=False)
    remaining = Column(Integer, nullable=False)

    project = relationship("Project", back_populates="project_goods")
    good = relationship("Good", back_populates="project_goods")
