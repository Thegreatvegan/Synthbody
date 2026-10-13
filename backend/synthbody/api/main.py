"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from synthbody.api.routers import library, simulate, workspace
from synthbody.config import get_settings
from synthbody.db.session import init_db
from synthbody.logging_config import configure_logging, log_event
from synthbody.version import ENGINE_REVISION, SOFTWARE_NAME, SOFTWARE_VERSION

settings = get_settings()
log = logging.getLogger("synthbody.api")

DESCRIPTION = """
SYNTHBODY simulation API.

**Research software, not a medical device.** Every response describes the behaviour of a
mathematical model applied to a hypothetical simulated subject. Nothing returned here is a
diagnosis, a dose recommendation, or a prediction about a real person.

Each model carries a `validation_status`:

* `independently_validated` - compared against observed data that was *not* used to estimate
  its parameters.
* `calibrated_only` - reproduces the data it was fitted to. Weak evidence.
* `structurally_verified` - numerics verified, no clinical comparison performed.
* `research_only` - implemented from published equations, no quantitative comparison.
* `not_validated`.

Each parameter carries an `origin` so a `measured` population value can be told apart from an
`illustrative` default chosen to make the software demonstrable.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.log_level)
    init_db()
    log_event(
        log,
        logging.INFO,
        "SYNTHBODY API starting",
        software_version=SOFTWARE_VERSION,
        engine_revision=ENGINE_REVISION,
        database=settings.database_url.split("///")[-1],
    )
    yield
    log_event(log, logging.INFO, "SYNTHBODY API stopping")


app = FastAPI(
    title=settings.api_title,
    version=SOFTWARE_VERSION,
    description=DESCRIPTION,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "library", "description": "Models, drugs, references, physiology, datasets."},
        {"name": "simulate", "description": "Run deterministic, population and sensitivity analyses."},
        {"name": "workspace", "description": "Patients, experiments, stored runs, validation, reports."},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    rid = uuid.uuid4().hex[:12]
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # pragma: no cover - last-resort handler
        log_event(
            log,
            logging.ERROR,
            "unhandled error",
            request_id=rid,
            path=request.url.path,
            error=f"{type(exc).__name__}: {exc}",
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal error. See server logs.",
                "request_id": rid,
                "error_type": type(exc).__name__,
            },
        )
    dt = time.perf_counter() - t0
    # Simulations are slow by nature; log the ones worth noticing.
    if dt > 1.0 or response.status_code >= 400:
        log_event(
            log,
            logging.INFO if response.status_code < 400 else logging.WARNING,
            "request",
            request_id=rid,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_s=round(dt, 4),
        )
    response.headers["X-Request-ID"] = rid
    response.headers["X-SYNTHBODY-Version"] = SOFTWARE_VERSION
    response.headers["X-SYNTHBODY-Disclaimer"] = "Research software. Not a medical device."
    return response


app.include_router(library.router, prefix="/api")
app.include_router(simulate.router, prefix="/api")
app.include_router(workspace.router, prefix="/api")


@app.get("/health", tags=["library"])
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "software": SOFTWARE_NAME,
        "version": SOFTWARE_VERSION,
        "engine": ENGINE_REVISION,
    }
