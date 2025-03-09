import os
import time
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from typing import List, Optional

from models import Base, System, Project, Good, ProjectGood

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

app = FastAPI(title="Elite Dangerous Colonisation API")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------------------
# WebSocket Manager for Real-Time Updates
# ---------------------
from typing import List
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

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Optionally process incoming messages here.
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# ---------------------
# API Endpoints
# ---------------------

# Serve the static HTML dashboard
@app.get("/", response_class=HTMLResponse)
def serve_index():
    return FileResponse("static/index.html")

# GET systems
@app.get("/systems")
def get_systems():
    session = SessionLocal()
    systems = session.query(System).all()
    session.close()
    return systems

# POST system - Create a new system if none exist
class SystemCreate(BaseModel):
    name: str

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

# GET goods
@app.get("/goods")
def get_goods():
    session = SessionLocal()
    goods = session.query(Good).all()
    session.close()
    return goods

# GET all projects
@app.get("/projects")
def get_projects():
    session = SessionLocal()
    projects = session.query(Project).all()
    session.close()
    return projects

# GET a specific project's details (including material requirements)
@app.get("/projects/{project_id}")
def get_project(project_id: int):
    session = SessionLocal()
    project = session.query(Project).filter(Project.id == project_id).first()
    if not project:
         session.close()
         raise HTTPException(status_code=404, detail="Project not found")
    project_data = {
         "id": project.id,
         "name": project.name,
         "system_id": project.system_id,
         "goods": []
    }
    for pg in project.project_goods:
         project_data["goods"].append({
             "id": pg.id,
             "good_id": pg.good_id,
             "required": pg.required,
             "remaining": pg.remaining,
             "good": {"id": pg.good.id, "name": pg.good.name}
         })
    session.close()
    return project_data

# POST project - Create a new project and its material requirements
class Requirement(BaseModel):
    good_id: int
    required: int

class CreateProjectRequest(BaseModel):
    name: str
    system_id: int
    requirements: Optional[List[Requirement]] = []

@app.post("/projects")
def add_project(project_req: CreateProjectRequest):
    session = SessionLocal()
    system = session.query(System).filter(System.id == project_req.system_id).first()
    if not system:
        session.close()
        raise HTTPException(status_code=404, detail="System not found")

    new_project = Project(name=project_req.name, system_id=project_req.system_id)
    session.add(new_project)
    session.commit()  # to assign an ID to new_project
    session.refresh(new_project)

    # Add material requirements (ignoring zeros)
    for req in project_req.requirements:
        if req.required > 0:
            pg = ProjectGood(
                project_id=new_project.id,
                good_id=req.good_id,
                required=req.required,
                remaining=req.required
            )
            session.add(pg)
    session.commit()
    project_id = new_project.id  # grab the id before closing the session
    session.close()
    return {"message": "Project added successfully", "project_id": project_id}

# DELETE project - Remove a project and its requirements
@app.delete("/projects/{project_id}")
def delete_project(project_id: int):
    session = SessionLocal()
    project = session.query(Project).filter(Project.id == project_id).first()
    if not project:
        session.close()
        raise HTTPException(status_code=404, detail="Project not found")
    session.query(ProjectGood).filter(ProjectGood.project_id == project_id).delete()
    session.delete(project)
    session.commit()
    session.close()
    return {"message": "Project deleted successfully"}

@app.get("/systems/{system_id}/aggregate")
def aggregate_system_goods(system_id: int):
    session = SessionLocal()
    results = (
        session.query(
            Good.name,
            func.sum(ProjectGood.required).label("total_required"),
            func.sum(ProjectGood.remaining).label("total_remaining")
        )
        .join(ProjectGood, Good.id == ProjectGood.good_id)
        .join(Project, Project.id == ProjectGood.project_id)
        .filter(Project.system_id == system_id)
        .group_by(Good.name)
        .all()
    )
    session.close()
    if not results:
        raise HTTPException(status_code=404, detail="No aggregated data found for this system")
    # Convert each result row to a dict
    return [
        {"name": row[0], "total_required": row[1], "total_remaining": row[2]}
        for row in results
    ]


# PUT project_good - Update the "remaining" value and broadcast the change
@app.put("/project_goods/{pg_id}")
async def update_project_good(pg_id: int, payload: dict):
    session = SessionLocal()
    pg = session.query(ProjectGood).filter(ProjectGood.id == pg_id).first()
    if not pg:
        session.close()
        raise HTTPException(status_code=404, detail="Project good not found")
    if "remaining" not in payload:
        session.close()
        raise HTTPException(status_code=400, detail="Missing 'remaining' in payload")
    pg.remaining = payload["remaining"]
    session.commit()
    session.refresh(pg)
    session.close()
    await manager.broadcast(f'{{"type": "update", "pg_id": {pg_id}}}')
    return {"message": "Updated", "project_good": {"id": pg_id, "remaining": pg.remaining}}
