# SYNTHBODY

**Research-grade virtual-patient pharmacokinetic simulation.**

A working MVP derived from the *Project SYNTHBODY* white paper, built with
classical numerical methods. Two independently validated compartmental
pharmacokinetic models, a whole-body PBPK model, population variability,
sensitivity analysis, complete per-parameter evidence provenance, and verified
deterministic reproduction.

> ### Not a medical device
> SYNTHBODY has not been reviewed or cleared by any regulator. Nothing it
> produces is a diagnosis, a dose recommendation, or a prediction about any real
> person. It is designed to be used with synthetic or published de-identified
> research data only, and it makes **no** HIPAA or GDPR compliance claim.
> Check a model's validation status before relying on any number it produces.

---

## Quick start

Requires **Python ≥ 3.11** and **Node ≥ 18**. No GPU, no cloud, no quantum
hardware.

### 1. Backend

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn synthbody.api.main:app --host 127.0.0.1 --port 8011
```

Check it: <http://127.0.0.1:8011/health> → `{"status":"ok","software":"SYNTHBODY",...}`
Interactive API docs: <http://127.0.0.1:8011/docs>

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5180>.

> **Ports.** 8000 and 5173 are commonly occupied by other local services, so
> SYNTHBODY defaults to **8011** (API) and **5180** (UI). Override with
> `SYNTHBODY_API_PORT` and `SYNTHBODY_UI_PORT`, or point the UI at a remote
> backend with `VITE_API_URL`.

### 3. Verify the installation

```bash
cd backend
python -m pytest tests/ -q          # 286 tests
python scripts/run_validation.py    # reproduces every number in VALIDATION.md
python scripts/run_benchmark.py     # reproduces every number in BENCHMARK.md
```

### Docker

```bash
docker compose up --build
```

UI on <http://localhost:5180>, API on <http://localhost:8011>.

---

## What it does

### Eight connected workspaces

| Workspace | Purpose |
| --- | --- |
| **Studio** | Configure and execute simulations. Parameter inspector with live evidence-origin tags, scenario bench for dose comparison, provenance inspector with solver diagnostics. |
| **Patient Builder** | Define hypothetical virtual subjects. Live derived physiology (BSA, CrCl, eGFR, fat-free mass) with every equation cited, and a side-by-side run showing how much the subject's covariates actually move the prediction. |
| **Compounds** | The drug library. Every stored parameter with its value, unit, evidence origin, between-subject variability, and the dataset and subjects it was fitted from. |
| **Systems** | The compartments and transport paths of the **active model** — and an explicit list of everything that is *not* modelled. |
| **Analytics** | Monte Carlo population variability with percentile envelopes and exposure distributions; local, Morris and Sobol sensitivity analysis. |
| **Experiments** | Stored runs grouped into experiments, with a reproduce button that re-executes a saved run and compares the input hash, engine revision and curve point by point. |
| **Evidence** | Searchable reference library (32 entries, every PMID verified against PubMed), live validation results, the oral PBPK concentration-time validation, the competitive benchmark, the shipped observed datasets, and the feasibility assessment. |
| **Reports** | Generates a complete methods-and-results document: inputs, parameter provenance, exposure metrics, solver diagnostics, independent validation, limitations, references. |

### Models

| Model | Status | Validation |
| --- | --- | --- |
| One-compartment, first-order absorption | `independently_validated` | Held-out Theoph subjects: AAFE **1.29**, **90%** within 2-fold, median absolute error **19%** |
| Two-compartment | `independently_validated` | Held-out Indometh subjects: AAFE **1.34**, **94%** within 2-fold |
| One-compartment Michaelis–Menten | `structurally_verified` | Numerics verified; no observed non-linear PK dataset ships |
| Whole-body perfusion-limited PBPK (12 tissues), IV | `research_only` | Mass and flow balance close; predicted theophylline Vss within **1.04-fold** of the reported 0.5 L/kg. Its distribution equations are exercised by the oral PBPK test below, but its own first-order oral depot route has no concentration-time validation. |
| **Whole-body oral PBPK (7-cmt ACAT + 12 tissues)** | `research_only` | **First concentration-time test of the PBPK module.** Held-out Theoph subjects: AAFE **1.19**, **97%** of 66 points within 2-fold, Cmax AAFE **1.10**, tmax AAFE **1.52**. Volume of distribution predicted, never fitted (0.479 vs 0.459 L/kg fitted, 1.04-fold). Plasma only; tissue concentrations remain unvalidated. |
| Sigmoid Emax, indirect response (×4), effect compartment | `research_only` | Structurally verified; all shipped PD parameters are **illustrative** |
| Compartmental GI absorption and transit (7-compartment CAT/ACAT) | `research_only` | Predicts fabs from physicochemistry. A-priori test on held-out Theoph: Cmax AAFE **1.08**, AUC AAFE **1.14**. Not validated for poorly soluble drugs. Single dosing only. |

Full numbers, including everything that went wrong: **[VALIDATION.md](VALIDATION.md)**

### Keyboard

| | |
| --- | --- |
| `Ctrl K` | Command palette |
| `Ctrl ⏎` | Run simulation |
| `Ctrl S` | Capture current setup as a scenario |
| `Ctrl L` | Toggle logarithmic concentration axis |
| `Ctrl I` | Toggle provenance inspector |
| `` Ctrl ` `` | Toggle diagnostics console |
| `Alt 1`–`Alt 8` | Switch workspace |

---

## The two ideas that shape this product

### 1. Every number declares where it came from

A simulation platform's worst failure mode is making an invented default look
like a measurement. So every parameter carries an origin tag, visible at the
point of use and recorded in the provenance of every run:

| Tag | Meaning |
| --- | --- |
| `measured` | Directly measured or reported population value from a cited primary source |
| `fitted` | Estimated by SYNTHBODY's own regression against a named shipped dataset — reproducible by running the validation script |
| `literature_fitted` | A fitted estimate reported by a cited publication, not re-estimated here |
| `derived` | Computed from other parameters by an explicit documented equation |
| `inferred` | Reasoned from related data, or a widely quoted value whose primary source was **not retrieved** |
| `illustrative` | A plausible default chosen to make the software demonstrable. **Not evidence.** |
| `user` | Supplied by the operator at run time |

These tags are never upgraded. A theophylline simulation reports `fitted` for
clearance and `illustrative` for bioavailability, because that is the truth
about those two numbers. With no compound selected, every parameter reports
`illustrative`, because schema defaults are SYNTHBODY's choices and not
evidence.

### 2. The engine checks its own numerics

The solver's self-report is not taken at face value. Every run additionally
computes:

- **Mass balance** — amount dosed minus (amount in body + amount eliminated),
  relative to the dose. Typically ~1e-16.
- **Negative-state detection** — scaled against the peak amount so round-off
  does not raise false alarms.
- **Tolerance convergence** — the problem is re-solved with 100× tighter
  tolerances and the worst relative difference is reported, so you can see
  whether the answer is converged rather than assuming it.

Plus the usual: method, tolerances, RHS evaluations, Jacobian evaluations, LU
decompositions, accepted steps and wall time. All of it in the status bar and
the provenance record.

---

## Data provenance

Nothing in SYNTHBODY was transcribed by hand.

| What | Source | Licence |
| --- | --- | --- |
| Observed theophylline concentrations | R `datasets::Theoph` (132 obs, 12 subjects) | GPL-2 \| GPL-3 |
| Observed indomethacin concentrations | R `datasets::Indometh` (66 obs, 6 subjects) | GPL-2 \| GPL-3 |
| Organ volumes, perfusion, tissue composition, haematocrit, GFR | US EPA `httk` package, read programmatically from its binary `.RData` | GPL-3 |
| Chemical identifiers, molecular weights, computed log P | PubChem PUG REST API | Public domain |
| 28 literature references | Resolved against the NCBI PubMed E-utilities API | Cited only; per-entry licence recorded |

Every reference records **whether its full text was actually retrieved**. Where
SYNTHBODY could not open a primary source, the entry says so — including the
case where a canonical reference (Brown et al. 1997) was deliberately *not*
relied upon because the table could not be accessed, and an openly licensed
alternative was used instead.

---

## Architecture

```
synthbody/
├── backend/
│   ├── synthbody/
│   │   ├── engine/              numerics — no API or DB imports anywhere
│   │   │   ├── core.py          ODE integration, dose events, diagnostics
│   │   │   ├── units.py         unit safety; refuses cross-dimension conversion
│   │   │   ├── provenance.py    origin tags, validation states, hashing
│   │   │   ├── registry.py      model and drug catalogue
│   │   │   ├── models/          compartmental, PBPK, pharmacodynamics
│   │   │   ├── physiology/      reference physiology, covariates, partitioning
│   │   │   └── analysis/        NCA, metrics, sensitivity, population,
│   │   │                        estimation, datasets, validation pipeline
│   │   ├── api/                 FastAPI routers + service layer
│   │   ├── db/                  SQLAlchemy models and session
│   │   ├── schemas/             Pydantic API contracts
│   │   └── data/library/        drugs, references, reference physiology (JSON)
│   ├── scripts/run_validation.py
│   └── tests/                   286 tests
└── frontend/
    └── src/
        ├── components/          UI primitives + the SVG plotting engine
        ├── workspaces/          the eight workspaces
        └── lib/                 typed API client, store, scales, formatting
```

The engine imports nothing from the API or the database, which is what lets the
test suite exercise the numerics without a web server. Details:
**[ARCHITECTURE.md](ARCHITECTURE.md)**

---

## Documentation

| Document | Contents |
| --- | --- |
| **[VALIDATION.md](VALIDATION.md)** | Every achieved accuracy figure, the fixed protocol, and every known problem the pipeline surfaced |
| **[BENCHMARK.md](BENCHMARK.md)** | Competitive benchmark: the a-priori absorption test that ran, and the head-to-head vs Simcyp/GastroPlus/GI-Sim that was **refused** for lack of obtainable data |
| **[PROGRESS.md](PROGRESS.md)** | Capability expansion status: what is built and tested, and what each remaining module needs before it can be built honestly |
| **[SCIENTIFIC_LIMITATIONS.md](SCIENTIFIC_LIMITATIONS.md)** | What this software cannot tell you, and what would be needed to change that |
| **[FEASIBILITY_MATRIX.md](FEASIBILITY_MATRIX.md)** | All 71 white-paper components mapped to implemented / simplified / not implemented / excluded |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | Design decisions, module boundaries, API surface |
| **[ROADMAP.md](ROADMAP.md)** | Prioritised path toward a multi-organ digital twin, with the evidence each step requires |
| **[docs/SAMPLE_REPORT.md](docs/SAMPLE_REPORT.md)** | A generated research report, as the application produces it |

---

## Honest status

**What works and is validated:** compartmental PK for single-dose oral
theophylline and single-dose IV indomethacin, in healthy adults, within the
designs of those two datasets.

**What works but is unvalidated:** multiple dosing, intravenous theophylline,
covariate adjustment magnitudes, every PBPK *tissue* concentration, and all
pharmacodynamics. The software permits these simulations; the validation status
does not travel with you.

**Newly tested:** the whole-body oral PBPK model predicts held-out observed
plasma profiles with AAFE 1.19, with the volume of distribution and the entire
absorption profile derived from physicochemistry rather than fitted — a lower
error than the empirical one-compartment model achieved while fitting three
parameters. That is still one drug, one study, plasma only, and theophylline is
close to the easiest case a PBPK model can be given. Read
[VALIDATION.md](VALIDATION.md) before quoting it.

**What is deliberately absent:** quantum simulation, dosing recommendations,
disease progression, immune/endocrine/neurotransmitter/metabolic networks,
genomic personalisation, EHR integration, and blockchain notarisation. Each is
listed in the feasibility matrix with the reason.

The ratio of scope to evidence was the central design decision. The white
paper's unit of ambition is the whole human body; the unit of evidence
available today is twelve healthy adults given a single oral dose. This MVP
builds the narrow thing properly rather than the broad thing unsupportably.
