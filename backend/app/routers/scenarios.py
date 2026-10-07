"""/api/scenarios - synthetic demo scenarios that run through the REAL incident + risk pipeline."""

import sqlite3

from fastapi import APIRouter, Depends, Path

from .. import repository, risk_repository
from ..database import get_db
from ..errors import NotFoundError
from ..schemas import IncidentCreate, ScenarioListResponse, ScenarioLoadOut, ScenarioLoadResponse, ScenarioOut
from ..services import scenarios as scenario_service
from ..services.attachment_analysis import AttachmentError
from ..services.risk_correlation import assess_incident_risk

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


@router.get("", response_model=ScenarioListResponse)
def list_scenarios():
    """The synthetic scenarios (inputs only - no expected scores; those come from the engine when loaded)."""
    return ScenarioListResponse(data=[ScenarioOut(**s.to_public()) for s in scenario_service.SCENARIOS])


@router.post("/{scenario_id}/load", response_model=ScenarioLoadResponse)
def load_scenario(scenario_id: str = Path(max_length=80), db: sqlite3.Connection = Depends(get_db)):
    """Create a labelled SYNTHETIC incident and run the normal risk pipeline on it (nothing is faked or hardcoded).

    The synthetic archive (if any) is built in memory, analysed statically and discarded: never executed or stored.
    """
    scenario = scenario_service.get_scenario(scenario_id)
    if scenario is None:
        raise NotFoundError(f"Scenario '{scenario_id}' was not found.")
    incident = repository.create_incident(db, IncidentCreate(**scenario.incident_payload()), scenario_id=scenario.id)
    attachment = None
    if scenario.attachment_name:
        attachment = (scenario.attachment_name, scenario.attachment_bytes(), "application/zip")
    persisted, assessment = False, None
    try:
        result = assess_incident_risk(incident, attachment)
        payload = result.to_dict()
        if payload["inputs"].get("message", {}).get("status") != "unavailable":
            risk_repository.check_result_consistent(payload)
            assessment = risk_repository.save_risk_assessment(db, incident.id, payload)
            persisted = True
    except AttachmentError:  # synthetic archives are well-formed; never surface a 500 for a demo load
        persisted = False
    return ScenarioLoadResponse(data=ScenarioLoadOut(
        scenario_id=scenario.id, incident_id=incident.id, reference=incident.reference, synthetic=True,
        assessment_persisted=persisted,
        risk_score=assessment.risk_score if assessment else None, risk_level=assessment.risk_level if assessment else None,
        recommended_action=assessment.recommended_action if assessment else None,
    ))
