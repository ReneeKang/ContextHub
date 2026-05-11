from fastapi import FastAPI

from app.admin.router import router as admin_router
from app.chat.router import router as chat_router


def create_app() -> FastAPI:
    app = FastAPI(title="ContextHub", version="0.1.0")
    app.include_router(chat_router, prefix="/api/v1/chat", tags=["chat"])
    app.include_router(admin_router, prefix="/api/v1/admin", tags=["admin"])
    return app


app = create_app()
