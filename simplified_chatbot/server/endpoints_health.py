"""FastAPI health endpoints for picobot."""

from __future__ import annotations

from fastapi import APIRouter

from simplified_chatbot.server.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return a lightweight health response."""
    return HealthResponse(status="ok")
