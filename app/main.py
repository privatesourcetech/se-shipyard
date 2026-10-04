from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.routes import api

STATIC_DIR = Path(__file__).parent / "static"


class RevalidatingStaticFiles(StaticFiles):
    """Always revalidate (ETag -> 304), so a redeploy is never masked by a stale browser cache."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app = FastAPI(title="SE Shipyard")
app.include_router(api.router)
app.mount("/static", RevalidatingStaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    # Version the script URL by file mtime so a changed app.js is always refetched.
    version = int((STATIC_DIR / "app.js").stat().st_mtime)
    html = (STATIC_DIR / "index.html").read_text().replace("__V__", str(version))
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
