"""GET /scan — thin HTTP wrapper around services.scan_service.scan_universe."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.scan_service import scan_universe

router = APIRouter()


@router.get("")
async def scan(
    budget: float = Query(500, ge=100, le=100_000, description="Portfolio capital in USD"),
    limit: int = Query(30, ge=1, le=100),
    include_weak: bool = Query(False),
    db: Session = Depends(get_db),
):
    return scan_universe(db, budget=budget, include_weak=include_weak, limit=limit)
