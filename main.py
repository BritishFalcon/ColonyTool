import os
import time
import csv
import pandas as pd
import numpy as np
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, joinedload
from pydantic import BaseModel
from typing import List, Optional

from sqlalchemy.orm.attributes import flag_modified

from models import Base, System, Project, StationRequirement

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://elite:dangerous@db:5432/colonisation")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def wait_for_db(engine, retries=10, wait=2):
    for i in range(retries):
        try:
            with engine.connect() as connection:
                print("Database is up and ready!")
                return
        except Exception as e:
            print(f"Database not ready, retrying in {wait} seconds... ({i+1}/{retries})")
            time.sleep(wait)
    raise Exception("Database connection failed after multiple retries")

wait_for_db(engine)
Base.metadata.create_all(bind=engine)

# ---------------------
# CSV Update Function (using pandas for cleaning)
# ---------------------
def update_station_requirements():
    session = SessionLocal()
    try:
        df = pd.read_csv("StationRequirements.csv", header=0)
        drop_cols = ['Required Facility In System', 'Construction Points Cost',
                     'Construction Points Reward', 'Pad', 'Facility Economy',
                     'Initial Population Increase', 'Max Population Increase',
                     'System Economy Influence', 'Security', 'Tech Level', 'Wealth',
                     'Standard of Living', 'Development Level', 'Total amount of Commodities',
                     '# Trips with 784 cargo space (L)', '# Trips with 400 cargo space (M)']
        df = df.drop(columns=drop_cols, errors='ignore')
        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
        numeric_columns = df.select_dtypes(include=['float64']).columns
        df[numeric_columns] = df[numeric_columns].replace([np.inf, -np.inf], np.nan).fillna(0).astype(int)
        if df.shape[1] < 7:
            raise Exception("CSV must have at least 7 columns (6 for hierarchy and at least 1 commodity)")
        # First 6 columns are hierarchy; remaining columns are commodity fields.
        hierarchy_keys = list(df.columns[:6])
        commodity_keys = list(df.columns[6:])
        unique_recs = {}
        for _, row in df.iterrows():
            tier = str(row[hierarchy_keys[0]]).strip() if pd.notnull(row[hierarchy_keys[0]]) else ""
            location = str(row[hierarchy_keys[1]]).strip() if pd.notnull(row[hierarchy_keys[1]]) else ""
            category = str(row[hierarchy_keys[2]]).strip() if pd.notnull(row[hierarchy_keys[2]]) else ""
            listed_type = str(row[hierarchy_keys[3]]).strip() if pd.notnull(row[hierarchy_keys[3]]) else ""
            building_type = str(row[hierarchy_keys[4]]).strip() if pd.notnull(row[hierarchy_keys[4]]) else ""
            layout = str(row[hierarchy_keys[5]]).strip() if pd.notnull(row[hierarchy_keys[5]]) else ""
            if not (tier and location and category and listed_type and building_type and layout):
                continue
            commodities = {}
            for key in commodity_keys:
                try:
                    commodities[key] = int(row[key]) if pd.notnull(row[key]) and row[key] != "" else 0
                except ValueError:
                    commodities[key] = 0
            unique_recs[(tier, location, category, listed_type, building_type, layout)] = commodities
        for key, commodities in unique_recs.items():
            tier, location, category, listed_type, building_type, layout = key
            record = session.query(StationRequirement).filter(
                StationRequirement.tier == tier,
                StationRequirement.location == location,
                StationRequirement.category == category,
                StationRequirement.listed_type == listed_type,
                StationRequirement.building_type == building_type,
                StationRequirement.layout == layout
            ).first()
            if not record:
                record = StationRequirement(
                    tier=tier,
                    location=location,
                    category=category,
                    listed_type=listed_type,
                    building_type=building_type,
                    layout=layout,
                    commodities=commodities
                )
                session.add(record)
            else:
                record.commodities = commodities
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

# ---------------------
# Lifespan Handler
# ---------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        update_station_requirements()
        print("Station requirements updated from CSV on startup.")
    except Exception as e:
        print("Error updating station requirements on startup:", e)
    yield

app = FastAPI(title="Elite Dangerous Colonisation API", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------------------
# WebSocket Manager for Real-Time Updates
# ---------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

# ---------------------
# Request Models
# ---------------------
class SystemCreate(BaseModel):
    name: str

class CreateProjectRequest(BaseModel):
    name: str
    system_id: int
    station_requirement_id: Optional[int] = None

class UpdateProgressRequest(BaseModel):
    commodity: str
    remaining: int

# ---------------------
# WebSocket Endpoint
# ---------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ---------------------
# API Endpoints
# ---------------------
@app.get("/", response_class=HTMLResponse)
def serve_index():
    return FileResponse("static/index.html")

@app.get("/systems")
def get_systems():
    session = SessionLocal()
    systems = session.query(System).all()
    session.close()
    return systems

@app.post("/systems")
def create_system(system: SystemCreate):
    session = SessionLocal()
    existing = session.query(System).filter(System.name == system.name).first()
    if existing:
        session.close()
        raise HTTPException(status_code=400, detail="System already exists")
    new_system = System(name=system.name)
    session.add(new_system)
    session.commit()
    session.refresh(new_system)
    session.close()
    return new_system

# GET all projects.
@app.get("/projects")
def list_projects():
    session = SessionLocal()
    projects = session.query(Project).options(joinedload(Project.station_requirement)).all()
    results = []
    for project in projects:
        station_req = None
        if project.station_requirement:
            station_req = {
                "id": project.station_requirement.id,
                "tier": project.station_requirement.tier,
                "location": project.station_requirement.location,
                "category": project.station_requirement.category,
                "listed_type": project.station_requirement.listed_type,
                "building_type": project.station_requirement.building_type,
                "layout": project.station_requirement.layout,
                "commodities": {k: v for k, v in project.station_requirement.commodities.items() if v != 0}
            }
        total_required = 0
        total_remaining = 0
        if station_req and project.progress:
            for commodity, req in station_req["commodities"].items():
                total_required += req
                total_remaining += project.progress.get(commodity, req)
        completion = round(((total_required - total_remaining) / total_required) * 100) if total_required > 0 else 0
        results.append({
            "id": project.id,
            "name": project.name,
            "system_id": project.system_id,
            "station_requirement": station_req,
            "progress": project.progress,
            "completion": completion
        })
    session.close()
    return results

# POST /projects to create a new project.
@app.post("/projects")
def add_project(project_req: CreateProjectRequest):
    session = SessionLocal()
    system = session.query(System).filter(System.id == project_req.system_id).first()
    if not system:
        session.close()
        raise HTTPException(status_code=404, detail="System not found")
    new_project = Project(
        name=project_req.name,
        system_id=project_req.system_id,
        station_requirement_id=project_req.station_requirement_id
    )
    session.add(new_project)
    session.commit()
    session.refresh(new_project)
    if new_project.station_requirement and new_project.station_requirement.commodities:
        new_project.progress = {k: v for k, v in new_project.station_requirement.commodities.items() if v != 0}
        session.commit()
    project_id = new_project.id
    session.close()
    return {"message": "Project added successfully", "project_id": project_id}

# GET a specific project's details.
@app.get("/projects/{project_id}")
def get_project(project_id: int):
    session = SessionLocal()
    project = session.query(Project).options(joinedload(Project.station_requirement)).filter(Project.id == project_id).first()
    if not project:
         session.close()
         raise HTTPException(status_code=404, detail="Project not found")
    station_req = None
    if project.station_requirement:
        station_req = {
            "id": project.station_requirement.id,
            "tier": project.station_requirement.tier,
            "location": project.station_requirement.location,
            "category": project.station_requirement.category,
            "listed_type": project.station_requirement.listed_type,
            "building_type": project.station_requirement.building_type,
            "layout": project.station_requirement.layout,
            "commodities": {k: v for k, v in project.station_requirement.commodities.items() if v != 0}
        }
    result = {
         "id": project.id,
         "name": project.name,
         "system_id": project.system_id,
         "station_requirement": station_req,
         "progress": project.progress
    }
    session.close()
    return result

# DELETE a project.
@app.delete("/projects/{project_id}")
def delete_project(project_id: int):
    session = SessionLocal()
    project = session.query(Project).filter(Project.id == project_id).first()
    if not project:
        session.close()
        raise HTTPException(status_code=404, detail="Project not found")
    session.delete(project)
    session.commit()
    session.close()
    return {"message": "Project deleted successfully"}

# PUT endpoint to update project progress.
@app.put("/project_progress/{project_id}")
async def update_project_progress(project_id: int, payload: UpdateProgressRequest):
    # Payload is validated by UpdateProgressRequest model.
    commodity = payload.commodity
    new_remaining = payload.remaining
    print(f"Updating project {project_id}: setting {commodity} remaining to {new_remaining}")
    session = SessionLocal()
    project = session.query(Project).options(joinedload(Project.station_requirement)).filter(Project.id == project_id).first()
    if not project:
        session.close()
        raise HTTPException(status_code=404, detail="Project not found")
    if project.progress is None:
        project.progress = {}
    project.progress[commodity] = new_remaining
    # Explicitly flag the JSON field as modified.
    flag_modified(project, "progress")
    print(f"Updated progress: {project.progress}")
    session.commit()
    updated_progress = project.progress
    session.close()
    await manager.broadcast(f'{{"type": "update", "project_id": {project_id}}}')
    return {"message": "Project progress updated", "progress": updated_progress}

# GET aggregate system progress.
@app.get("/systems/{system_id}/aggregate")
def aggregate_system_progress(system_id: int):
    session = SessionLocal()
    projects = session.query(Project).options(joinedload(Project.station_requirement)).filter(Project.system_id == system_id).all()
    session.close()
    aggregate = {}
    required_totals = {}
    for proj in projects:
        if proj.station_requirement and proj.station_requirement.commodities and proj.progress:
            for commodity, req in proj.station_requirement.commodities.items():
                if req == 0:
                    continue
                required_totals[commodity] = required_totals.get(commodity, 0) + req
                remaining = proj.progress.get(commodity, req)
                aggregate[commodity] = aggregate.get(commodity, 0) + remaining
    result = {k: aggregate[k] for k in aggregate if required_totals.get(k, 0) > 0 and aggregate[k] > 0}
    return result

# Dependent dropdown endpoint for station requirement levels.
@app.get("/station_requirements/levels")
def get_station_levels(level: int = Query(...), tier: Optional[str] = None, location: Optional[str] = None,
                       category: Optional[str] = None, listed_type: Optional[str] = None,
                       building_type: Optional[str] = None):
    session = SessionLocal()
    query = None
    if level == 1:
        query = session.query(StationRequirement.tier.distinct())
    elif level == 2:
        if not tier:
            session.close()
            raise HTTPException(status_code=400, detail="tier required for level 2 options")
        query = session.query(StationRequirement.location.distinct()).filter(StationRequirement.tier == tier)
    elif level == 3:
        if not (tier and location):
            session.close()
            raise HTTPException(status_code=400, detail="tier and location required for level 3 options")
        query = session.query(StationRequirement.category.distinct()).filter(
            StationRequirement.tier == tier,
            StationRequirement.location == location
        )
    elif level == 4:
        if not (tier and location and category):
            session.close()
            raise HTTPException(status_code=400, detail="tier, location, and category required for level 4 options")
        query = session.query(StationRequirement.listed_type.distinct()).filter(
            StationRequirement.tier == tier,
            StationRequirement.location == location,
            StationRequirement.category == category
        )
    elif level == 5:
        if not (tier and location and category and listed_type):
            session.close()
            raise HTTPException(status_code=400, detail="tier, location, category, and listed_type required for level 5 options")
        query = session.query(StationRequirement.building_type.distinct()).filter(
            StationRequirement.tier == tier,
            StationRequirement.location == location,
            StationRequirement.category == category,
            StationRequirement.listed_type == listed_type
        )
    elif level == 6:
        if not (tier and location and category and listed_type and building_type):
            session.close()
            raise HTTPException(status_code=400, detail="tier, location, category, listed_type, and building_type required for level 6 options")
        query = session.query(StationRequirement.layout.distinct()).filter(
            StationRequirement.tier == tier,
            StationRequirement.location == location,
            StationRequirement.category == category,
            StationRequirement.listed_type == listed_type,
            StationRequirement.building_type == building_type
        )
    else:
        session.close()
        raise HTTPException(status_code=400, detail="Invalid level")
    options = [row[0] for row in query.all()]
    session.close()
    return options

# GET station requirement by 6 levels.
@app.get("/station_requirements")
def get_station_requirement(tier: str, location: str, category: str, listed_type: str, building_type: str, layout: str):
    session = SessionLocal()
    req = session.query(StationRequirement).filter(
        StationRequirement.tier == tier,
        StationRequirement.location == location,
        StationRequirement.category == category,
        StationRequirement.listed_type == listed_type,
        StationRequirement.building_type == building_type,
        StationRequirement.layout == layout
    ).first()
    session.close()
    if not req:
        raise HTTPException(status_code=404, detail="Station requirement not found")
    return {
        "id": req.id,
        "tier": req.tier,
        "location": req.location,
        "category": req.category,
        "listed_type": req.listed_type,
        "building_type": req.building_type,
        "layout": req.layout,
        "commodities": {k: v for k, v in req.commodities.items() if v != 0}
    }

# POST endpoint to update station requirements from CSV.
@app.post("/update_station_requirements")
def update_station_requirements_endpoint():
    session = SessionLocal()
    try:
        with open("StationRequirements.csv", newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            headers = reader.fieldnames
            if not headers or len(headers) < 7:
                raise Exception("CSV must have at least 7 columns (6 for hierarchy and at least 1 commodity)")
            hierarchy_keys = headers[:6]
            commodity_keys = headers[6:]
            unique_recs = {}
            for row in reader:
                tier = row[hierarchy_keys[0]].strip() if row[hierarchy_keys[0]] else ""
                location = row[hierarchy_keys[1]].strip() if row[hierarchy_keys[1]] else ""
                category = row[hierarchy_keys[2]].strip() if row[hierarchy_keys[2]] else ""
                listed_type = row[hierarchy_keys[3]].strip() if row[hierarchy_keys[3]] else ""
                building_type = row[hierarchy_keys[4]].strip() if row[hierarchy_keys[4]] else ""
                layout = row[hierarchy_keys[5]].strip() if row[hierarchy_keys[5]] else ""
                if not (tier and location and category and listed_type and building_type and layout):
                    continue
                commodities = {}
                for key in commodity_keys:
                    try:
                        commodities[key] = int(row[key]) if row[key] not in (None, "") else 0
                    except ValueError:
                        commodities[key] = 0
                unique_recs[(tier, location, category, listed_type, building_type, layout)] = commodities
            for key, commodities in unique_recs.items():
                tier, location, category, listed_type, building_type, layout = key
                record = session.query(StationRequirement).filter(
                    StationRequirement.tier == tier,
                    StationRequirement.location == location,
                    StationRequirement.category == category,
                    StationRequirement.listed_type == listed_type,
                    StationRequirement.building_type == building_type,
                    StationRequirement.layout == layout
                ).first()
                if not record:
                    record = StationRequirement(
                        tier=tier,
                        location=location,
                        category=category,
                        listed_type=listed_type,
                        building_type=building_type,
                        layout=layout,
                        commodities=commodities
                    )
                    session.add(record)
                else:
                    record.commodities = commodities
            session.commit()
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
    return {"message": "Station requirements updated successfully"}
