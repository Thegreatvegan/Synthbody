# SYNTHBODY — Roadmap toward a multi-organ digital twin

The gap between this MVP and the white paper's vision is not primarily a
software gap. The equations for most of the missing systems are published and
implementable in days. **What does not exist is the licensed, linked,
individual-level data needed to parameterise them for a human and then
demonstrate that the result predicts anything.**

So this roadmap is ordered by *evidence availability*, not by implementation
difficulty. Each item states what it would take to make the capability real
rather than decorative.

Effort estimates assume a small team (2–4 people) with the stated expertise.

---

## Phase 1 — Deepen the validated core
*Target: 3–6 months · the cheapest real increase in scientific credibility*

The MVP's narrowest weakness is that 18 subjects and 198 observations support
everything it claims. Phase 1 widens the evidence base without widening scope.

| # | Item | What it requires | Why it matters |
| --- | --- | --- | --- |
| 1.1 | **Non-linear mixed-effects estimation (FOCE or SAEM)** | Pharmacometrician + 2–3 months. `nlmixr2`/`Pumas` as reference implementations for cross-checking. | The single highest-value item. Two-stage fitting gives an *upper bound* on between-subject variability, which makes every population percentile band wider than the truth. Proper NLME turns variability from a caveat into an estimate. |
| 1.2 | **Licensed multiple-dose and IV datasets** | Data licensing effort, not engineering. Candidates: published open-access PK studies with digitisable profiles; commercial datasets from a pharma partner. | Unlocks validation for accumulation, steady state, and absolute (rather than apparent) CL and V. Makes `F` identifiable. |
| 1.3 | **Transit-compartment absorption** (Savic et al. 2007) | 1–2 weeks. Reference already in the library. | The current single-depot model with a lag is the weakest structural element — theophylline `ka` has a 120% CV, which says the absorption model is wrong, not just imprecise. |
| 1.4 | **Visual predictive check and NPDE** | 2–3 weeks; Comets et al. 2008 already in the reference library. | SYNTHBODY currently reports prediction-interval *coverage*, which is a weaker diagnostic. VPC/NPDE is what a reviewer expects. |
| 1.5 | **Expand to 8–10 well-characterised compounds** | Mostly curation. Obach et al. 2008 (670 compounds) is the obvious source once licensing is cleared. | Three compounds, one of them synthetic, is a demo. Ten validated compounds is a tool. |
| 1.6 | **Bayesian parameter estimation with priors** | 1–2 months; PyMC or Stan. | Enables individual-level estimation from sparse data — the actual mechanism behind the paper's "diagnostic-driven personalisation", done defensibly. |
| 1.7 | **Job queue for long runs** | 1–2 weeks; Celery or RQ. | A 2000-subject cohort currently blocks a worker. Needed before any multi-user deployment. |
| 1.8 | **Authentication and per-user isolation** | 2–3 weeks. | Prerequisite for anything beyond localhost. |

**Phase 1 exit criterion.** At least five compounds independently validated
against held-out data, with NLME-estimated variability, and at least one
validated for multiple dosing.

---

## Phase 2 — Make the PBPK model validated rather than research-only
*Target: 6–12 months*

The PBPK model is the structural foundation for everything multi-organ. Right
now it passes one scalar check. Phase 2 makes it a model you can read tissue
concentrations from.

| # | Item | What it requires |
| --- | --- | --- |
| 2.1 | **Rodgers & Rowland partitioning** (2005/2006) | 3–4 weeks. Both references already in the library. Fixes the known failure mode for moderate-to-strong bases, which Poulin–Theil handles badly. |
| 2.2 | **Measured physicochemistry instead of computed descriptors** | Data licensing. The current log P is PubChem's *computed* XLogP3, and fu and B:P are inferred or illustrative. Experimental values exist in commercial databases. |
| 2.3 | **Validate against observed concentration-time data** | A compound with measured log P, fu, B:P **and** an open PK profile. This is the item that changes `research_only` to something stronger. |
| 2.4 | **Permeability-limited distribution** for relevant tissues | 1–2 months. Needed before any claim about tissue exposure for poorly permeable compounds. |
| 2.5 | **Blood–brain barrier model** | 2–3 months + CNS exposure data. **The highest-priority safety fix in the product**: brain is currently an ordinary perfusion compartment, so CNS concentrations are overestimated for actively excluded compounds. |
| 2.6 | **IVIVE: in-vitro CLint → in-vivo clearance** | 1–2 months. Microsomal/hepatocyte scaling factors. Turns `CLint_H` from an illustrative input into a predicted quantity. |
| 2.7 | **Enterohepatic recirculation** | 3–4 weeks. The indomethacin dataset already demonstrates the need: the source study reports recirculation and the 2-cmt model cannot reproduce it. |
| 2.8 | **Cross-validate against PK-Sim** | 1 month. The Open Systems Pharmacology suite is GPLv2 and is the field's reference implementation. Agreement with it would be meaningful external corroboration. |
| 2.9 | **Paediatric and geriatric physiology** | 2–3 months + ICRP/age-dependent datasets. Ontogeny of CYP enzymes is published. |

**Phase 2 exit criterion.** PBPK model predicts plasma concentration-time
profiles for at least three compounds within 2-fold on held-out data, and the
BBB limitation is removed or quantified.

---

## Phase 3 — Pharmacodynamics and the first biological system
*Target: 12–24 months*

Everything up to here is exposure. Phase 3 is the first honest step toward
*effect*.

| # | Item | What it requires |
| --- | --- | --- |
| 3.1 | **A licensed PK/PD dataset** | The gating item. Every PD parameter in the MVP is illustrative because no paired concentration-and-effect data ships. Without this, nothing in Phase 3 can be validated. |
| 3.2 | **Validated Emax / indirect-response models** | Once 3.1 exists, the structures are already implemented and verified. |
| 3.3 | **Tolerance and rebound** | 1–2 months. Needed for any chronic-dosing claim. |
| 3.4 | **Pharmacogenomic covariate model** | 2–4 months + a genotype-linked PK dataset. Start with CYP2D6 and CYP1A2 phenotype categories → clearance multipliers. **This is the realistic version of the paper's "genomic personalisation"** — a validated covariate effect, not a molecular simulation. |
| 3.5 | **One biological system, done properly: glucose–insulin** | 4–6 months. The Bergman minimal model is published, identifiable from an oral glucose tolerance test, and OGTT data is comparatively available. Chosen deliberately as the system most likely to be *validatable*. |
| 3.6 | **Biomarker turnover models** | 2–3 months. Connects exposure to measurable biomarkers (CRP, HbA1c), which is the first genuinely clinically interesting output. |

**Phase 3 exit criterion.** At least one concentration–effect relationship
validated against held-out data, and one physiological system (glucose–insulin)
validated against OGTT data.

---

## Phase 4 — Multi-system coupling
*Target: 2–4 years*

Only worth attempting once Phases 1–3 have established that the single-system
models actually predict. Coupling unvalidated models multiplies their errors.

| # | Item | What it requires |
| --- | --- | --- |
| 4.1 | **Spatial PDE solver** (FEniCSx or FiPy) | 3–6 months. Prerequisite for tumour microenvironment, transdermal delivery, inflammation gradients. |
| 4.2 | **HPA axis** | 4–6 months + serial cortisol/ACTH data. The equations are in the white paper and are standard; the data to individualise and validate them is the obstacle. |
| 4.3 | **Cytokine network and inflammation** | 6–12 months + longitudinal cytokine panels. |
| 4.4 | **Cardiovascular haemodynamics** (time-varying elastance + Windkessel) | 4–6 months. Published and tractable; couples to drug effect on blood pressure. |
| 4.5 | **Systems-biology model import** (SBML / BioModels) | 3–4 months. Lets validated published models be loaded rather than reimplemented — the single highest-leverage item in this phase. |
| 4.6 | **Inter-system coupling framework** | 6–12 months. The hard part is not the plumbing; it is demonstrating that coupled predictions are better than uncoupled ones. |
| 4.7 | **Metabolic network with ATP accounting** | 6–12 months. KEGG licensing must be cleared; Reactome is an open alternative. |

**Phase 4 exit criterion.** At least two coupled systems where the coupled
prediction demonstrably outperforms the uncoupled ones on held-out data.

---

## Phase 5 — Regulatory and clinical pathway
*Target: 3–7 years · runs in parallel from Phase 2 onward*

| # | Item | What it requires |
| --- | --- | --- |
| 5.1 | **Quality management system (ISO 13485 / IEC 62304)** | Regulatory consultant + 12–18 months. Must start *before* clinical ambitions, not after. |
| 5.2 | **Model qualification dossiers** | Per model. FDA and EMA both publish PBPK qualification expectations; each model needs its own documented intended-use context. |
| 5.3 | **Prospective clinical comparison** | A clinical collaboration. The only thing that converts "validated against a published dataset" into "validated". |
| 5.4 | **Regulatory engagement** | FDA Model-Informed Drug Development meetings, EMA scientific advice. |
| 5.5 | **Data protection** (HIPAA/GDPR) if real patient data is ever used | Legal + security engineering. The MVP deliberately avoids this by working with synthetic data only. |
| 5.6 | **Independent verification** | A third party reproducing the validation results from source. |

---

## Explicitly not on the roadmap

These are excluded on principle, not deferred:

| Not pursuing | Why |
| --- | --- |
| **Quantum computing** | The white paper's premise that classical computing cannot do this is incorrect for pharmacokinetics. PBPK and population PK are used in regulatory submissions today, on laptops. If binding-affinity prediction later matters, tensor-network methods are the realistic classical route — and that is a research project, not a platform feature. |
| **Dosing recommendations / AI copilot** | A recommendation engine resting on models validated against 18 subjects would be unsafe regardless of how its reasoning were presented. This stays excluded until the underlying models carry clinical-grade validation — and at that point it is a regulated medical device, with everything that implies. |
| **Blockchain notarisation** | Hashing a result and writing it to a ledger proves only that *a* hash existed at a time. It adds no guarantee about the correctness of the science or the integrity of the software stack, while signalling an assurance level the product cannot honour. |
| **Full molecular dynamics / protein folding** | Out of scope for exposure prediction, and a solved problem elsewhere (AlphaFold, GROMACS). Integration, not reimplementation, if ever needed. |
| **"Chemical twin" as a product claim** | The term implies a completeness no software can currently deliver. SYNTHBODY describes what it models and lists what it does not. |

---

## The commercial sequence

Each phase has a distinct audience, which is why the ordering is also a
go-to-market sequence:

| Phase | Who it is for | What they get |
| --- | --- | --- |
| **MVP (now)** | Pharmacometrics groups, computational biology labs, teaching | A reproducible PK simulation environment with complete evidence provenance. Credible because the claims are checkable. |
| **Phase 1** | Pharma discovery and clinical pharmacology | Dose-finding and trial-design support with proper population modelling. First realistic licensing conversation. |
| **Phase 2** | Pharma DMPK, regulatory science | PBPK for first-in-human prediction and special-population extrapolation — a well-established, budgeted use case. |
| **Phase 3** | Translational medicine, biomarker strategy | Exposure–response modelling. Where the value grows substantially. |
| **Phase 4** | Systems pharmacology, academic collaboration | Research platform for multi-system QSP. |
| **Phase 5** | Regulatory submission support | The point at which clinical claims become possible. |

**The strategic argument for this ordering.** The MVP's credibility rests on
saying "not implemented" more often than "implemented", and on every number
declaring where it came from. That discipline is the asset. A platform that
claimed the whole white paper and delivered plausible curves would be easy to
dismiss after ten minutes with a pharmacometrician. A platform that validates
two models properly, shows its residuals, and lists its own failures is
something a research partner can build on — and each phase above adds scope
only when the evidence to support it arrives.
