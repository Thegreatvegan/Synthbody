"""Simulation, comparison, population and sensitivity endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from synthbody.api.service import (
    ServiceError,
    run_comparison,
    run_population,
    run_sensitivity,
    run_simulation,
)
from synthbody.db.session import get_session
from synthbody.schemas.api import (
    ComparisonRequest,
    ComparisonResponse,
    PopulationRequest,
    PopulationResponse,
    SensitivityRequest,
    SensitivityResponse,
    SimulationRequest,
    SimulationResponse,
)

router = APIRouter(tags=["simulate"])


@router.post("/simulate", response_model=SimulationResponse)
def simulate_endpoint(
    req: SimulationRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        return run_simulation(req, session)
    except ServiceError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"{type(exc).__name__}: {exc}") from exc


@router.post("/simulate/compare", response_model=ComparisonResponse)
def compare_endpoint(
    req: ComparisonRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        return run_comparison(req, session)
    except ServiceError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"{type(exc).__name__}: {exc}") from exc


@router.post("/simulate/population", response_model=PopulationResponse)
def population_endpoint(
    req: PopulationRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        return run_population(req, session)
    except ServiceError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"{type(exc).__name__}: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/simulate/sensitivity", response_model=SensitivityResponse)
def sensitivity_endpoint(
    req: SensitivityRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    try:
        return run_sensitivity(req, session)
    except ServiceError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        # SALib missing, for example.
        raise HTTPException(501, str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, f"{type(exc).__name__}: {exc}") from exc
