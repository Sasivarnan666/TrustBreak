"""/api/dashboard - read-only analyst command-centre aggregates."""

import sqlite3

from fastapi import APIRouter, Depends

from ..database import get_db
from ..schemas import DashboardResponse
from ..services.dashboard import build_dashboard

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
def dashboard(db: sqlite3.Connection = Depends(get_db)):
    return DashboardResponse(data=build_dashboard(db))
