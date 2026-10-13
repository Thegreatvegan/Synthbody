"""
Provenance: the audit record attached to every simulation.

The white paper's "Regulatory / Certifier Mode" asks for lineage traceability,
deterministic re-execution and content hashing. This module implements the
parts of that which are achievable today: a canonical, hashable description of
exactly what was run, with every parameter tagged by where its value came
from, so a reviewer can tell a measured population mean from a value we chose
to make a demo look reasonable.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from synthbody.version import (
    ENGINE_REVISION,
    PROVENANCE_SCHEMA_VERSION,
    SOFTWARE_NAME,
    SOFTWARE_VERSION,
)


class ParameterOrigin(str, Enum):
    """Where a number came from. This distinction is the whole point.

    Never relabel a value upward (e.g. ILLUSTRATIVE -> MEASURED) to make a
    model look better supported than it is.
    """

    MEASURED = "measured"
    """Directly measured / reported population value from a cited primary source."""

    FITTED = "fitted"
    """Estimated by regression against a named observed dataset inside SYNTHBODY."""

    LITERATURE_FITTED = "literature_fitted"
    """A fitted estimate reported by a cited publication (not re-estimated here)."""

    DERIVED = "derived"
    """Computed from other parameters by an explicit, documented equation."""

    INFERRED = "inferred"
    """Reasoned from related data (e.g. scaled from another species or analogue drug)."""

    ILLUSTRATIVE = "illustrative"
    """A plausible default chosen to make the software demonstrable. NOT evidence."""

    USER = "user"
    """Supplied by the operator at run time."""


class ValidationStatus(str, Enum):
    """How much external checking a model has actually survived."""

    INDEPENDENTLY_VALIDATED = "independently_validated"
    """Compared against observed data that was NOT used to estimate its parameters."""

    CALIBRATED_ONLY = "calibrated_only"
    """Reproduces the dataset its own parameters were fitted to. Weak evidence."""

    STRUCTURALLY_VERIFIED = "structurally_verified"
    """Numerics verified (analytic solution / mass balance) but no clinical comparison."""

    RESEARCH_ONLY = "research_only"
    """Implemented from published equations; no quantitative comparison performed."""

    NOT_VALIDATED = "not_validated"


@dataclass
class ParameterRecord:
    """One parameter, its value, its unit, and its pedigree."""

    name: str
    value: float
    unit: str
    origin: ParameterOrigin
    description: str = ""
    reference_ids: list[str] = field(default_factory=list)
    population_range: tuple[float, float] | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["origin"] = self.origin.value
        d["population_range"] = list(self.population_range) if self.population_range else None
        return d


@dataclass
class SolverDiagnostics:
    """Everything needed to judge whether the numbers can be trusted."""

    method: str
    rtol: float
    atol: float
    success: bool
    message: str
    n_rhs_evaluations: int
    n_jacobian_evaluations: int
    n_lu_decompositions: int
    n_steps_accepted: int
    wall_time_s: float
    # Independent checks run by the engine, not by the solver.
    mass_balance_relative_error: float | None = None
    max_negative_state: float | None = None
    tolerance_refinement_max_rel_diff: float | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProvenanceRecord:
    """The complete, hashable description of a single simulation run."""

    model_id: str
    model_name: str
    model_version: str
    software_name: str = SOFTWARE_NAME
    software_version: str = SOFTWARE_VERSION
    engine_revision: str = ENGINE_REVISION
    schema_version: str = PROVENANCE_SCHEMA_VERSION

    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    python_version: str = field(default_factory=lambda: sys.version.split()[0])
    platform: str = field(default_factory=platform.platform)

    parameters: list[ParameterRecord] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    reference_ids: list[str] = field(default_factory=list)
    validation_status: ValidationStatus = ValidationStatus.NOT_VALIDATED
    validation_summary: str = ""
    solver: SolverDiagnostics | None = None
    random_seed: int | None = None

    # ---------------------------------------------------------------- hashing
    def canonical_payload(self) -> dict[str, Any]:
        """The subset that determines the numerical result.

        Deliberately excludes timestamp, platform and python version so that the
        same science run twice hashes identically (the point of `input_hash`),
        while `record_hash` covers the whole document.

        Parameters contribute only their name, value and unit. Evidence origin,
        description, citations and notes are metadata: they change what a
        reviewer knows about a number, not what the solver computes from it.
        Including them would mean that improving a citation invalidated every
        stored input hash and made the reproducibility check cry wolf. Those
        fields are still covered by `record_hash`, which is what you check when
        you want to know whether the *document* changed.
        """
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "engine_revision": self.engine_revision,
            "parameters": [
                {"name": p.name, "value": p.value, "unit": p.unit} for p in self.parameters
            ],
            "inputs": self.inputs,
            "random_seed": self.random_seed,
        }

    @property
    def input_hash(self) -> str:
        blob = json.dumps(self.canonical_payload(), sort_keys=True, default=str, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d = {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "software_name": self.software_name,
            "software_version": self.software_version,
            "engine_revision": self.engine_revision,
            "schema_version": self.schema_version,
            "timestamp_utc": self.timestamp_utc,
            "python_version": self.python_version,
            "platform": self.platform,
            "parameters": [p.to_dict() for p in self.parameters],
            "inputs": self.inputs,
            "assumptions": self.assumptions,
            "limitations": self.limitations,
            "reference_ids": self.reference_ids,
            "validation_status": self.validation_status.value,
            "validation_summary": self.validation_summary,
            "solver": self.solver.to_dict() if self.solver else None,
            "random_seed": self.random_seed,
            "input_hash": self.input_hash,
        }
        blob = json.dumps(d, sort_keys=True, default=str, separators=(",", ":"))
        d["record_hash"] = "sha256:" + hashlib.sha256(blob.encode()).hexdigest()
        return d
