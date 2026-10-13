# SYNTHBODY — Technical Feasibility Matrix

An assessment of every major component proposed in *Project SYNTHBODY:
Quantum-Driven Virtual Human Replication for Personalized Medical Simulation*
(Cruxeon, S. Lovell, 16 April 2025, 175 pp.), mapped to what this MVP actually
implements with classical computing.

**Reading the status column**

| Status | Meaning |
| --- | --- |
| ✅ **Implemented** | Built, numerically verified, and (where a dataset exists) validated against observed data. |
| 🟦 **Simplified** | Built, but with a documented reduction in scope or fidelity relative to the paper. |
| 🟨 **Not implemented** | The science exists and is published, but the data needed to parameterise *and validate* it does not exist in a form this MVP can access. Building it would produce output with no evidential content. |
| 🟥 **Infeasible / excluded** | Not achievable today at the claimed scale, or deliberately excluded on safety grounds. |

The central editorial decision: **the paper's vision is preserved; its
unsupported claims are not implemented as though they were established.** Where
a capability could only be faked, it is absent and labelled absent, in the
application as well as in this document.

---

## 1. Quantum computing architecture (white paper §IV.A, §VI.A.3–4, §VII.1)

| Component | Paper's claim | Status | Assessment |
| --- | --- | --- | --- |
| Quantum simulation as the computational core | "The only viable computational framework capable of modeling the true biochemical behavior of the human body at atomic and molecular resolution" | 🟥 | The claim conflates two different problems. Predicting **drug exposure** is a differential-equation problem at the organ and whole-body scale; it does not require electronic-structure accuracy. Predicting **binding affinity** from first principles is an electronic-structure problem, and is genuinely beyond current hardware at useful scale and accuracy. SYNTHBODY solves the first problem well and does not attempt the second. |
| VQE / QAOA for binding energy minimisation | Primary use case for QPU access | 🟥 | Not implemented. Current devices cannot reach chemical accuracy for drug-sized ligand–protein systems. Implementing a toy VQE circuit would be theatre. |
| Jordan–Wigner / Bravyi–Kitaev mapping, Trotter–Suzuki circuit synthesis | §VI.D.2 workflow | 🟥 | Not implemented. Correct as textbook quantum chemistry; irrelevant to the MVP use case. |
| Qubit counts, error correction, coherence budgets (§IV.A.2–4) | 10³–10⁶ logical qubits | 🟥 | Not applicable. Recorded here so a reader knows the omission is deliberate. |
| Tensor network methods (§VI.A.4) | Classical approximation of quantum states | 🟨 | Not implemented. Would be the *realistic* classical route to the paper's molecular ambitions, and is a long-term roadmap item — but it answers a question (binding affinity) that the MVP does not need to answer. |

**Bottom line.** No part of SYNTHBODY claims quantum computation, and the
product does not need it. The paper's framing of classical computing as
incapable is incorrect for pharmacokinetics: PBPK and population PK are
routinely used in regulatory submissions today, on laptops.

---

## 2. Biochemical modelling engine (§IV.B)

| Component | Paper's claim | Status | Assessment |
| --- | --- | --- | --- |
| Michaelis–Menten enzyme kinetics | §IV.B.3.a, used across organ modules | ✅ | Implemented as `pk_1cmt_mm` with analytic Jacobian. Verified to reduce to first-order kinetics when C ≪ Km and to produce supra-proportional exposure above Km. `structurally_verified` only — no licensed non-linear PK dataset ships. |
| Competitive inhibition, Hill cooperativity, time-varying Vmax | §IV.B.3.a.4 | 🟨 | Hill cooperativity is implemented in the PD layer. Competitive inhibition and transcriptionally driven Vmax(t) are not: both need enzyme-level data SYNTHBODY has no access to. |
| Hormonal feedback (HPA axis) | §IV.B.3.b, coupled ODEs with circadian forcing | 🟨 | Not implemented. The equations are real and the structure is standard, but individualising α, β, γ and the circadian phase for a human — and then validating the result — requires serial hormone sampling data that is not openly available. An HPA simulation here would be a plausible-looking curve with no evidential content. |
| Neurotransmitter release / binding / reuptake | §IV.B.3.c, 3-compartment synaptic ODEs | 🟨 | Not implemented, same reason. Synaptic concentrations are not measurable in a living human, so nothing could validate it. |
| Lipid metabolism and ATP yield | §IV.B.3.d | 🟨 | Not implemented. Stoichiometric ATP accounting is well established, but ties to whole-body outcomes only through parameters that would be invented. |
| Metabolic / immunologic graph topology from KEGG, Reactome, BioCyc | §IV.B.1.b | 🟨 | Not implemented. Licensing was a real constraint (KEGG requires a commercial licence for redistribution), and a topology without validated kinetic parameters produces structure without prediction. |
| Layered abstraction: organ → system → tissue → cell → molecule | §IV.B.2.a | 🟦 | Two of the five layers are implemented: **organ** (the 12-compartment PBPK model) and a lumped **systemic** layer (compartmental PK). Tissue, cell and molecular layers are not. The Systems workspace shows exactly which layers the active model represents and nothing more. |
| Mass flow control, Fick's law diffusion, active transport | §IV.B.2.b.1 | 🟦 | Perfusion-limited transport is implemented with exact flow balance and a verified mass-balance check. Fick's-law *spatial* diffusion and ATP-dependent active transport are not: no PDE solver and no transporter model. |
| Circadian rhythms, fed/fasted cycles, feedback regulation | §IV.B.1.c | 🟨 | Not implemented. |
| Markov chains for probabilistic state transitions | §IV.B.1.c | 🟨 | Not implemented. Monte Carlo over continuous parameter distributions **is** implemented, which covers the population-variability use case the paper wanted it for. |

---

## 3. Pharmacokinetics and pharmacodynamics (§III, §V.A.3, §VI.A.1)

This is where the MVP is concentrated, because it is the part of the paper that
is genuinely achievable *and* validatable today.

| Component | Paper's claim | Status | Assessment |
| --- | --- | --- | --- |
| Compartmental PK with first-order absorption | §V.A.3 stochastic ADME layer | ✅ | `pk_1cmt_foa`. **Independently validated** on held-out Theoph subjects: AAFE 1.29, 90% within 2-fold, median absolute error 19%. Estimated CL/F and V/F independently match published adult values. |
| Two-compartment disposition | §VI.A.1 coupled ODE systems | ✅ | `pk_2cmt`. **Independently validated** on held-out Indometh subjects: AAFE 1.34, 94% within 2-fold. Absolute volumes unrecoverable because the dataset omits the dose — stated prominently everywhere. |
| Absorption: oral, IV bolus, IV infusion | §III key capabilities | 🟦 | Three routes implemented with correct discontinuity handling at dose events. Transdermal, sublingual, inhalational, rectal and intrathecal are not. Gastric emptying, pKa-dependent solubility and surface-area constraints (§V.A.3) are not modelled; absorption is a single first-order process with an optional lag. |
| Distribution: tissue compartments, organ-specific uptake | §III | 🟦 | Implemented in the PBPK model, `research_only`. Blood-brain barrier explicitly **not** modelled. |
| Metabolism: CYP450 isoform-specific | §III, "quantum-modeled enzyme interactions (e.g. CYP450 isoforms)" | 🟦 | Hepatic elimination is implemented as well-stirred clearance on unbound drug. Isoform attribution is documented metadata (theophylline → CYP1A2 ~90%) but does not drive the mathematics, and no genotype-to-clearance mapping exists. |
| Excretion: renal clearance, biliary, enterohepatic recycling | §III | 🟦 | Renal clearance implemented. Biliary excretion and enterohepatic recirculation are **not** — and the indomethacin source study reports recirculation, so that mechanism shows up as fit error rather than being represented. |
| Binding dynamics via Schrödinger-level approximation | §III | 🟥 | Not implemented. See §1. |
| Multiple-dose regimens, accumulation, steady state | §V.C.2 protocol planner | ✅ | Implemented with exact breakpoint handling. Steady-state Cmax and Cmin verified against the multiple-dose closed form to 1e-6. AUC(τ) is anchored to the interval following the **last** dose, and the window is reported so the column is interpretable. **Unvalidated**: no multiple-dose dataset ships. |
| Dose and interval comparison | §IV.E.1.b combinatorial therapy planner | ✅ | Scenario bench with exposure comparison, accumulation ratio, peak-trough fluctuation and time-in-band. |
| Sigmoid Emax concentration–effect | §IV.B.3.a.4.b Hill equation | ✅ structurally | Implemented. All shipped parameters `illustrative`. |
| Indirect response (turnover) models | implied by §III feedback claims | ✅ structurally | All four Dayneka–Garg–Jusko structures implemented and verified. No PD dataset ships. |
| Effect-compartment / hysteresis | implied by §III | ✅ structurally | Implemented and verified. |
| Stochastic PK with confidence bands | §V.A.3, "all layers run stochastically with confidence bands" | ✅ | Monte Carlo over log-normal between-subject random effects, with optional correlation and a separately-reported residual error model. Sampler verified to recover requested CV% and correlation. |

---

## 4. Whole-body physiology (§IV.B.1.a, §VI.C)

| Component | Paper's claim | Status | Assessment |
| --- | --- | --- | --- |
| Organ modules with I/O interfaces | Liver, kidney, brain, heart, pancreas | 🟦 | 12 tissue compartments with volumes, perfusion and composition, from an openly licensed dataset. They are *perfusion compartments*, not functional organ models: the liver clears drug, the kidney clears drug, and nothing else happens in any of them. |
| Blood and lymph as dynamic multiphase carriers | §IV.B.1.a | 🟦 | Arterial and venous blood pools with portal drainage from gut and spleen into the liver. Blood carries drug only — no O₂, CO₂, ions, hormones or cytokines. Lymph is not modelled. |
| Cardio-hepatic axis, neuroendocrine loop, renal-electrolyte control | §IV.B.1.a integration hubs | 🟨 | Not implemented. The portal/hepatic coupling is the only inter-organ relationship represented. |
| Physiological parameter values | §VII | ✅ | Organ volumes, perfusion, tissue composition, haematocrit, GFR and cardiac output, extracted **programmatically** from the GPL-3 US EPA `httk` dataset with per-value primary citations. Cardiac output comes out at 6.5 L/min and GFR at ~119 mL/min for a 70 kg reference adult — both physiologically correct. |
| Cardiovascular Navier–Stokes, time-varying elastance, Windkessel | §VI.C.1 | 🟨 | Not implemented. |
| Immune cascade, cytokine reaction-diffusion, T/B differentiation | §VI.C.2 | 🟨 | Not implemented. |
| Hodgkin–Huxley neural dynamics, BBB permeability | §VI.C.3 | 🟨 | Not implemented. Brain is an ordinary perfusion compartment, which the application states will overestimate CNS exposure for excluded compounds. |
| Microbiome Lotka–Volterra co-metabolism | §VI.C.4 | 🟨 | Not implemented. |
| PDE solvers (FEM/FVM/spectral) for spatial gradients | §VI.A.2 | 🟨 | Not implemented. No spatial dimension anywhere in SYNTHBODY. |

---

## 5. Patient individualisation (§III, §IV.D, §V.B)

| Component | Paper's claim | Status | Assessment |
| --- | --- | --- | --- |
| Configurable virtual subject | Age, sex, height, weight, organ function | ✅ | Implemented, with validation of physiological plausibility and live derived physiology. Every subject is flagged synthetic; the API **refuses** to store a record claiming otherwise. |
| Body-size scaling | §IV.D.2 calibration logic | ✅ | Theory-based allometric scaling (CL ∝ WT^0.75, V ∝ WT^1.0), labelled `derived`. Per-kilogram library parameterisations are resolved against the subject's actual weight. |
| Renal function | Creatinine → GFR → renal clearance factor | ✅ | Cockcroft–Gault and CKD-EPI 2021 both implemented, both cited, and the UI shows **how far apart they disagree** for the current subject rather than silently picking one. |
| Hepatic impairment | §IV.D.2, ALT/AST → Vmax | 🟦 | Category multipliers implemented, but labelled `illustrative`: the *direction* is supported by the cited studies and the *magnitude* is a SYNTHBODY default. The application says this at the point of use, and the Patient Builder can run the model with and without the adjustment so the operator sees how much it moves the answer. |
| Smoking / CYP1A2 induction | §IV.B.3.a.4.c environmental induction | 🟦 | 1.6× multiplier, labelled `inferred`. Direction well established; magnitude a commonly quoted order of magnitude, not extracted from a retrieved source. |
| Genomic personalisation (CYP2D6, CYP3A5, ALDH2 variants) | §III, §V.A.1 ethnic variants | 🟨 | Not implemented. No open, licensed dataset links genotype to pharmacokinetics in a form that could be both parameterised and validated. A pharmacogenomic *covariate* model (phenotype category → clearance multiplier) is the realistic near-term step and is on the roadmap. |
| Transcriptomic / proteomic / metabolomic input | §III, §IV.D.1 | 🟨 | Not implemented. |
| DICOM imaging → perfusion and volume segmentation | §IV.D.1 | 🟨 | Not implemented. |
| Wearable sensor streams | §IV.D.1 | 🟨 | Not implemented. |
| HL7/FHIR EHR integration | §IV.E.1.a | 🟨 | Not implemented, and deliberately so: SYNTHBODY is designed to be used with synthetic or published de-identified data, and connecting it to live clinical records would create a data-protection obligation this product cannot yet honour. |
| Population priors from UK Biobank, GTEx, NHANES | §V.B.3 | 🟨 | Not implemented. UK Biobank requires an approved application; the others would need curation work beyond MVP scope. |
| Demographic variant library (sex, ethnicity, age) | §V.A.1 | 🟦 | Partially: sex enters through the published renal and body-composition equations, and body size through allometry. There is no library of ethnically stratified genomic archetypes, because the parameters for one would be invented. Age affects only renal function, not maturation or ageing physiology. |

---

## 6. AI and machine learning (§IV.C, §IV.E.4)

| Component | Paper's claim | Status | Assessment |
| --- | --- | --- | --- |
| Adaptive learning of drug interaction patterns | §IV.C.1, from DrugBank/FAERS/TWOSIDES | 🟨 | Not implemented. |
| Reinforcement learning for treatment optimisation | §IV.C.2 | 🟥 | Deliberately excluded. An RL policy trained against a model validated on twelve healthy adults would optimise against the model's errors. |
| Multi-omic dataset training | §IV.C.3 | 🟨 | Not implemented. |
| Graph neural networks for biological interaction | §IV.C.4 | 🟨 | Not implemented. |
| Federated learning with differential privacy | §IV.D.3 | 🟨 | Not implemented. |
| AI copilot making dosing recommendations | §IV.E.4, incl. autonomous ICU alerting | 🟥 | **Deliberately excluded**, and this is the most important exclusion in the product. The paper's own examples ("Increase IV hydrocortisone to 100 mg every 6 h") are clinical decisions. Issuing them from models with this validation status would be unsafe regardless of how the reasoning were presented. SYNTHBODY reports model behaviour and leaves inference to the researcher. |
| Statistical estimation and calibration | §V.B.2 model calibration logic | ✅ | Implemented as classical regression rather than learned: weighted non-linear least squares with asymptotic standard errors, parameter correlation matrix and a condition-number identifiability check, plus two-stage population summary. Verified to recover known parameters from noise-free data to 0.1%. |
| Sensitivity analysis for parameter influence | §IV.E.3 sensitivity analysis | ✅ | Local normalised finite differences with a step-halving convergence check, Morris screening, and Sobol variance decomposition. Verified against analytic cases. |

**Note on the engine/LLM boundary.** No language model participates in any
numerical result. Every curve, metric and interval in SYNTHBODY is produced by
NumPy/SciPy code operating on declared parameters.

---

## 7. Interface, reproducibility and governance (§IV.E, §VIII)

| Component | Paper's claim | Status | Assessment |
| --- | --- | --- | --- |
| Clinician dashboard with drag-and-drop medication editor | §IV.E.1 | 🟦 | A **researcher** workspace is implemented, not a clinician dashboard: dose/interval/route controls, scenario comparison, reference bands and time-in-range. The clinical framing is deliberately dropped. |
| Researcher API (compound injection, pathway editing, telemetry, batch trials) | §IV.E.2 | 🟦 | Typed REST API with OpenAPI schema covering simulation, comparison, population and sensitivity, plus CSV/JSON/SVG export of everything shown. Pathway editing is absent because there are no pathways. Batch cohort execution is implemented as population simulation. |
| Version-locked simulation containers | §IV.E.3.a | 🟦 | Docker Compose with pinned dependency versions and a lockable image. Not per-agency sandboxing. |
| Lineage traceability: input hash, code version, parameter vector | §IV.E.3.b | ✅ | Every run records software version, engine revision, model version, every parameter **with its evidence origin and citations**, solver settings and diagnostics, under a SHA-256 input hash. The hash covers only what determines the numbers; evidence metadata is covered by a separate record hash. |
| Deterministic re-execution | §IV.E.3.d sandbox re-run | ✅ | A stored run can be re-executed and compared: input hash, engine revision, and the curve point by point. Verified bitwise identical. |
| Blockchain / ledger notarisation | §IV.E.3.c | 🟥 | **Deliberately not implemented.** Hashing a result and writing it to a ledger proves only that *a* hash existed at a time; it adds no guarantee about the correctness of the science or the integrity of the software stack. Implementing it would signal an assurance level this product cannot honour. An append-only audit log is provided instead, described accurately as not tamper-proof. |
| Regulatory / certifier mode | §IV.E.3 | 🟨 | Not implemented as a separate mode. The underlying capabilities it would need (provenance, re-execution, limitations disclosure) are present and available to everyone. |
| HIPAA / GDPR compliance | §VII.4, §VIII.1 | 🟥 | **No compliance claim is made.** The `/api/meta` endpoint reports `hipaa_compliant: false` and `gdpr_assessed: false` explicitly. Designed for synthetic and published de-identified data only. |
| FDA / EMA / TGA alignment | §VIII.1 | 🟨 | Not pursued. `fda_cleared: false`, `ce_marked: false`. The roadmap describes what alignment would actually require. |

---

## 8. Summary

| Status | Count |
| --- | --- |
| ✅ Implemented and verified | 17 |
| 🟦 Simplified with documented scope reduction | 16 |
| 🟨 Not implemented (data or licensing constraint) | 29 |
| 🟥 Infeasible or deliberately excluded | 9 |

**What this MVP is.** A pharmacokinetic simulation platform with two
independently validated compartmental models, a research-grade whole-body PBPK
model, population variability and sensitivity analysis, complete per-parameter
evidence provenance, and verified deterministic reproduction. Roughly 10% of
the white paper's surface area, built to a standard where the claims can be
checked.

**What it is not.** A chemical twin. A quantum simulator. A diagnostic system.
A dosing recommender. A medical device.

**The judgement behind that split.** The paper's unit of ambition is the whole
human body. The unit of *evidence* available today is a dozen healthy adults
given a single oral dose. Building the former on the latter would produce
software that looks like the paper and means nothing. Building a narrow thing
honestly produces something a pharmacometrician can actually use, and a
foundation the rest can be added to as the evidence arrives — which is what the
[roadmap](ROADMAP.md) describes.
