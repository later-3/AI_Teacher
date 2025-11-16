import logging

from fastapi import FastAPI

from .api.routes import router as api_router
from .api.admin import router as admin_router
from .config import get_settings
from .database import init_db


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app = FastAPI(title="AI Teacher Backend", version="0.1.0")

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(admin_router)
    return app


app = create_app()
