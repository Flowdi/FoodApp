from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .jobs import create_scheduler
from .routers import (
    auth,
    catalog,
    events,
    households,
    inventory,
    inventory_sessions,
    notifications,
    receipts,
    recipes,
    shopping,
    voice,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    scheduler = create_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Vorrat API", version="0.5.0", docs_url="/docs", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Household-ID"],
)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(inventory.router, prefix="/api/v1")
app.include_router(catalog.router, prefix="/api/v1")
app.include_router(inventory_sessions.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(households.router, prefix="/api/v1")
app.include_router(events.router, prefix="/api/v1")
app.include_router(recipes.router, prefix="/api/v1")
app.include_router(shopping.router, prefix="/api/v1")
app.include_router(voice.router, prefix="/api/v1")
app.include_router(receipts.router, prefix="/api/v1")


@app.get("/healthz", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}
