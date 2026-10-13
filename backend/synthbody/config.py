"""Runtime configuration. All knobs are environment-overridable (SYNTHBODY_*)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent.parent
DATA_DIR = PACKAGE_ROOT / "data"
LIBRARY_DIR = DATA_DIR / "library"
DATASET_DIR = DATA_DIR / "datasets"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SYNTHBODY_", env_file=".env", extra="ignore")

    # --- storage -----------------------------------------------------------
    database_url: str = f"sqlite:///{(REPO_ROOT / 'synthbody.db').as_posix()}"

    # --- api ---------------------------------------------------------------
    api_title: str = "SYNTHBODY Simulation API"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ]

    # --- solver defaults ---------------------------------------------------
    default_rtol: float = 1e-8
    default_atol: float = 1e-10
    default_method: str = "LSODA"

    # --- safety rails ------------------------------------------------------
    # Hard caps so a single request cannot wedge the process. Monte Carlo and
    # sensitivity work is CPU-bound and synchronous in the MVP.
    max_simulation_horizon_h: float = 24.0 * 400
    max_output_points: int = 20_000
    max_population_subjects: int = 5_000
    max_sensitivity_samples: int = 65_536

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
