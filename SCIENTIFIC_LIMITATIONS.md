# SYNTHBODY — Scientific Assumptions and Limitations

This document states what SYNTHBODY cannot tell you. It is the most important
document in the repository, and it is deliberately written to be used *against*
the product: if you are about to rely on a SYNTHBODY number, look for it here
first.

**Software version** 0.1.0 · **Engine revision** `engine-2026.10.12b`

> Competitive benchmarking against Simcyp, GastroPlus and GI-Sim was attempted and
> **could not be run**: the source study is paywalled. See [BENCHMARK.md](BENCHMARK.md).

---

## 0. Regulatory and intended-use status

SYNTHBODY is **research simulation software**. It is not a medical device.

| Claim | Status |
| --- | --- |
| FDA cleared or approved | **No** |
| CE marked | **No** |
| HIPAA compliant | **No** — and not designed to be |
| GDPR assessed | **No** |
| Validated for clinical use | **No** |
| Quality management system | **None** |

The API reports all of this at `GET /api/meta`, so an integrator cannot miss it.

**Intended use.** Exploration of pharmacokinetic and pharmacodynamic model
behaviour for hypothetical simulated subjects, using published models and
openly licensed data.

**Not intended for,** and unsafe for:

- Diagnosis of any condition.
- Selection of a dose for any real person.
- Any decision affecting the care of an identifiable patient.
- Regulatory submission without independent qualification of each model.

SYNTHBODY stores **synthetic virtual subjects only**. The API rejects any record
flagged as a real person. Nothing in the product is designed for identifiable
patient data, and connecting it to clinical records would create obligations
this software cannot meet.

---

## 1. The boundary of what has been validated

Everything SYNTHBODY has evidence for sits inside this box:

> Single-dose oral theophylline in 12 healthy adults over ~25 hours, and
> single-dose intravenous indomethacin in 6 adults over 8 hours.

That is 18 subjects and 198 concentration measurements, total.

The software will let you simulate far outside that box. **The validation status
does not travel with you.** Specifically, these are all unvalidated
extrapolation:

| Simulation the software permits | Why it is unvalidated |
| --- | --- |
| Multiple dosing / accumulation / steady state | No multiple-dose dataset ships. The maths is verified against the closed form, but no observed data confirms the *biology* holds (no autoinduction, no time-varying clearance). |
| Intravenous theophylline | The Theoph dataset is oral-only, so bioavailability is not identifiable and CL/V are apparent values. An IV simulation applies apparent oral parameters as if they were absolute. |
| Children, neonates, the elderly | Healthy-adult data only. No maturation or ageing physiology is modelled; age affects only renal function. |
| Hepatic impairment | The multiplier is `illustrative`. The *direction* is supported; the magnitude is a SYNTHBODY default. |
| Smokers | The 1.6× factor is `inferred`, not extracted from a retrieved source. |
| Drug–drug interactions | Not modelled at all. No inhibition, induction, displacement or transporter competition. |
| Obesity | Allometric scaling on total body weight. Fat-free mass is computed and displayed but does not drive any model. Cockcroft–Gault overestimates clearance in obesity, which the UI flags but does not correct. |
| Renal impairment | Renal function is computed and displayed, but only a minor renal route exists for the shipped compounds. No renally cleared drug has been validated. |
| Any other drug | Three compounds ship; one of them is explicitly synthetic. |
| Any tissue concentration | PBPK output is `research_only`. See §4. |
| Any pharmacodynamic effect | All PD parameters are `illustrative`. See §5. |

---

## 2. Assumptions in the compartmental models

**Structural**

- Absorption is a single first-order process from one depot. No gastric
  emptying, no pKa-dependent solubility, no surface-area constraint, no transit
  compartments. An absorption lag is available but is a crude substitute.
- Disposition is linear: clearance and volume do not depend on concentration
  (except in the explicitly non-linear Michaelis–Menten model).
- Distribution within a compartment is instantaneous and complete.
- Bioavailability is constant across doses and does not saturate.
- Elimination occurs only from the central compartment.
- No enterohepatic recirculation. The indomethacin source study
  (Kwan et al. 1976) **reports** recirculation, so that mechanism appears as
  irreducible fit error rather than being represented.

**Statistical**

- Between-subject variability is log-normal on structural parameters.
- Residual error is combined additive-plus-proportional, and its magnitude is
  `illustrative` — not estimated from the data.
- Variability magnitudes come from **two-stage** estimation, which is known to
  overestimate between-subject variance because each individual estimate
  carries its own estimation error into the variance calculation. **Every
  reported CV% is an upper bound.** SYNTHBODY does not implement non-linear
  mixed-effects (FOCE/SAEM) estimation and says so wherever variability appears.

**Parameter identifiability**

- `ka` for theophylline has a between-subject CV of 120%, and two calibration
  subjects returned relative standard errors above 300% for it. The sampling
  schedule does not resolve absorption. Absorption-phase predictions are weak.
- `V2` for indomethacin has a reported CV of 3.55% from three subjects, one of
  which had an 81% relative standard error. That number is an artefact of a
  tiny sample, not evidence that V2 is conserved.
- Subject 1 of the Theoph dataset has a non-zero concentration at nominal time
  zero, which a model with an empty depot cannot reproduce. Its estimates carry
  relative standard errors above 1400%. The pipeline surfaces this rather than
  averaging it away.

---

## 3. Dataset limitations

### Theoph (theophylline)

- Single dose only — no information about accumulation or time-varying clearance.
- Healthy adults only.
- **Body weight is the only covariate recorded.** Smoking status, which strongly
  affects theophylline clearance via CYP1A2, is absent — so the smoking
  covariate cannot be validated against this dataset at all.
- Two subjects have non-zero concentrations at nominal time zero.
- Bioavailability is not identifiable, making CL and V apparent values.

### Indometh (indomethacin)

- **The administered dose is not present in the distributed dataset.** SYNTHBODY
  uses a nominal dose of 1 unit, so every volume and clearance is an apparent
  value per unit dose, **not** an absolute L or L/h. Rate constants and ratios
  remain valid; absolute volumes do not.
- Six subjects, three in the calibration set. Typical values and especially
  variability estimates are very imprecise.
- Eight hours of sampling under-determines the terminal phase.
- **No covariates at all** — no weight, age or sex.
- The source study reports enterohepatic recirculation.

---

## 4. The PBPK model — `research_only`

**This section was rewritten when the concentration-time test below was added.
The earlier text said the PBPK module had never been compared against an
observed profile. That is no longer true, and the limitations that remain are
different ones.**

### What has now been tested

The whole-body **oral** PBPK model (`pbpk_oral_acat`) predicts held-out
observed theophylline plasma profiles with AAFE 1.185 and 96.7% of 66 points
within 2-fold, with the volume of distribution and the entire absorption
profile predicted from physicochemistry rather than fitted. Full protocol and
caveats in [VALIDATION.md](VALIDATION.md) §5a.

### What that does and does not license

It licenses one sentence: for a freely soluble, highly permeable, neutral,
low-extraction, minimally bound drug, this model can predict an observed human
oral *plasma* profile to within roughly 15% median error.

It does not license anything else, and specifically:

- **One drug.** Theophylline is close to the easiest case a PBPK model can be
  given. Nothing here transfers to poorly soluble, highly bound,
  high-extraction or basic compounds.
- **Plasma only.** The model emits twelve tissue concentrations; exactly one
  observable was tested. **Every tissue concentration remains entirely
  unvalidated** and is labelled as such in the UI. Plasma agreement does not
  establish that any individual organ compartment is correct.
- **Same study.** The held-out subjects shared a protocol, laboratory and
  population with the calibration subjects.
- **The intravenous model was not tested.** `pbpk_perfusion_limited` shares the
  distribution equations that were exercised, but its own first-order oral
  depot route has no concentration-time validation of its own.

The validation status was deliberately **not** upgraded on the strength of one
drug. See [PROGRESS.md](PROGRESS.md) for what would justify that.

### The inputs are still weak

The test above inherits the same input provenance as the original scalar check:

- a log P that is PubChem's **XLogP3**, a *computed* descriptor, not a measurement;
- a fraction unbound that is **inferred** from "approximately 40% protein bound";
- a blood:plasma ratio whose primary source was **not retrieved**;
- all systemic clearance assigned to the hepatic route, because a primary
  source for theophylline's renal fraction was not retrieved. The effect of
  that choice is small enough to be checked rather than assumed, and
  `test_renal_fraction_barely_moves_the_result` checks it.

A good prediction from weakly sourced inputs is still a good prediction, but it
is not evidence that the inputs are right.

### Structural limitations

- **No blood-brain barrier.** Brain is an ordinary perfusion-limited
  compartment, so brain concentrations will be **overestimated** for any
  compound actively excluded from the CNS. This is the single most
  misuse-prone output in the product.
- **Perfusion-limited everywhere**: no permeability barriers, instantaneous
  tissue–blood equilibration.
- **No active transport** (P-gp, OATP, OCT, BCRP). All transport is passive.
- **No biliary excretion, no enterohepatic recirculation.**
- **No metabolite formation or tracking.** Drug is eliminated into a bookkeeping
  state, not transformed into named species.
- **No tissue heterogeneity.** Each organ is one well-mixed compartment with no
  internal gradients, no spatial dimension, and no PDE solver anywhere.
- **No protein-binding displacement.** Fraction unbound is a constant input.

### Partitioning method limitation

Tissue:plasma partition coefficients are predicted by the **Poulin & Theil
(2002)** tissue-composition method. This method is **known to predict poorly
for moderate-to-strong bases**, where binding to acidic phospholipids dominates.
Rodgers & Rowland (2005/2006) is the appropriate method for those compounds and
is **not implemented**. SYNTHBODY emits a warning when it detects a basic
compound, but the warning does not fix the prediction.

### Physiology provenance caveat

Organ volume fractions trace to a **1994 ILSI Risk Science Institute
monograph that SYNTHBODY could not independently retrieve.** They are used
exactly as redistributed in the GPL-3 US EPA `httk` package, with httk's own
attribution. Anyone using these values for a regulatory purpose should verify
them against the primary document.

Likewise, the canonical reference for PBPK physiology (Brown et al. 1997,
PMID 9249929) was **deliberately not used**: its human parameter table is
paywalled and could not be accessed, and transcribing it from memory or from
secondary summaries would have been fabrication. The reference library records
this decision explicitly.

### Modelling assumptions declared in the code

- The lumped `rest` compartment is assigned **muscle** tissue composition. Its
  volume and perfusion come from the source dataset; its composition does not.
- Cardiac output is defined as the **sum of the modelled tissue flows**, so
  that flow balance closes exactly. The independent whole-body value from the
  source dataset is shown alongside for comparison.
- Blood volume is split **1:2** between arterial and venous pools.
- A single reference adult physiology, scaled only by body weight. No
  paediatric, geriatric, pregnancy or disease physiology.

---

## 4b. The GI absorption model — `research_only`

Added to close the capability gap exposed by the Sjögren et al. benchmark. It
predicts fraction absorbed from physicochemistry; it is **not validated**.

- **Fasted state only.** No food effect. Mudie et al. report fed values with far
  greater spread and strong meal-volume dependence; none of it is implemented.
- **Predicts fraction ABSORBED, not bioavailability.** There is no gut-wall or
  hepatic first-pass extraction inside the absorption model, and no efflux
  transport. A drug can be fully absorbed and still have low bioavailability.
- **No between-subject variability in gastric emptying.** This is visible in the
  benchmark: predicted tmax is ~2.72 h for every subject while observed tmax
  spans 1.07–3.55 h. Gastric emptying variability is one of the largest real
  sources of oral-absorption variability and the model has no mechanism for it.
- **Monodisperse spherical particles** at a single radius. No particle-size
  distribution, no aggregation, no shape factor.
- **The diffusion layer is `min(r, 30 µm)` floored at 1 µm**, not computed from
  hydrodynamics. The floor is a numerical necessity (without it the depletion
  tail is unintegrable) and it changes the equation from its textbook form.
- **Precipitation is a single first-order rate**, not nucleation-and-growth, so
  supersaturating formulations will be poorly represented.
- **Uniform permeability** along the small intestine; no regional differences.
- **Henderson–Hasselbalch solubility** with no salt effects, common-ion effects
  or solid-form changes.
- **Colonic parameters are SYNTHBODY defaults**, not measurements.
- **Permeability is an input SYNTHBODY cannot measure.** In the shipped
  theophylline benchmark it is `inferred`, which is why that benchmark sweeps it
  rather than relying on one number.

See [BENCHMARK.md](BENCHMARK.md) for what was and was not demonstrated.

## 5. Pharmacodynamics — every parameter is illustrative

Three standard structures are implemented and numerically verified. **No
pharmacodynamic dataset ships with SYNTHBODY, and no concentration-effect
values were extracted from any publication.**

The theophylline Emax curve (E0 = 0, Emax = 30% FEV1 improvement, EC50 = 10
mg/L, γ = 1) demonstrates that the PK/PD machinery works. It is **not** a
prediction of bronchodilator response. The only claim being relied upon from
the cited literature is the qualitative one: that theophylline bronchodilation
increases with concentration across roughly 5–20 mg/L.

`kin`, `kout`, `ke0`, `EC50`, `IC50`, `Imax` and `Emax` are not identifiable
from concentration data alone. They require paired concentration-and-effect
measurements, which SYNTHBODY does not have.

---

## 6. The reference concentration band

The theophylline band shipped as 10–20 mg/L is the **historical** therapeutic
range and is **actively contested**: later clinical opinion favours lower
targets (roughly 5–15 mg/L) because toxicity rises steeply above 20 mg/L.

SYNTHBODY presents it as an **adjustable reference band**, not a clinical
target, and recommends no concentration. The "time in range" and "target
attainment" metrics are descriptive properties of a simulated profile or
cohort, not clinical target-attainment claims.

---

## 7. Numerical limitations

These are the honest edges of the computation:

- **AUC(0–∞)** extrapolates using the terminal rate constant. Above ~20%
  extrapolated fraction it is unreliable; the engine warns and the UI colours
  the field. The terminal phase itself is selected automatically by adjusted R²,
  which can pick a poor window on noisy or short profiles.
- **AUC(τ)** for multiple-dose runs is anchored to the interval following the
  **last** dose, and the window used is reported. If the horizon ends less than
  one interval after the last dose, the value **understates** interval exposure
  and the engine says so explicitly.
- **Comparing AUC across scenarios with different intervals** integrates over
  different window lengths. The comparison notes say this; the numbers do not
  enforce it.
- **Sensitivity indices** are only as good as the sample size. Sobol confidence
  intervals widen sharply at small sample counts, and the first-order sum is
  reported so you can see when interactions dominate.
- **Local sensitivity** is valid only at the nominal parameter set and is blind
  to interactions. The step-halving check tells you when the finite difference
  itself is not converged.
- **Monte Carlo percentiles** are sampling estimates. At 250 subjects the 5th
  and 95th percentiles still move noticeably between seeds.
- **Correlation matrices** supplied by the operator need not be positive
  semi-definite. SYNTHBODY projects them onto the nearest PSD matrix rather
  than sampling from something that is not a distribution — but the result is
  not exactly the correlation that was requested.
- **Parameter draws that hit a bound are truncated**, which biases the sampled
  distribution. The count of truncated draws is reported.

---

## 8. What is not modelled at all

Each of these is proposed in the white paper and absent here. The Systems
workspace lists them in the application, too, so the absence is visible at the
point of use.

**Physiology**: blood-brain barrier, active transporters, biliary excretion,
enterohepatic recirculation, metabolite tracking, protein-binding displacement,
intra-organ gradients, lymphatic transport.

**Biological systems**: immune system and cytokine networks, endocrine feedback
axes (HPA, HPT, HPG), circadian rhythms, neurotransmitter release and reuptake,
metabolic networks and ATP accounting, microbiome, cardiac electrophysiology
and haemodynamics, disease progression of any kind, gene expression.

**Data integration**: genomic/transcriptomic/proteomic input, imaging-derived
parameterisation, wearable sensor streams, HL7/FHIR EHR integration,
population priors from UK Biobank / GTEx / NHANES.

**Inference**: machine-learned correction of predictions, reinforcement
learning for treatment optimisation, graph neural networks, federated learning,
and **any form of dosing recommendation or clinical decision support.**

That last exclusion is deliberate and is not a roadmap item. A recommendation
engine resting on models validated against 18 subjects would be unsafe
regardless of how its reasoning were presented.

---

## 9. Known software limitations

- **SQLite by default.** Fine for single-operator research use; not a
  multi-tenant deployment. PostgreSQL is supported via `SYNTHBODY_DATABASE_URL`
  but is untested at scale here.
- **No authentication.** The API is unauthenticated and intended for localhost
  use. Do not expose it to a network without putting authentication in front.
- **Synchronous, CPU-bound simulation.** A 2000-subject cohort will block a
  worker for minutes. Hard caps exist (`max_population_subjects`,
  `max_sensitivity_samples`) to stop a single request wedging the process, but
  there is no job queue.
- **Reproduction is implemented for deterministic runs only.** Population runs
  are reproducible by seed but do not go through the hash-comparison path.
- **The audit log is append-only, not tamper-proof.** It supports
  reconstructing what was run; it is not a cryptographic ledger, and SYNTHBODY
  makes no such claim.
- **The input hash covers only what determines the numbers** (model, version,
  engine revision, parameter names/values/units, inputs, seed). Evidence
  metadata is covered by a separate record hash, so improving a citation does
  not invalidate a stored reproducibility hash.

---

## 10. Honest summary

SYNTHBODY implements roughly 10% of the white paper's surface area, to a
standard where the claims can be checked.

What it demonstrates is that a narrow, properly validated pharmacokinetic
platform is buildable today with classical methods, laptop hardware, and openly
licensed data — and that doing it honestly means saying "not implemented" far
more often than "implemented".

The gap between the paper's ambition and this MVP is not primarily a software
gap. It is a **data and validation gap**. The equations for most of the missing
systems are published and implementable in days. What does not exist is the
licensed, linked, individual-level data needed to parameterise them for a human
and then demonstrate that the result predicts anything. Until that exists,
implementing them would produce impressive curves with no evidential content —
which is precisely the failure mode this document exists to prevent.

See **[ROADMAP.md](ROADMAP.md)** for what each next step would actually require.
