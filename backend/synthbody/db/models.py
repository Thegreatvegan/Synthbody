"""
Persistence schema.

Design notes:
  * A simulation row stores its full provenance record and its result payload as
    JSON. Numerical trajectories are not relational data and forcing them into
    tables buys nothing; what matters is that the provenance travels with them.
  * `input_hash` is indexed so an identical re-run can be recognised.
  * Experiments group simulations so scenarios can be compared and reproduced.
  * Nothing here stores identifiable patient data. Virtual patients are
    explicitly flagged synthetic and the column is non-nullable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class VirtualPatientRow(Base):
    """A hypothetical simulated subject. Never a real person.

    `is_synthetic` is non-nullable and defaults to True. The API refuses to
    create a row with it set False, so no code path can quietly store something
    claiming to be a real patient record.
    """

    __tablename__ = "virtual_patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    age_years: Mapped[float] = mapped_column(Float, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    height_cm: Mapped[float] = mapped_column(Float, nullable=False)
    sex: Mapped[str] = mapped_column(String(16), nullable=False)
    serum_creatinine_mg_dL: Mapped[float] = mapped_column(Float, nullable=False)
    albumin_g_dL: Mapped[float] = mapped_column(Float, nullable=False)
    hepatic_function: Mapped[str] = mapped_column(String(32), nullable=False)
    smoking_status: Mapped[str] = mapped_column(String(32), nullable=False)

    derived: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    simulations: Mapped[list["SimulationRow"]] = relationship(
        back_populates="patient", cascade="save-update"
    )


class ExperimentRow(Base):
    """A named container grouping simulations for comparison and reproduction."""

    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    simulations: Mapped[list["SimulationRow"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class SimulationRow(Base):
    """One executed simulation, with everything needed to re-run it."""

    __tablename__ = "simulations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int | None] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=True
    )
    patient_id: Mapped[int | None] = mapped_column(
        ForeignKey("virtual_patients.id"), nullable=True
    )

    label: Mapped[str] = mapped_column(String(200), nullable=False)
    model_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    drug_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="deterministic")

    # The complete request, sufficient to reproduce the run byte-for-byte.
    request: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    input_hash: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    record_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False)
    software_version: Mapped[str] = mapped_column(String(40), nullable=False)
    engine_revision: Mapped[str] = mapped_column(String(60), nullable=False)

    solver_success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    solver_warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wall_time_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    experiment: Mapped["ExperimentRow | None"] = relationship(back_populates="simulations")
    patient: Mapped["VirtualPatientRow | None"] = relationship(back_populates="simulations")

    __table_args__ = (
        Index("ix_simulations_experiment_created", "experiment_id", "created_at"),
    )


class AuditLogRow(Base):
    """Append-only record of actions that change stored state.

    Not a security control on its own. It exists so a reviewer can reconstruct
    what was run and when, which is the part of the white paper's lineage
    requirement that is achievable without a notarisation service.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    software_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
