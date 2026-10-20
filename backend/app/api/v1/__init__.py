"""Version 1 API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import health, schema, sources, workspaces

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(workspaces.router)
api_router.include_router(sources.router)
api_router.include_router(schema.router)
