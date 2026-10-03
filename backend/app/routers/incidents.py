"""/api/incidents endpoints. Thin: validation in schemas, SQL in repository."""

import sqlite3

from fastapi import APIRouter, Depends, Path, Query, status

from .. import repository
from ..database import get_db
from ..errors import NotFoundError
from ..schemas import (
    IncidentCreate,
    IncidentListMeta,
    IncidentListResponse,
    IncidentResponse,
)

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

SQLITE_MAX_INT = 9_223_372_036_854_775_807


@router.post("", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
def create_incident(payload: IncidentCreate, db: sqlite3.Connection = Depends(get_db)):
    incident = repository.create_incident(db, payload)
    return IncidentResponse(data=incident)


@router.get("", response_model=IncidentListResponse)
def list_incidents(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    items = repository.list_incidents(db, limit=limit, offset=offset)
    total = repository.count_incidents(db)
    return IncidentListResponse(
        data=items,
        meta=IncidentListMeta(total=total, count=len(items), limit=limit, offset=offset),
    )


@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(
    incident_id: int = Path(ge=1, le=SQLITE_MAX_INT),
    db: sqlite3.Connection = Depends(get_db),
):
    incident = repository.get_incident(db, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    return IncidentResponse(data=incident)
