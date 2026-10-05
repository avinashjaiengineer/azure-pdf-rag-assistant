"""FastAPI entry point.

Run locally:
    uvicorn src.api.main:app --reload
Docs at http://localhost:8000/docs
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routes import router
from src.api.services import Services, build_services
from src.config.settings import get_settings


def create_app(services: Services | None = None) -> FastAPI:
    """Pass `services` to inject fakes (tests); otherwise backends are built from settings at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = services or build_services(get_settings())
        yield

    app = FastAPI(
        title="Azure PDF RAG Assistant",
        description="Upload PDFs and ask questions answered from them, with page citations.",
        version="0.5.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
