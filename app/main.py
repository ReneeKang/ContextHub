from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.admin.router import router as admin_router
from app.chat.router import router as chat_router

POC_STATIC_DIR = Path(__file__).resolve().parent / "static" / "poc"


def create_app() -> FastAPI:
    app = FastAPI(title="ContextHub", version="0.1.0")
    app.include_router(chat_router, prefix="/api/v1/chat", tags=["chat"])
    app.include_router(admin_router, prefix="/api/v1/admin", tags=["admin"])

    app.mount(
        "/static/poc",
        StaticFiles(directory=str(POC_STATIC_DIR)),
        name="poc_static",
    )

    @app.get("/")
    @app.get("/poc")
    async def poc_ui() -> FileResponse:
        """Vanilla JS POC: discover → select documents → generate (same origin as API)."""
        return FileResponse(POC_STATIC_DIR / "index.html", media_type="text/html")

    return app


app = create_app()
