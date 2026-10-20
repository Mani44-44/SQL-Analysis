"""Version 1 API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import auth, health, history, query, schema, sources, workspaces
from app.api import eval as eval_api

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(workspaces.router)
api_router.include_router(sources.router)
api_router.include_router(schema.router)
api_router.include_router(query.router)
api_router.include_router(history.router)
api_router.include_router(eval_api.router)
