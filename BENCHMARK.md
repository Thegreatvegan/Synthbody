# SYNTHBODY — Competitive Benchmark Report

**Software** 0.1.0 · **Engine** `engine-2026.10.12b`
**Reproduce** `cd backend && python scripts/run_benchmark.py`
**Raw results** [docs/benchmark_results.json](docs/benchmark_results.json)
**In the app** Evidence workspace → *Competitive benchmark*

---

## Summary

| | Status |
| --- | --- |
| **Requested benchmark** — SYNTHBODY vs Simcyp / GastroPlus / GI-Sim on Sjögren et al. 2016 | ❌ **Not run.** Source data paywalled; SYNTHBODY refuses to fabricate it. |
| **Capability gap closed** — mechanistic GI absorption model | ✅ **Built and verified.** 7-compartment CAT/ACAT-style model, 35 new tests. |
| **Benchmark that could run** — a-priori oral absorption on open data | ✅ **Executed.** AUC AAFE 1.14, Cmax AAFE 1.08, tmax AAFE 1.64. |
| **Head-to-head conclusion** | ⛔ **None drawn.** The experiments are not equivalent. |

**The one-line result:** SYNTHBODY can now predict oral absorption from
physicochemistry, and it does so accurately for a freely soluble drug — but
that is not the question the published benchmark asks, and the data needed to
answer that question is behind a paywall.

---

## 1. Why the requested benchmark was not run

The target study is:

> Sjögren E, Thörn H, Tannergren C. *In Silico Modeling of Gastrointestinal
> Drug Absorption: Predictive Performance of Three Physiologically Based
> Absorption Models.* Mol Pharm. 2016;13(6):1763-78.
> PMID [26926043](https://pubmed.ncbi.nlm.nih.gov/26926043/) · DOI 10.1021/acs.molpharmaceut.5b00861

### 1.1 Access record (checked 2026-10-12)

| Route | Result |
| --- | --- |
| Unpaywall API | `is_oa: false`, `oa_status: "closed"`, **0 OA locations** |
| OpenAlex API | `is_oa: false`, no `pdf_url`, no licence |
| PubMed Central | Not deposited |
| ACS article page | **HTTP 403** |
| ACS Supporting Information | **HTTP 403** |

What sits behind that paywall is precisely what the benchmark needs:

- the identities of the 12 drugs;
- per-drug physicochemistry — intrinsic solubility, pKa(s), human effective
  permeability, particle size, formulation;
- dose and dosing conditions for each of the 44 administrations;
- the literature disposition parameters used for the convolution;
- **the 44 observed clinical AUC / Cmax / tmax values — the benchmark target.**

Without the observed values there is nothing to compute an AAFE against.

### 1.2 The refusal is enforced in code, not just in prose

`compare_against_published()` in `backend/synthbody/engine/analysis/benchmark.py`
returns `comparison_available: false` and there is **no code path** from an
empty case library to a comparison table. Four tests enforce it, including:

```
test_head_to_head_comparison_is_refused_without_data
test_orbito_case_library_ships_empty
test_access_record_documents_why_data_is_unavailable
```

This matters because the alternative was easy and undetectable. I could have
produced a table showing SYNTHBODY at AAFE 1.1, beating GI-Sim, and nothing
short of reading the paper would have revealed it as invented.

### 1.3 Published competitor figures (recorded, never computed)

| Software | AUC | Cmax | tmax |
| --- | --- | --- | --- |
| Simcyp 13.1 | 2.2 | 2.2 | 1.7 |
| GastroPlus 8.0 | 1.6 | 1.6 | 1.5 |
| GI-Sim 4.1 | 1.3 | 1.3 | 1.4 |
| **SYNTHBODY** | **not computed** | **not computed** | **not computed** |

Taken verbatim from the public PubMed abstract. Three caveats travel with them:

1. They are for **2016 software versions**, not current releases.
2. They reflect those vendors' own modelling choices, made by the study authors.
3. The methodology was **publicly contested** — see the Comment and Reply,
   PMID [27983859](https://pubmed.ncbi.nlm.nih.gov/27983859/).

### 1.4 How to unlock the comparison

Populate `backend/synthbody/data/library/orbito_cases.json` (it ships empty with
a full schema and instructions) and re-run. The comparison becomes available
automatically. The file also carries a comparability warning: supplying inputs
the original modellers did not have, or tuning anything against the observed
outcomes, invalidates the comparison regardless of the resulting number.

---

## 2. The capability gap — and what was built to close it

### 2.1 What SYNTHBODY could not do

The study's method is stated in its abstract: *"Plasma concentration-time
profiles for 44 oral drug administrations were calculated by **convolution of
model-predicted absorption-time profiles** and reported pharmacokinetic
parameters."*

So the thing benchmarked is the **GI absorption model** — predicting fabs and
absorption rate *a priori* from physicochemistry, for 12 drugs chosen for
**incomplete absorption**.

A repository audit before this work found:

| Required capability | Occurrences in SYNTHBODY |
| --- | --- |
| dissolution / Noyes–Whitney / Nernst–Brunner | **0** |
| solubility, pH-dependent solubility | **0** |
| particle size, precipitation | **0** |
| Peff / permeability-limited absorption | **0** |
| regional GI transit (ACAT/ADAM) | **0** |
| stomach, duodenum, jejunum, ileum, colon | **0** |

Absorption was one line — `dA_depot/dt = −ka·A_depot` — with `ka` an **input**.
The quantity the benchmark measures was the quantity SYNTHBODY could not produce.

### 2.2 What was built

A compartmental absorption and transit model
(`backend/synthbody/engine/models/absorption.py`), structured after
Yu & Amidon (1999), PMID [10486429](https://pubmed.ncbi.nlm.nih.gov/10486429/):

```
stomach ──> SI_1 ──> ... ──> SI_7 ──> colon ──> faeces
   │          └────────┬──────────┘      │
   │          absorption into portal blood
   └── no gastric absorption modelled
```

| Process | Equation |
| --- | --- |
| Gastric emptying | first-order, `Kge = ln2 / t½` |
| Intestinal transit | first-order, `Kt = N / T_si` |
| Solubility | Henderson–Hasselbalch at each compartment's own pH, with optional bile-salt solubilisation |
| Dissolution | Nernst–Brunner for shrinking spheres, `dM/dt = (D·A/h)(Cs − C)`, `A = 3M/(ρr)` |
| Absorption | permeability-limited, `ka,i = 2·Peff/R` |
| Precipitation | first-order on supersaturation |

Coupled to the existing disposition models via `OralAbsorptionWithDisposition`,
which integrates absorption and disposition together — an exact convolution,
matching the published methodology.

### 2.3 Physiology provenance

All fasted-state GI physiology comes from an **open-access** source, retrieved
and parsed programmatically rather than transcribed:

> Mudie DM, Amidon GL, Amidon GE. *Physiological parameters for oral delivery
> and in vitro testing.* Mol Pharm. 2010;7(5):1388-405.
> PMID [20822152](https://pubmed.ncbi.nlm.nih.gov/20822152/) · **PMC3025274** · open access

| Parameter | Value | Origin |
| --- | --- | --- |
| Gastric pH (fasted, median) | 1.7 | measured |
| Gastric half-emptying (300 mL water) | 15.8 min | measured |
| Small-intestinal transit | 192 min | measured |
| Small-intestinal liquid volume | 105 mL | measured |
| Small-intestinal length | 680 cm | measured |
| Small-intestinal radius | 1.75 cm | measured (httk, GPL-3) |
| Regional pH, duodenum → ileum | 6.2 → 7.2 | measured endpoints, interpolated between |
| Bile salts, duodenum → ileum | 2.7 → 2.0 mM | measured endpoints, interpolated |
| Colonic parameters | — | **illustrative** (SYNTHBODY defaults) |

**Independent corroboration:** Mudie reports 192 min for small-intestinal
transit; the unrelated US EPA `httk` dataset gives 199.2 min. Agreement within
4% from two independent sources.

### 2.4 Two bugs the build surfaced

**A modelling error.** Particle radius was initially inferred from the solid
mass *in each compartment*. That is wrong: a compartment holding a tenth of the
dose holds a tenth of the particles at full size, not all particles at a tenth
the volume. Radius is now derived once per evaluation from total solid across
the whole tract. Pinned by `test_particle_radius_is_global_not_per_compartment`.

**A numerical singularity.** The textbook law with `h = r` gives
`dM/dt ∝ M^(1/3)`, whose derivative is infinite at depletion. For fine
particles of a soluble drug the initial rate is ~1.3×10⁶ mg/h (the dose
dissolves in 0.29 s), and the solver then has to resolve a non-smooth tail —
the first implementation **hung indefinitely**. Flooring the radius and the
diffusion layer converts the tail to a smooth first-order decay. Runtime went
from "never finishes" to **0.07 s**, with mass balance at 2×10⁻¹⁵.

### 2.5 Verification

35 new tests, all passing. The model reproduces every limiting behaviour an
absorption model must have:

| Check | Result |
| --- | --- |
| Highly soluble + permeable (BCS I) → fabs ≈ 1 | ✅ 0.998 |
| fabs falls monotonically with permeability | ✅ 0.998 → 0.053 over Peff 5×10⁻⁴ → 3×10⁻⁶ |
| Solubility-limited → fabs falls with dose | ✅ 0.407 → 0.008 over 1 → 800 mg |
| Freely soluble → fabs independent of dose | ✅ Δ < 0.02 over 10 → 500 mg |
| Smaller particles → higher fabs | ✅ 0.027 → 0.092 over 100 → 2 µm |
| Henderson–Hasselbalch: acid ↑ with pH, base ↓ | ✅ exact at pH = pKa |
| Solution dose > solid dose (poorly soluble) | ✅ 0.985 vs 0.073 |
| fabs bounded in [0,1] across 24 combinations | ✅ |
| Mass balance | ✅ < 1.7×10⁻¹³ worst case |
| First-pass extraction does not change fabs | ✅ |

---

## 3. The benchmark that ran

**A-priori oral absorption prediction on the openly licensed Theoph dataset.**

### 3.1 Design

The question: *with the absorption rate derived purely from GI physiology and
theophylline's physicochemistry — never fitted to these profiles — how well
does SYNTHBODY predict observed plasma concentrations?*

Three precautions against circularity:

1. **Disposition (CL/F, V/F) comes from calibration subjects only** (1, 3, 5, 7,
   9, 11); the test is on held-out subjects (2, 4, 6, 8, 10, 12).
2. **AUC is the weak metric** and is labelled as such — since AUC ≈ dose·fabs/CL
   and CL was fitted to this drug, AUC partly tests the fit rather than the
   absorption model. tmax is the cleanest test; Cmax is next.
3. **Permeability is inferred, so it is swept, not chosen.** The headline uses
   the value fixed *before* any result was computed.

### 3.2 Inputs

| Input | Value | Origin |
| --- | --- | --- |
| Intrinsic solubility | 7.36 mg/mL | **measured** — PubChem CID 2153, 7360 mg/L at 25 °C |
| pKa (acidic) | 8.81 | **measured** — PubChem CID 2153 |
| Effective permeability | 3.0×10⁻⁴ cm/s | **inferred** — BCS Class I; Lennernäs's measured dataset is paywalled |
| Particle radius | 25 µm | **illustrative** — formulation not recorded in the dataset |

### 3.3 Results — pre-specified Peff = 3.0×10⁻⁴ cm/s

**Mean predicted fabs = 0.984.** Theophylline is a BCS Class I drug and is
completely absorbed in vivo. The model was given only solubility, pKa and
permeability — never the observed profiles — so recovering fabs ≈ 1 is a
genuine a-priori result.

| Metric | n | AAFE | AFE | Median FE | Within 2-fold | Max FE |
| --- | --- | --- | --- | --- | --- | --- |
| **AUC** | 6 | **1.142** | 1.082 | 1.164 | 100% | 1.27 |
| **Cmax** | 6 | **1.075** | 0.970 | 1.074 | 100% | 1.12 |
| **tmax** | 6 | **1.642** | 1.377 | 1.384 | 67% | 2.54 |

### 3.4 Per-subject (held out)

| Subject | Dose mg | fabs | AUC pred | AUC obs | Cmax pred | Cmax obs | tmax pred | tmax obs |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | 318.6 | 0.984 | 114.4 | 97.4 | 7.68 | 8.33 | 2.73 | 1.92 |
| 4 | 319.9 | 0.984 | 114.4 | 114.2 | 7.68 | 8.60 | 2.72 | 1.07 |
| 6 | 320.0 | 0.984 | 104.0 | 81.7 | 6.99 | 6.44 | 2.73 | 1.15 |
| 8 | 319.4 | 0.984 | 117.8 | 102.1 | 7.91 | 7.56 | 2.71 | 2.02 |
| 10 | 320.1 | 0.984 | 143.0 | 167.9 | 9.60 | 10.21 | 2.72 | 3.55 |
| 12 | 320.6 | 0.984 | 137.8 | 125.8 | 9.26 | 9.75 | 2.72 | 3.52 |

Max GI mass-balance error: 6.9×10⁻¹⁵.

### 3.5 Sensitivity to the inferred permeability

| Peff (cm/s) | mean fabs | AUC AAFE | Cmax AAFE | tmax AAFE |
| --- | --- | --- | --- | --- |
| 1.0×10⁻⁴ | 0.803 | 1.131 | 1.461 | 1.966 |
| 2.0×10⁻⁴ | 0.950 | 1.129 | 1.125 | 1.729 |
| **3.0×10⁻⁴** ← pre-specified | **0.984** | **1.142** | **1.075** | **1.642** |
| 5.0×10⁻⁴ | 0.998 | 1.152 | 1.057 | 1.526 |
| 1.0×10⁻³ | 1.000 | 1.153 | 1.076 | 1.540 |

The best sweep point (5×10⁻⁴, Cmax AAFE 1.057) is **not** quoted as the result.
Choosing it would be selection on the outcome. The gap is small — 1.075 vs
1.057 — which is itself useful information: the conclusion does not hinge on
the inferred input.

### 3.6 Where it fails, honestly

**tmax is the weak metric, and the per-subject table shows exactly why.** The
model predicts tmax ≈ 2.72 h for *every* subject, because gastric emptying and
transit are population means. The observed tmax ranges from **1.07 to 3.55 h**.

The model has no mechanism for between-subject variability in gastric
emptying — which is, in reality, one of the largest sources of variability in
oral absorption. That is a real limitation, not noise, and it is why tmax
manages only 67% within 2-fold while Cmax manages 100%.

---

## 4. Why these numbers must not be compared to the published ones

SYNTHBODY's Cmax AAFE of 1.075 is numerically better than GI-Sim's published
1.3. **That comparison is meaningless**, for five independent reasons:

| | This benchmark | Sjögren et al. |
| --- | --- | --- |
| Drugs | **1** | **12** |
| Administrations | **6** | **44** |
| Drug class | BCS I, freely soluble, ~100% absorbed | chosen for **incomplete absorption** |
| What is being tested | does the machinery work on an easy case | can dissolution and solubility limitation be predicted |
| Disposition source | fitted to this drug (other subjects) | independent literature values |

The published study deliberately selected the regime where absorption models
differ — poorly soluble compounds where dissolution rate, precipitation and
solubility limitation dominate. A freely soluble BCS Class I drug is the
*easiest* possible case. Scoring well on it says the equations are wired up
correctly. It says **nothing** about performance on the drugs that matter.

Any claim that SYNTHBODY outperforms Simcyp, GastroPlus or GI-Sim would be
unsupported, and this report does not make one.

---

## 5. What would make a real comparison possible

| Need | Why | Difficulty |
| --- | --- | --- |
| The Sjögren et al. paper + SI | Supplies both the inputs and the targets | Institutional access or purchase |
| Measured human Peff values | Currently inferred; Lennernäs's dataset is paywalled | Licensing |
| Measured solubility–pH profiles | Henderson–Hasselbalch is an approximation; real profiles deviate | Licensing or lab data |
| Precipitation kinetics | Currently one first-order rate; supersaturating formulations need nucleation-and-growth | Model development + data |
| Regional permeability | Currently uniform along the small intestine | Data |
| Fed-state physiology | Not implemented at all | Mudie reports fed values; needs a food-effect model |
| Gut-wall metabolism and efflux | fabs ≠ bioavailability without them | Model development |

The honest ordering: **data licensing is the binding constraint, not
engineering.** The absorption model took hours. Validating it properly needs
data that costs money or partnership.

---

## 6. Status of the absorption model

`research_only`, and it stays there until it is compared against observed
concentration-time data for drugs with incomplete absorption.

What it is: a mechanistic absorption model built from published structure, with
physiology from an open-access source, that reproduces every expected limiting
behaviour and closes mass balance to 10⁻¹³.

What it is not: validated. It predicts **fraction absorbed**, not
bioavailability — there is no gut-wall or hepatic first-pass extraction inside
it. No fed state. No controlled release. Colonic parameters are invented
defaults.

---

## 7. Reproducing this report

```bash
cd backend
python scripts/run_benchmark.py                                # the report above
python scripts/run_benchmark.py --json ../docs/benchmark_results.json
python -m pytest tests/test_absorption_and_benchmark.py -q     # 35 tests
python -m pytest tests/ -q                                     # 234 tests
```

Or open the app: **Evidence → Competitive benchmark**. It runs live rather than
reading a cached result, so the figures are always current for the code you are
running — including the refusal.
