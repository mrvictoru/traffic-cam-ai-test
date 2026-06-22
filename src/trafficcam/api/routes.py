"""Route definitions for the API scaffold."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/cameras")
def list_cameras() -> list[dict]:
    """Return a placeholder list of cameras."""
    return []
