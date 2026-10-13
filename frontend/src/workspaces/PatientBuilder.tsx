/**
 * Virtual Patient Builder.
 *
 * Builds hypothetical simulated subjects. The word "patient" is used because
 * that is the term of art in pharmacometrics, but every surface in here states
 * that the subject is synthetic, the store enforces it, and the API refuses to
 * record anything claiming otherwise.
 *
 * Derived physiology (BSA, CrCl, eGFR, fat-free mass) is computed by the
 * backend from published equations and each one is shown with its citation, so
 * the operator can see which formula produced which number.
 */
import { useEffect, useMemo, useState } from "react";
import { Plot, type PlotSeries } from "../components/charts/Plot";
import {
  Badge,
  Button,
  Cell,
  Field,
  Hint,
  Metric,
  Notice,
  NumberInput,
  OriginBadge,
  Panel,
  Row,
  SectionLabel,
  Select,
  Slider,
  Splitter,
  Table,
  TextArea,
  TextInput,
  useToast,
} from "../components/ui";
import { api, ApiError } from "../lib/api";
import { seriesColour, sig } from "../lib/format";
import { useStore } from "../lib/store";
import type { PatientInput, PatientPreview } from "../lib/types";

const BLANK: PatientInput = {
  label: "New virtual subject",
  age_years: 35,
  weight_kg: 70,
  height_cm: 175,
  sex: "male",
  serum_creatinine_mg_dL: 0.9,
  albumin_g_dL: 4.3,
  hepatic_function: "normal",
  smoking_status: "non_smoker",
  notes: "",
  is_synthetic: true,
};

export function PatientBuilder() {
  const patients = useStore((s) => s.patients);
  const refresh = useStore((s) => s.refreshPatients);
  const pushLog = useStore((s) => s.pushLog);
  const patchSetup = useStore((s) => s.patchSetup);
  const setWorkspace = useStore((s) => s.setWorkspace);
  const toast = useToast();

  const [editing, setEditing] = useState<number | null>(null);
  const [form, setForm] = useState<PatientInput>(BLANK);
  const [preview, setPreview] = useState<PatientPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Live derived physiology, recomputed by the backend as the form changes.
  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const p = await api.previewPatient(form);
        if (!cancelled) {
          setPreview(p);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setPreview(null);
          setError(e instanceof ApiError ? e.message : String(e));
        }
      }
    }, 180);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [form]);

  const patch = (p: Partial<PatientInput>) => setForm((f) => ({ ...f, ...p }));

  const save = async () => {
    setBusy(true);
    try {
      const saved = editing
        ? await api.updatePatient(editing, form)
        : await api.createPatient(form);
      await refresh();
      setEditing(saved.id);
      toast.push({ tone: "ok", title: editing ? "Subject updated" : "Subject created", detail: saved.label });
      pushLog({
        level: "ok",
        source: "patients",
        message: `${editing ? "Updated" : "Created"} virtual subject "${saved.label}"`,
        detail: `${saved.weight_kg} kg · ${saved.age_years} y · CrCl ${sig(
          saved.derived["creatinine_clearance_cockcroft_gault_mL_min"] as number,
          3,
        )} mL/min`,
      });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      toast.push({ tone: "danger", title: "Could not save subject", detail: msg });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: number) => {
    try {
      await api.deletePatient(id);
      await refresh();
      if (editing === id) {
        setEditing(null);
        setForm(BLANK);
      }
      toast.push({ tone: "ok", title: "Subject deleted" });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : String(e);
      toast.push({
        tone: e instanceof ApiError && e.status === 409 ? "warn" : "danger",
        title: "Could not delete subject",
        detail: msg,
      });
    }
  };

  const load = (id: number) => {
    const p = patients.find((x) => x.id === id);
    if (!p) return;
    setEditing(id);
    setForm({
      label: p.label,
      age_years: p.age_years,
      weight_kg: p.weight_kg,
      height_cm: p.height_cm,
      sex: p.sex as "male" | "female",
      serum_creatinine_mg_dL: p.serum_creatinine_mg_dL,
      albumin_g_dL: p.albumin_g_dL,
      hepatic_function: p.hepatic_function as PatientInput["hepatic_function"],
      smoking_status: p.smoking_status as PatientInput["smoking_status"],
      notes: p.notes,
      is_synthetic: true,
    });
  };

  return (
    <Splitter
      storageKey="patient-main"
      initial={0.3}
      min={0.2}
      max={0.45}
      first={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          <Panel
            title={`Stored virtual subjects (${patients.length})`}
            className="min-h-0 flex-1"
            scroll
            dense
            actions={
              <Button
                size="xs"
                variant="subtle"
                onClick={() => {
                  setEditing(null);
                  setForm(BLANK);
                }}
              >
                + New
              </Button>
            }
          >
            {patients.length === 0 ? (
              <div className="p-3 text-xs text-ink-faint">
                No subjects yet. Configure one on the right and save it. Simulations can also run
                against a default reference adult without creating a subject at all.
              </div>
            ) : (
              <Table
                compact
                headers={["Subject", { label: "kg", align: "right" }, { label: "y", align: "right" }, { label: "CrCl", align: "right" }, ""]}
              >
                {patients.map((p) => (
                  <Row key={p.id} selected={editing === p.id} onClick={() => load(p.id)}>
                    <Cell>
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-ink">{p.label}</span>
                        <Badge tone="violet" title="Hypothetical simulated subject, not a patient record">
                          SYN
                        </Badge>
                      </div>
                      <div className="text-[9px] text-ink-ghost">
                        {p.sex} · {p.hepatic_function.replace(/_/g, " ")} · {p.smoking_status.replace(/_/g, " ")}
                      </div>
                    </Cell>
                    <Cell align="right" mono>
                      {p.weight_kg}
                    </Cell>
                    <Cell align="right" mono dim>
                      {p.age_years}
                    </Cell>
                    <Cell align="right" mono dim>
                      {sig(p.derived["creatinine_clearance_cockcroft_gault_mL_min"] as number, 3)}
                    </Cell>
                    <Cell align="right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          void remove(p.id);
                        }}
                        className="text-ink-ghost hover:text-danger"
                        title="Delete this subject"
                      >
                        ✕
                      </button>
                    </Cell>
                  </Row>
                ))}
              </Table>
            )}
          </Panel>

          <Panel title="Scope of this workspace" className="shrink-0">
            <Notice tone="violet" compact title="Hypothetical subjects only">
              SYNTHBODY stores synthetic virtual subjects. The API rejects any record flagged as a
              real person, and nothing here is designed for or safe to use with identifiable patient
              data. Use published de-identified values or invented ones.
            </Notice>
          </Panel>
        </div>
      }
      second={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          <Splitter
            storageKey="patient-form"
            direction="horizontal"
            initial={0.42}
            min={0.3}
            max={0.62}
            first={
              <div className="flex min-h-0 flex-1 flex-col p-0.5">
                <Panel
                  title={editing ? `Editing subject #${editing}` : "New virtual subject"}
                  className="min-h-0 flex-1"
                  scroll
                  actions={
                    <Badge tone="violet">synthetic</Badge>
                  }
                >
                  <div className="space-y-2.5">
                    <Field label="Label" inline={false}>
                      <TextInput value={form.label} onChange={(label) => patch({ label })} />
                    </Field>

                    <SectionLabel>Body size</SectionLabel>
                    <SliderField
                      label="Body weight"
                      unit="kg"
                      value={form.weight_kg}
                      min={2}
                      max={200}
                      step={0.5}
                      onChange={(weight_kg) => patch({ weight_kg })}
                    />
                    <SliderField
                      label="Height"
                      unit="cm"
                      value={form.height_cm}
                      min={40}
                      max={220}
                      step={0.5}
                      onChange={(height_cm) => patch({ height_cm })}
                    />
                    <SliderField
                      label="Age"
                      unit="years"
                      value={form.age_years}
                      min={0.1}
                      max={100}
                      step={0.5}
                      onChange={(age_years) => patch({ age_years })}
                    />
                    <Field label="Sex (for physiological equations)" inline={false}>
                      <Select<"male" | "female">
                        value={form.sex}
                        onChange={(sex) => patch({ sex })}
                        options={[
                          { value: "male", label: "Male" },
                          { value: "female", label: "Female" },
                        ]}
                      />
                      <Hint>
                        Binary because the published equations SYNTHBODY implements (Cockcroft–Gault,
                        CKD-EPI 2021, Janmahasatian fat-free mass, Devine ideal body weight) each
                        carry a binary sex coefficient. That is a limitation of those equations, not
                        a statement about who a simulated subject represents. The limitation is
                        recorded in the scientific limitations report.
                      </Hint>
                    </Field>

                    <SectionLabel>Laboratory values</SectionLabel>
                    <SliderField
                      label="Serum creatinine"
                      unit="mg/dL"
                      value={form.serum_creatinine_mg_dL}
                      min={0.2}
                      max={8}
                      step={0.05}
                      onChange={(serum_creatinine_mg_dL) => patch({ serum_creatinine_mg_dL })}
                    />
                    <SliderField
                      label="Serum albumin"
                      unit="g/dL"
                      value={form.albumin_g_dL}
                      min={1.5}
                      max={6}
                      step={0.1}
                      onChange={(albumin_g_dL) => patch({ albumin_g_dL })}
                    />
                    <Hint>
                      Albumin is recorded and displayed but does not drive any model in this
                      release: SYNTHBODY has no validated protein-binding model, so letting it
                      change clearance would be an invented mechanism.
                    </Hint>

                    <SectionLabel>Organ function and lifestyle</SectionLabel>
                    <Field label="Hepatic function" inline={false}>
                      <Select
                        value={form.hepatic_function}
                        onChange={(hepatic_function) => patch({ hepatic_function })}
                        options={[
                          { value: "normal", label: "Normal" },
                          { value: "mild_impairment", label: "Mild impairment (×0.80 CL)" },
                          { value: "moderate_impairment", label: "Moderate impairment (×0.60 CL)" },
                          { value: "severe_impairment", label: "Severe impairment (×0.40 CL)" },
                        ]}
                      />
                      <div className="mt-1 flex items-start gap-1.5">
                        <OriginBadge origin="illustrative" />
                        <Hint>
                          The direction of this effect is supported by the cited literature; the
                          specific multipliers are SYNTHBODY defaults and are not measurements. A
                          simulation using anything other than "Normal" inherits that limitation.
                        </Hint>
                      </div>
                    </Field>
                    <Field label="Smoking status" inline={false}>
                      <Select
                        value={form.smoking_status}
                        onChange={(smoking_status) => patch({ smoking_status })}
                        options={[
                          { value: "non_smoker", label: "Non-smoker" },
                          { value: "smoker", label: "Smoker (×1.60 CL for CYP1A2 substrates)" },
                        ]}
                      />
                      <div className="mt-1 flex items-start gap-1.5">
                        <OriginBadge origin="inferred" />
                        <Hint>
                          Cigarette smoke induces CYP1A2 and raises theophylline clearance. The 1.6×
                          magnitude is a commonly quoted order of magnitude, not a value extracted
                          from a primary source.
                        </Hint>
                      </div>
                    </Field>

                    <SectionLabel>Notes</SectionLabel>
                    <TextArea
                      value={form.notes}
                      onChange={(notes) => patch({ notes })}
                      rows={3}
                      placeholder="Why this subject exists, where its values came from, what scenario it represents…"
                    />

                    {error && (
                      <Notice tone="danger" compact title="Implausible configuration">
                        {error}
                      </Notice>
                    )}

                    <div className="flex gap-1 pt-1">
                      <Button variant="primary" full loading={busy} onClick={() => void save()}>
                        {editing ? "Save changes" : "Create subject"}
                      </Button>
                      {editing && (
                        <Button
                          variant="default"
                          onClick={() => {
                            patchSetup({ patientId: editing });
                            setWorkspace("studio");
                          }}
                          title="Use this subject in the Studio and switch to it"
                        >
                          Use in Studio
                        </Button>
                      )}
                    </div>
                  </div>
                </Panel>
              </div>
            }
            second={
              <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-0.5">
                <Panel title="Derived physiology" subtitle="computed by the engine from published equations" scroll className="min-h-0 flex-1">
                  {!preview ? (
                    <div className="text-xs text-ink-faint">
                      {error ? "Fix the configuration above to see derived values." : "Computing…"}
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div>
                        <SectionLabel>Body composition</SectionLabel>
                        <Metric label="Body mass index" value={preview.derived["bmi_kg_m2"] as number} unit="" digits={4} />
                        <Metric label="Body surface area (Du Bois)" value={preview.derived["bsa_m2_du_bois"] as number} unit="m2" digits={4} />
                        <Metric label="Fat-free mass (Janmahasatian)" value={preview.derived["fat_free_mass_kg_janmahasatian"] as number} unit="kg" digits={4} />
                        <Metric label="Ideal body weight (Devine)" value={preview.derived["ideal_body_weight_kg_devine"] as number} unit="kg" digits={4} />
                      </div>
                      <div>
                        <SectionLabel>Renal function</SectionLabel>
                        <Metric
                          label="Creatinine clearance (Cockcroft–Gault)"
                          value={preview.derived["creatinine_clearance_cockcroft_gault_mL_min"] as number}
                          unit="mL/min"
                          origin="derived"
                        />
                        <Metric
                          label="eGFR (CKD-EPI 2021)"
                          value={preview.derived["egfr_ckd_epi_2021_mL_min_1_73m2"] as number}
                          unit="mL/min"
                          origin="literature_fitted"
                          hint="Normalised to 1.73 m² body surface area."
                        />
                        <Metric
                          label="eGFR de-normalised to this subject"
                          value={preview.derived["egfr_absolute_mL_min"] as number}
                          unit="mL/min"
                          origin="derived"
                        />
                        <RenalComparison preview={preview} />
                      </div>

                      <div>
                        <SectionLabel>Equations in use</SectionLabel>
                        <Table compact headers={["Quantity", "Source", "Origin"]}>
                          {preview.equations.map((e) => (
                            <Row key={e.name}>
                              <Cell title={e.formula}>
                                <span className="text-ink">{e.name}</span>
                                <div className="font-mono text-[9px] text-ink-ghost">{e.formula}</div>
                                {e.note && <div className="text-[9px] text-warn">{e.note}</div>}
                              </Cell>
                              <Cell dim>{e.citation}</Cell>
                              <Cell>
                                <OriginBadge origin={e.origin as never} />
                              </Cell>
                            </Row>
                          ))}
                        </Table>
                      </div>

                      <div className="space-y-1">
                        {preview.caveats.map((c, i) => (
                          <Notice key={i} tone="warn" compact>
                            {c}
                          </Notice>
                        ))}
                      </div>
                    </div>
                  )}
                </Panel>

                <CovariateImpact form={form} />
              </div>
            }
          />
        </div>
      }
    />
  );
}

function SliderField({
  label,
  unit,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  unit: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <Field label={label} unit={unit}>
        <NumberInput value={value} min={min} max={max} step={step} onChange={onChange} />
      </Field>
      <Slider min={min} max={max} step={step} value={value} onChange={onChange} />
    </div>
  );
}

/** Shows how far apart the two renal-function equations are for this subject. */
function RenalComparison({ preview }: { preview: PatientPreview }) {
  const cg = preview.derived["creatinine_clearance_cockcroft_gault_mL_min"] as number;
  const eg = preview.derived["egfr_absolute_mL_min"] as number;
  if (!Number.isFinite(cg) || !Number.isFinite(eg) || eg === 0) return null;
  const ratio = cg / eg;
  const disagree = Math.abs(ratio - 1) > 0.2;
  return (
    <Notice tone={disagree ? "warn" : "neutral"} compact>
      Cockcroft–Gault and CKD-EPI disagree by {((ratio - 1) * 100).toFixed(0)}% for this subject
      {disagree
        ? ". That is worth noticing: Cockcroft–Gault uses total body weight and overestimates in obesity, while CKD-EPI is body-surface-normalised. Which one a dosing rule intends matters."
        : "."}
    </Notice>
  );
}

/**
 * Runs the current model twice — once with covariates applied and once without
 * — so the operator can see exactly how much the subject's covariates move the
 * prediction, rather than taking it on trust.
 */
function CovariateImpact({ form }: { form: PatientInput }) {
  const setup = useStore((s) => s.setup);
  const drugs = useStore((s) => s.drugs);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ with: number[]; without: number[]; t: number[]; aucWith: number; aucWithout: number; cmaxWith: number; cmaxWithout: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const drug = drugs.find((d) => d.drug_id === setup.drugId);

  const hasCovariateModel = useMemo(
    () => Boolean(drug && Object.keys(drug.covariates ?? {}).length > 0),
    [drug],
  );

  const compute = async () => {
    setBusy(true);
    setErr(null);
    try {
      // The subject must exist server-side to be referenced, so this uses a
      // transient subject: create, simulate twice, delete.
      const created = await api.createPatient({ ...form, label: `${form.label} (preview)` });
      try {
        const base = {
          model_id: setup.modelId,
          drug_id: setup.drugId,
          parameters: setup.parameters,
          regimen: setup.regimen,
          simulation_horizon_h: setup.horizonH,
          n_output_points: 241,
          patient_id: created.id,
          persist: false,
        };
        const [a, b] = await Promise.all([
          api.simulate({ ...base, label: "with covariates", apply_patient_covariates: true }),
          api.simulate({ ...base, label: "without covariates", apply_patient_covariates: false }),
        ]);
        setResult({
          t: a.time_h,
          with: a.observables[a.primary_observable] ?? [],
          without: b.observables[b.primary_observable] ?? [],
          aucWith: a.nca.auc_0_last,
          aucWithout: b.nca.auc_0_last,
          cmaxWith: a.nca.cmax,
          cmaxWithout: b.nca.cmax,
        });
      } finally {
        await api.deletePatient(created.id).catch(() => {});
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const series: PlotSeries[] = result
    ? [
        { id: "without", label: "Covariates off", x: result.t, y: result.without, colour: seriesColour(2), dash: "4 3" },
        { id: "with", label: "Covariates applied", x: result.t, y: result.with, colour: seriesColour(0), width: 1.8 },
      ]
    : [];

  return (
    <Panel
      title="Covariate impact"
      subtitle="how much this subject's covariates actually move the prediction"
      className="max-h-[46%] shrink-0"
      scroll
      actions={
        <Button size="xs" variant="default" loading={busy} onClick={() => void compute()}>
          Compute
        </Button>
      }
    >
      {!hasCovariateModel && (
        <Notice tone="neutral" compact>
          The selected compound ({drug?.name ?? "none"}) has no covariate model, so only body-size
          scaling would apply. Pick a compound with declared covariates — theophylline has smoking
          and hepatic-function terms — to see a difference.
        </Notice>
      )}
      {err && (
        <Notice tone="danger" compact title="Could not compute">
          {err}
        </Notice>
      )}
      {!result ? (
        <Hint>
          Press Compute to run the current Studio setup twice against this subject, once with
          covariate adjustment and once without. The two curves are the honest answer to "does this
          covariate matter here?"
        </Hint>
      ) : (
        <div className="space-y-2">
          <Plot
            series={series}
            xLabel="Time"
            xUnit="h"
            yLabel="Plasma concentration"
            yUnit="mg/L"
            height={180}
            showLegend
          />
          <div className="grid grid-cols-2 gap-x-4">
            <Metric label="Cmax with covariates" value={result.cmaxWith} unit="mg/L" />
            <Metric label="Cmax without" value={result.cmaxWithout} unit="mg/L" />
            <Metric label="AUC with covariates" value={result.aucWith} unit="mg·h/L" />
            <Metric label="AUC without" value={result.aucWithout} unit="mg·h/L" />
            <Metric
              label="AUC change"
              value={`${(((result.aucWith - result.aucWithout) / result.aucWithout) * 100).toFixed(1)}%`}
              tone={Math.abs(result.aucWith / result.aucWithout - 1) > 0.2 ? "warn" : undefined}
            />
          </div>
          <Notice tone="warn" compact>
            A large difference here is driven partly by multipliers SYNTHBODY labels illustrative or
            inferred. The size of the effect is not evidence; only its direction is supported.
          </Notice>
        </div>
      )}
    </Panel>
  );
}
