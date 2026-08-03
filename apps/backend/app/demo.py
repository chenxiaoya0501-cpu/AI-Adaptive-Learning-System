from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.main import app


APPS_DIR = Path(__file__).resolve().parents[2]
STUDENT_DIST = APPS_DIR / "frontend" / "student" / "dist"
ADMIN_DIST = APPS_DIR / "frontend" / "admin" / "dist"


def _require_file(path: Path) -> Path:
    if not path.is_file():
        raise HTTPException(status_code=503, detail="Frontend has not been built")
    return path


if (STUDENT_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STUDENT_DIST / "assets"), name="student-assets")

if (ADMIN_DIST / "assets").is_dir():
    app.mount("/admin/assets", StaticFiles(directory=ADMIN_DIST / "assets"), name="admin-assets")


@app.get("/admin", include_in_schema=False)
@app.get("/admin/{path:path}", include_in_schema=False)
async def admin_spa(path: str = ""):
    return FileResponse(_require_file(ADMIN_DIST / "index.html"))


@app.get("/", include_in_schema=False)
@app.get("/{path:path}", include_in_schema=False)
async def student_spa(path: str = ""):
    requested = STUDENT_DIST / path
    if path and requested.is_file() and STUDENT_DIST in requested.resolve().parents:
        return FileResponse(requested)
    return FileResponse(_require_file(STUDENT_DIST / "index.html"))
