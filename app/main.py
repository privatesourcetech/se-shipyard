from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import dashboard, instance_detail

app = FastAPI(title="SE Shipyard")

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

app.include_router(dashboard.router)
app.include_router(instance_detail.router)
