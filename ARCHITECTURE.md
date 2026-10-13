# SYNTHBODY — Software Architecture

**Version** 0.1.0 · **Engine revision** `engine-2026.10.12b`

---

## 1. The shape of the system

```
┌──────────────────────────────────────────────────────────────┐
│  Frontend — React 18 + TypeScript + Vite + Tailwind          │
│  8 workspaces · custom SVG plotting engine · zustand store   │
└───────────────────────────┬──────────────────────────────────┘
                            │ typed REST (OpenAPI), JSON
┌───────────────────────────▼──────────────────────────────────┐
│  API — FastAPI + Pydantic v2                                 │
│  routers: library · simulate · workspace                     │
│  service layer: parameter resolution, covariates, provenance │
└───────────────────────────┬──────────────────────────────────┘
                            │
      ┌─────────────────────┴──────────────────────┐
      │                                            │
┌─────▼────────────────────────────┐   ┌───────────▼─────────────┐
│  Engine — NumPy / SciPy / SALib  │   │  Persistence            │
│  imports NOTHING from api or db  │   │  SQLAlchemy 2 + SQLite  │
│                                   │   │  (PostgreSQL optional)  │
│  core        ODE integration      │   │                         │
│  units       unit safety          │   │  virtual_patients       │
│  provenance  origins, hashing     │   │  experiments            │
│  registry    model/drug catalogue │   │  simulations (JSON)     │
│  models/     PK, PBPK, PD         │   │  audit_log              │
│  physiology/ reference man, Kp    │   └─────────────────────────┘
│  analysis/   NCA, metrics, SA,    │
│              population, fitting, │   ┌─────────────────────────┐
│              datasets, validation │   │  Data library (JSON)    │
└───────────────────────────────────┘   │  drugs · references ·   │
                                        │  reference physiology · │
                                        │  observed datasets (CSV)│
                                        └─────────────────────────┘
```

**The one architectural rule that matters:** `synthbody.engine` imports nothing
from `synthbody.api` or `synthbody.db`. That is what lets 150 of the 199 tests
exercise the numerics with no web server, no database and no fixtures — and it
is what would let the engine be lifted into a notebook or a batch pipeline
unchanged.

---

## 2. Technology choices, and why

| Choice | Reason |
| --- | --- |
| **Python + SciPy** for the engine | `solve_ivp` gives production-grade adaptive integrators (LSODA, BDF, Radau, RK45, DOP853) with event handling. Re-implementing them would be strictly worse. SciPy is also what the pharmacometrics community reads. |
| **FastAPI + Pydantic v2** | Request validation at the boundary means a malformed request never reaches the solver, and the generated OpenAPI schema is accurate enough that the frontend can be written against it. `extra="forbid"` on every input model catches typos rather than silently ignoring them. |
| **SQLAlchemy + SQLite** | A research tool should run from a clone with no database server. Trajectories are stored as JSON because they are not relational data; what matters is that provenance travels with them. PostgreSQL via `SYNTHBODY_DATABASE_URL` for deployment. |
| **React + TypeScript + Vite** | Hand-written types mirroring the Pydantic contracts, so the shapes the UI depends on are explicit and reviewable. Vite's dev server makes the proxy configuration trivial. |
| **Tailwind with a custom token set** | Density and consistency. Semantic colours (`origin-fitted`, `origin-illustrative`, severity tones) are defined once, so a yellow badge means the same thing in every workspace. |
| **zustand** | The Studio reads many slices of state; re-rendering the tree on every slider move would be visible. Selector-based subscriptions keep it flat. |
| **Custom SVG plotting engine** | No charting library. ~700 lines gives exact control over log-axis tick behaviour (pharmacokinetic decline is log-linear and generic libraries handle it poorly), publication-quality vector export, and a crosshair readout that knows about series semantics. Series counts here are tens, well inside SVG's comfort zone. |
| **SALib** for global sensitivity | Morris and Sobol are easy to implement wrongly. SALib is the reference implementation the literature uses. |
| **No LLM in the numerical path** | Every curve, metric and interval is produced by NumPy/SciPy code operating on declared parameters. |

---

## 3. Engine design

### 3.1 The model contract

A model declares its identity, its states, its right-hand side, and how to turn
states into observables. `BaseModel` (in `engine/core.py`) also lets a model
optionally provide:

- **an analytic Jacobian** — a large stability and speed win for the stiff
  solvers, and tested against central finite differences;
- **`eliminated_state_index()`** — the index of a cumulative-eliminated-amount
  state. A model that provides one gets a true mass-balance check;
- **`preferred_method()`** — e.g. the PBPK model asks for BDF, because blood
  pools turn over in seconds while adipose takes hours;
- **a closed-form solution** — used by the test suite to verify the numerical
  path, never to serve results.

### 3.2 Dosing as genuine discontinuities

An IV bolus is a state discontinuity. Smoothing it is how you get quietly wrong
Cmax values. So:

- Dose times become **breakpoints**; integration restarts at each one, and the
  solver never steps across a discontinuity.
- Instantaneous doses are **added to the state vector** at the breakpoint.
- Infusions enter through the RHS as a **piecewise-constant rate** over a
  half-open interval, so back-to-back infusions do not double count.
- At a breakpoint the pre-dose value is recorded **before** the dose is applied,
  so a trough and the peak that follows are both visible in the output.

That last detail is why the steady-state Cmin test can pass to 1e-5 against the
closed form.

### 3.3 The engine checks its own numerics

A solver reporting `success=True` means it met its own tolerance, not that the
answer is right. Every run therefore also computes:

| Check | What it catches |
| --- | --- |
| **Mass balance** — dosed in − (in body + eliminated), relative to dose | A wrong sign or a missing term in the RHS |
| **Negative-state detection**, scaled against the peak amount | Tolerance set too loose for the dynamics |
| **Tolerance refinement** — re-solve with 100× tighter tolerances, report the worst relative difference | An answer that looks fine but is not converged |

The refinement check costs one extra solve and is on by default. It is what
turns "the solver said it was fine" into "the answer does not change when I ask
for more accuracy".

### 3.4 Unit safety

`engine/units.py` implements a small closed vocabulary rather than importing a
units library. The design decision that matters: it **refuses** to convert
between dimensions rather than guessing.

```python
convert(1.0, "mg", "L")        # UnitError: different dimensions
to_canonical(0.5, "L/kg")      # UnitError: body weight required
to_canonical(0.5, "L/kg", 70)  # 35.0
```

Per-kilogram units require an explicit body weight — omitting it is an error,
not a silent assumption of 70 kg. `ug/mL` and `mg/L` are explicitly identical,
because treating them as different is a classic source of 1000× errors.

### 3.5 Provenance is a first-class object

`engine/provenance.py` defines two enums that the whole product is organised
around: `ParameterOrigin` (measured / fitted / literature_fitted / derived /
inferred / illustrative / user) and `ValidationStatus`
(independently_validated / calibrated_only / structurally_verified /
research_only / not_validated).

Two hashes, with a deliberate split:

- **`input_hash`** covers only what determines the numbers: model id, model
  version, engine revision, parameter **names, values and units**, inputs, and
  random seed. Timestamp, platform and Python version are excluded so the same
  science run twice hashes identically.
- **`record_hash`** covers the whole document, including evidence metadata.

That split exists because an early version included origin tags in
`input_hash`, which meant *improving a citation* invalidated every stored
reproducibility hash and made the check cry wolf. There is a test pinning the
contract both ways.

### 3.6 Where origin tags actually get set

A model instance receives plain numbers through its constructor and cannot know
their pedigree, so it tags everything `USER`. The service layer then
**re-tags** each record by asking where the value really came from:

| Source | Resulting tag |
| --- | --- |
| Operator supplied it in the request | `user` |
| It came from the drug library | that entry's own origin, plus its citations, caveat and fitted-from-dataset note |
| Neither — it is a model schema default | `illustrative`, with a note saying so |

This is why a theophylline run reports `fitted` for CL with its PMIDs attached,
`illustrative` for bioavailability, and `derived` for ke — while the same model
with no compound selected reports `illustrative` for everything.

---

## 4. Module map

### `backend/synthbody/engine/`

| Module | Responsibility |
| --- | --- |
| `core.py` | `BaseModel` contract, `DoseEvent`, `expand_regimen`, `simulate()`, diagnostics |
| `units.py` | Canonical units, dimension-safe conversion |
| `provenance.py` | Origin and validation enums, `ParameterRecord`, `ProvenanceRecord`, hashing |
| `registry.py` | Model catalogue with parameter/observable schemas; drug and reference library loaders |
| `models/compartmental.py` | 1-cmt first-order absorption, 2-cmt, 1-cmt Michaelis–Menten — each with analytic solution and Jacobian |
| `models/pbpk.py` | 12-tissue perfusion-limited PBPK with portal drainage and well-stirred hepatic clearance |
| `models/pharmacodynamics.py` | Sigmoid Emax, indirect response (4 variants), effect compartment |
| `physiology/reference_man.py` | Reference physiology loader with provenance |
| `physiology/covariates.py` | `VirtualPatient`, Cockcroft–Gault, CKD-EPI 2021, Du Bois BSA, Janmahasatian FFM, Devine IBW, allometry, covariate effects |
| `physiology/partition.py` | Poulin–Theil tissue-composition partitioning, analytic Vss |
| `analysis/nca.py` | Linear-up/log-down AUC, automatic λz window selection, accumulation metrics, grid-independent time-in-range |
| `analysis/metrics.py` | RMSE/MAE/AFE/AAFE/fold-error/CCC, R² against the **line of identity**, residual diagnostics, prediction-interval coverage |
| `analysis/sensitivity.py` | Local normalised finite differences with step-halving check, Morris, Sobol |
| `analysis/population.py` | Log-normal random effects with PSD-projected correlation, Monte Carlo cohorts, residual error |
| `analysis/estimation.py` | Log-scale weighted NLS with asymptotic SEs, correlation matrix, condition-number identifiability check; two-stage |
| `analysis/datasets.py` | Theoph and Indometh loaders with licence and limitation metadata |
| `analysis/validation.py` | The fixed-protocol held-out validation pipeline |

### `backend/synthbody/api/`

`service.py` is the only place that knows about both the engine and the
database. It resolves a request into a model instance, applies covariates while
recording each adjustment and its evidence origin, runs the engine, computes
exposure metrics, assembles and re-tags provenance, and persists.

Routers: `library.py` (read-only catalogue), `simulate.py` (the four compute
endpoints), `workspace.py` (patients, experiments, stored runs, validation,
reports).

### `frontend/src/`

| Path | Responsibility |
| --- | --- |
| `lib/types.ts` | Hand-written mirror of the API contracts |
| `lib/api.ts` | Typed client; surfaces the server's own error message, including FastAPI validation detail |
| `lib/store.ts` | zustand store: catalogue, current setup, results, scenario bench, diagnostics log |
| `lib/scale.ts` | Linear and log scales with 1/2/5 tick generation and decade-aware log ticks |
| `lib/format.ts` | Significant figures, units, origin/validation metadata, series palette, CSV export |
| `components/charts/Plot.tsx` | The plotting engine: lines, points, ribbons, bands, markers, identity/fold lines, drag-zoom, crosshair readout, SVG export |
| `components/ui/index.tsx` | ~30 primitives — Panel, Table, Metric, OriginBadge, ValidationBadge, Splitter, Modal, Toast, … |
| `components/Shell.tsx` | Title bar with the non-dismissible regulatory strip, activity rail, status bar, diagnostics console, command palette, global hotkeys |
| `workspaces/*.tsx` | The eight workspaces |

---

## 5. API surface

```
GET  /health
GET  /api/meta                               version, intended use, regulatory status
GET  /api/models                             model catalogue with parameter schemas
GET  /api/models/{id}
GET  /api/drugs                              drug library + origin legend
GET  /api/drugs/{id}
GET  /api/references?q=&topic=&kind=          searchable reference library
GET  /api/references/{id}                     + which models and drugs depend on it
GET  /api/physiology                          reference physiology with provenance
GET  /api/datasets
GET  /api/datasets/{id}                       including every observed value

POST /api/simulate                            deterministic run
POST /api/simulate/compare                    multi-scenario with exposure table
POST /api/simulate/population                 Monte Carlo cohort
POST /api/simulate/sensitivity                local | morris | sobol

GET    /api/patients
POST   /api/patients
PUT    /api/patients/{id}
DELETE /api/patients/{id}                     409 if referenced by a stored run
POST   /api/patients/preview                  derived physiology without storing

GET    /api/experiments
POST   /api/experiments
PUT    /api/experiments/{id}
DELETE /api/experiments/{id}                  cascades to its simulations

GET    /api/simulations?experiment_id=&model_id=&limit=
GET    /api/simulations/{id}
POST   /api/simulations/{id}/reproduce        re-execute and compare hashes + curve
POST   /api/simulations/{id}/duplicate
DELETE /api/simulations/{id}
GET    /api/audit

GET  /api/validation/targets
GET  /api/validation/{target_id}              runs the pipeline live
GET  /api/validation/pbpk/structural-check

POST /api/reports                             markdown | json
```

Interactive docs at `/docs`.

---

## 6. Engineering practices

**Typed contracts.** Pydantic v2 with `extra="forbid"` on every input model,
cross-field validators (an IV infusion must have a duration; the last dose must
land inside the horizon), and TypeScript types mirroring them. During
development, `extra="forbid"` caught a real bug where the frontend spread a
drug's `default_regimen` wholesale into the regimen object — the strict schema
rejected it with a precise message instead of silently ignoring two fields.

**Error handling.** `ServiceError` → 400 with the parameter name and its allowed
range. Validation errors → 422 with field paths. SALib absent → 501. Unhandled
→ 500 with a request id, logged. The client surfaces the server's message
verbatim, and a connection failure tells the operator how to start the backend.

**Structured logging.** JSON lines with a request id, duration and status.
Simulations log their solver method, tolerances, RHS evaluation count,
wall time, mass-balance error and every warning.

**Testing.** 199 tests, organised by what they protect:

| File | Tests | Protects |
| --- | --- | --- |
| `test_units.py` | 16 | Unit safety — including that cross-dimension conversion is *refused* |
| `test_engine_numerics.py` | 44 | ODE correctness against closed forms, superposition, dose proportionality, infusion steady state, steady-state Cmax/Cmin, Jacobians, provenance hashing contract |
| `test_pbpk_and_physiology.py` | 33 | Physiology plausibility, flow and mass balance, Kp equilibrium, flow-limited clearance, partition behaviour |
| `test_analysis.py` | 51 | NCA against analytic answers, metric honesty (AFE vs AAFE), sensitivity against analytic derivatives, population sampler recovery, estimator recovery |
| `test_api_and_validation.py` | 55 | Dataset integrity against distributed values, the validation protocol, every endpoint, provenance origin accuracy |

Several tests exist specifically to stop the product overstating itself:

- `test_pbpk_declares_research_only_status` — a guard against someone quietly
  upgrading the PBPK claim.
- `test_drug_parameters_all_declare_origin` and
  `test_fitted_drug_parameters_name_their_dataset` — a `fitted` claim must say
  what it was fitted to.
- `test_references_declare_access_honestly` — every reference must state
  whether its full text was retrieved.
- `test_synthetic_drug_parameters_are_never_tagged_measured`.
- `test_every_model_reference_resolves` — a dangling citation is worse than none.

**Dependency locking.** Exact pins in `requirements.txt` and
`package-lock.json`.

**Configuration.** Environment-driven via `SYNTHBODY_*` with `pydantic-settings`.
Hard caps (`max_population_subjects`, `max_sensitivity_samples`,
`max_output_points`, `max_simulation_horizon_h`) stop a single request wedging
the process.

**Database migrations.** Alembic is configured. `init_db()` creates tables on
first run so a fresh clone works without a migration step.

---

## 7. Deployment

### Local

Two processes: uvicorn on 8011, Vite on 5180 (both overridable). The Vite dev
server proxies `/api` and `/health`, so there is no CORS in development.

### Docker

```bash
docker compose up --build
```

Backend on 8011, nginx-served frontend build on 5180, SQLite on a named volume.

### Production considerations, honestly

- **Add authentication.** The API is unauthenticated and intended for localhost.
- **Move to PostgreSQL** via `SYNTHBODY_DATABASE_URL` for concurrent use.
- **Add a job queue.** Simulation is synchronous and CPU-bound; a
  2000-subject cohort blocks a worker for minutes.
- **Pin the image digest** if reproducibility across time matters — the engine
  revision in the provenance record identifies the science, but not the exact
  SciPy build.

---

## 8. Extending it

**Adding a model.** Subclass `BaseModel`, implement `state_names`, `rhs` and
`observables`; optionally add a Jacobian, an `eliminated_state_index` and a
closed-form solution for the tests. Register a `ModelSpec` in
`engine/registry.py`. The frontend reads the registry, so no UI change is
needed — parameter controls, observable overlays and dose routing all come from
the schema.

**Adding a drug.** Add an entry to `data/library/drugs.json`. Every parameter
needs an `origin`; a `fitted` origin needs `fitted_from_dataset` and
`fitted_from_subjects`, and a test enforces that.

**Adding a validation target.** Add a `ValidationTarget` in
`engine/analysis/validation.py` with its fit specs and a prediction function.
The pipeline, the API endpoint and the Evidence workspace pick it up
automatically.
