/**
 * Oral PBPK concentration-time validation tab.
 *
 * This is the evidence that the whole-body PBPK module predicts an observed
 * human plasma profile, not merely a plausible volume of distribution. Until
 * this test existed, the PBPK model's only external check was a single scalar.
 *
 * The tab is built around one editorial decision: the methodology is shown
 * BEFORE the accuracy numbers. What was predicted a priori and what was
 * calibrated is the thing that makes the numbers mean anything, and a reader
 * who sees "AAFE 1.19" first will have stopped reading by the time they reach
 * it. So the top panel is the protocol, the middle is the result, and the
 * caveats are given the same visual weight as the headline.
 */
import { useEffect, useMemo, useState } from "react";
import { Plot, type PlotSeries } from "../components/charts/Plot";
import {
  Badge,
  Cell,
  Hint,
  Metric,
  Notice,
  OriginBadge,
  Panel,
  Row,
  SectionLabel,
  Select,
  Spinner,
  Table,
  Toggle,
  cx,
} from "../components/ui";
import { api } from "../lib/api";
import { pct, seriesColour, sig } from "../lib/format";
import type { PbpkOralValidation, PbpkSubjectPrediction } from "../lib/types";

export function OralPbpkValidationTab() {
  const [data, setData] = useState<PbpkOralValidation | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [logY, setLogY] = useState(false);
  const [subject, setSubject] = useState<string>("all");

  useEffect(() => {
    let cancelled = false;
    api
      .pbpkOralValidation()
      .then((d) => !cancelled && (setData(d), setErr(null)))
      .catch((e) => !cancelled && setErr(String(e)));
    return () => {
      cancelled = true;
    };
  }, []);

  if (err) {
    return (
      <div className="p-3">
        <Notice tone="danger" title="Could not run the validation">
          {err}
        </Notice>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="p-3">
        <Spinner label="Running the oral PBPK validation protocol…" />
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 space-y-2 overflow-auto p-2">
      <ProtocolPanel data={data} />
      <ResultPanel data={data} />
      <ProfilePanel
        data={data}
        logY={logY}
        onLogY={setLogY}
        subject={subject}
        onSubject={setSubject}
      />
      <GoodnessPanel data={data} />
      <SubjectTable data={data} />
      <CaveatPanel data={data} />
    </div>
  );
}

// ===========================================================================
// What was predicted and what was calibrated — shown first, deliberately
// ===========================================================================
function ProtocolPanel({ data }: { data: PbpkOralValidation }) {
  const rows: Array<{ process: string; how: string; tone: "ok" | "warn"; detail: string }> = [
    {
      process: "Distribution",
      how: "predicted a priori",
      tone: "ok",
      detail:
        "All twelve tissue:plasma partition coefficients, and therefore the volume " +
        "of distribution, computed by the Poulin–Theil method from log P, fraction " +
        "unbound and blood:plasma ratio. Never fitted.",
    },
    {
      process: "Absorption",
      how: "predicted a priori",
      tone: "ok",
      detail:
        "Gastric emptying, transit, dissolution and permeability-limited uptake from " +
        "the shipped GI physiology at the pre-specified permeability. There is no " +
        "absorption rate constant to estimate.",
    },
    {
      process: "Elimination",
      how: "calibrated out-of-sample",
      tone: "warn",
      detail:
        "One number — total plasma clearance per kg — taken from the calibration " +
        "subjects and inverted through the well-stirred model. The subjects it came " +
        "from are not the subjects it is tested on.",
    },
  ];

  return (
    <Panel
      title="Protocol"
      subtitle="What was predicted from physicochemistry, and what was not"
      actions={
        <Badge tone={data.inputs.prespecified ? "ok" : "warn"}>
          {data.inputs.prespecified
            ? "pre-specified permeability"
            : "non-pre-specified permeability"}
        </Badge>
      }
    >
      <div className="space-y-2">
        <Table headers={["Process", "Status", "How"]}>
          {rows.map((r) => (
            <Row key={r.process}>
              <Cell>
                <span className="text-ink">{r.process}</span>
              </Cell>
              <Cell>
                <Badge tone={r.tone}>{r.how}</Badge>
              </Cell>
              <Cell>
                <span className="text-muted">{r.detail}</span>
              </Cell>
            </Row>
          ))}
        </Table>

        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Metric
            label="Calibration subjects"
            value={data.calibration_subject_ids.join(", ")}
            hint="Clearance estimated here"
          />
          <Metric
            label="Held-out subjects"
            value={data.held_out_subject_ids.join(", ")}
            hint="Evaluated here — no overlap"
          />
          <Metric
            label="Calibrated CL"
            value={`${sig(data.calibrated_clearance_L_per_h_per_kg, 4)} L/h/kg`}
            hint="The only calibrated number"
          />
          <Metric
            label="Permeability"
            value={`${data.inputs.peff_cm_per_s.toExponential(1)} cm/s`}
            hint="Pre-specified, not chosen post hoc"
          />
        </div>

        <div>
          <SectionLabel>Physicochemical inputs and their evidence origin</SectionLabel>
          <Table
            headers={[
              "Input",
              { label: "Value", align: "right" },
              "Origin",
              "Source",
            ]}
          >
            {Object.entries(data.inputs.physchem).map(([name, entry]) => (
              <Row key={name}>
                <Cell>
                  <span className="font-mono text-[11px] text-ink">{name}</span>
                </Cell>
                <Cell align="right">
                  <span className="font-mono text-ink">{sig(entry.value, 4)}</span>
                </Cell>
                <Cell>
                  <OriginBadge origin={entry.origin} />
                </Cell>
                <Cell>
                  <span className="text-[11px] text-muted">{entry.source}</span>
                </Cell>
              </Row>
            ))}
          </Table>
        </div>

        <Hint>{data.protocol}</Hint>
      </div>
    </Panel>
  );
}

// ===========================================================================
// The result
// ===========================================================================
function ResultPanel({ data }: { data: PbpkOralValidation }) {
  const m = data.pointwise_metrics;
  const comparison = data.comparison_to_empirical_model;
  const pbpkAafe = Number(comparison.pbpk_held_out_aafe);
  const empiricalAafe = Number(comparison.empirical_held_out_aafe);

  return (
    <Panel
      title="Held-out accuracy"
      subtitle={`${m.n_observations} observed plasma concentrations across ${data.predictions.length} subjects`}
    >
      <div className="space-y-2">
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <Metric label="AAFE" value={sig(m.aafe, 4)} hint="Absolute average fold error" />
          <Metric
            label="AFE"
            value={sig(m.afe, 4)}
            hint={m.afe < 1 ? "Slight under-prediction" : "Slight over-prediction"}
          />
          <Metric label="Within 2-fold" value={pct(m.fraction_within_2_fold)} />
          <Metric label="Within 1.5-fold" value={pct(m.fraction_within_1_5_fold)} />
          <Metric
            label="Median abs. error"
            value={`${sig(m.median_absolute_percent_error, 3)}%`}
          />
          <Metric label="RMSE" value={`${sig(m.rmse, 3)} mg/L`} />
          <Metric
            label="R² vs identity"
            value={sig(m.r_squared_identity, 3)}
            hint="Against the line of identity, not a fitted regression"
          />
          <Metric label="Lin's CCC" value={sig(m.concordance_correlation, 3)} />
        </div>

        <div>
          <SectionLabel>Exposure metrics</SectionLabel>
          <Table
            headers={[
              "Metric",
              { label: "AAFE", align: "right" },
              { label: "AFE", align: "right" },
              { label: "Within 2-fold", align: "right" },
              "Reading",
            ]}
          >
            {(
              [
                [
                  "AUC",
                  "auc",
                  "WEAK metric. Clearance was calibrated and AUC ≈ dose × F / CL, so agreement here is partly a restatement of the calibration.",
                ],
                [
                  "Cmax",
                  "cmax",
                  "Informative. Depends on the absorption profile and the volume of distribution, both predicted.",
                ],
                [
                  "tmax",
                  "tmax",
                  "The cleanest a-priori test, and the weakest result: the model gives every subject the same absorption shape because between-subject gastric emptying is not modelled.",
                ],
              ] as const
            ).map(([label, key, reading]) => {
              const s = data.metric_summary[key];
              if (!s) return null;
              return (
                <Row key={key}>
                  <Cell>
                    <span className="text-ink">{label}</span>
                  </Cell>
                  <Cell align="right">
                    <span className="font-mono text-ink">{sig(s.aafe, 4)}</span>
                  </Cell>
                  <Cell align="right">
                    <span className="font-mono text-muted">{sig(s.afe, 4)}</span>
                  </Cell>
                  <Cell align="right">
                    <span className="font-mono text-muted">
                      {pct(s.fraction_within_2_fold)}
                    </span>
                  </Cell>
                  <Cell>
                    <span className="text-[11px] text-muted">{reading}</span>
                  </Cell>
                </Row>
              );
            })}
          </Table>
        </div>

        <Notice tone="violet" title="Compared with the empirical one-compartment model">
          <div className="space-y-1">
            <div>
              The empirical model fitted <strong>three</strong> parameters to theophylline
              (clearance, volume and an absorption rate constant) and reached AAFE{" "}
              <strong>{sig(empiricalAafe, 4)}</strong>. The PBPK model calibrated{" "}
              <strong>one</strong> and reached AAFE <strong>{sig(pbpkAafe, 4)}</strong>,
              predicting the volume of distribution and the entire absorption profile from
              physicochemistry.
            </div>
            <div className="text-muted">{String(comparison.note)}</div>
          </div>
        </Notice>

        <Hint>{data.interpretation}</Hint>
      </div>
    </Panel>
  );
}

// ===========================================================================
// Predicted versus observed profiles
// ===========================================================================
function ProfilePanel({
  data,
  logY,
  onLogY,
  subject,
  onSubject,
}: {
  data: PbpkOralValidation;
  logY: boolean;
  onLogY: (v: boolean) => void;
  subject: string;
  onSubject: (v: string) => void;
}) {
  const shown = useMemo(
    () =>
      subject === "all"
        ? data.predictions
        : data.predictions.filter((p) => p.subject_id === subject),
    [data.predictions, subject],
  );

  const series = useMemo<PlotSeries[]>(() => {
    const out: PlotSeries[] = [];
    shown.forEach((p, i) => {
      const colour = seriesColour(i);
      out.push({
        id: `pred-${p.subject_id}`,
        label: `Subject ${p.subject_id} predicted`,
        x: p.time_h,
        y: p.predicted_mg_per_L,
        colour,
        kind: "line",
        width: 1.75,
      });
      out.push({
        id: `obs-${p.subject_id}`,
        label: `Subject ${p.subject_id} observed`,
        x: p.time_h,
        y: p.observed_mg_per_L,
        colour,
        kind: "points",
        pointRadius: 3,
        hollow: true,
      });
    });
    return out;
  }, [shown]);

  return (
    <Panel
      title="Predicted versus observed profiles"
      subtitle="Lines are predictions; open markers are observed concentrations"
      actions={
        <div className="flex items-center gap-2">
          <Select
            value={subject}
            onChange={onSubject}
            options={[
              { value: "all", label: "All held-out subjects" },
              ...data.predictions.map((p) => ({
                value: p.subject_id,
                label: `Subject ${p.subject_id}`,
              })),
            ]}
          />
          <Toggle checked={logY} onChange={onLogY} label="log C" />
        </div>
      }
    >
      <Plot
        series={series}
        xLabel="Time"
        xUnit="h"
        yLabel="Plasma concentration"
        yUnit="mg/L"
        yScale={logY ? "log" : "linear"}
        height={340}
        onExportName="pbpk-oral-validation-profiles"
      />
    </Panel>
  );
}

// ===========================================================================
// Goodness of fit
// ===========================================================================
function GoodnessPanel({ data }: { data: PbpkOralValidation }) {
  const { scatter, residuals, maxValue } = useMemo(() => {
    const obs: number[] = [];
    const pred: number[] = [];
    const resTime: number[] = [];
    const resValue: number[] = [];
    for (const p of data.predictions) {
      p.observed_mg_per_L.forEach((o, i) => {
        const q = p.predicted_mg_per_L[i];
        obs.push(o);
        pred.push(q);
        resTime.push(p.time_h[i]);
        // Fold error on a log axis: 0 is perfect, +0.3 is 2-fold over.
        resValue.push(o > 0 && q > 0 ? Math.log10(q / o) : 0);
      });
    }
    const top = Math.max(...obs, ...pred) * 1.08;
    return {
      scatter: [
        {
          id: "po",
          label: "Predicted vs observed",
          x: obs,
          y: pred,
          colour: seriesColour(0),
          kind: "points" as const,
          pointRadius: 3,
        },
      ],
      residuals: [
        {
          id: "res",
          label: "log10(predicted / observed)",
          x: resTime,
          y: resValue,
          colour: seriesColour(2),
          kind: "points" as const,
          pointRadius: 3,
        },
      ],
      maxValue: top,
    };
  }, [data.predictions]);

  return (
    <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
      <Panel title="Predicted versus observed" subtitle="Identity line with 2-fold bounds">
        <Plot
          series={scatter}
          xLabel="Observed"
          xUnit="mg/L"
          yLabel="Predicted"
          yUnit="mg/L"
          xDomain={[0, maxValue]}
          yDomain={[0, maxValue]}
          identityLine
          foldLines={[2]}
          height={300}
          showLegend={false}
          onExportName="pbpk-oral-validation-identity"
        />
      </Panel>
      <Panel
        title="Residuals against time"
        subtitle="Zero is exact; ±0.30 is the 2-fold boundary"
      >
        <Plot
          series={residuals}
          xLabel="Time"
          xUnit="h"
          yLabel="log₁₀(pred / obs)"
          zeroLine
          height={300}
          showLegend={false}
          onExportName="pbpk-oral-validation-residuals"
        />
      </Panel>
    </div>
  );
}

// ===========================================================================
// Per subject
// ===========================================================================
function SubjectTable({ data }: { data: PbpkOralValidation }) {
  const fold = (predicted: number, observed: number) =>
    observed > 0 ? predicted / observed : Number.NaN;

  return (
    <Panel
      title="Per held-out subject"
      subtitle="Every prediction, with the fold error alongside it"
    >
      <Table
        headers={[
          "Subject",
          { label: "Weight", align: "right" },
          { label: "CLint,H", align: "right" },
          { label: "Vss pred", align: "right" },
          { label: "fabs", align: "right" },
          { label: "Cmax obs", align: "right" },
          { label: "Cmax pred", align: "right" },
          { label: "fold", align: "right" },
          { label: "tmax obs", align: "right" },
          { label: "tmax pred", align: "right" },
          { label: "mass bal.", align: "right" },
        ]}
      >
        {data.predictions.map((p: PbpkSubjectPrediction) => {
          const cmaxFold = fold(p.predicted_cmax, p.observed_cmax);
          const off = Math.abs(Math.log10(cmaxFold)) > Math.log10(1.5);
          return (
            <Row key={p.subject_id}>
              <Cell>
                <span className="text-ink">{p.subject_id}</span>
              </Cell>
              <Cell align="right">
                <span className="font-mono text-muted">{sig(p.weight_kg, 3)} kg</span>
              </Cell>
              <Cell align="right">
                <span className="font-mono text-muted">
                  {sig(p.hepatic_clint_L_per_h, 3)}
                </span>
              </Cell>
              <Cell align="right">
                <span className="font-mono text-muted">
                  {sig(p.predicted_vss_L_per_kg, 4)}
                </span>
              </Cell>
              <Cell align="right">
                <span className="font-mono text-muted">{sig(p.predicted_fabs, 4)}</span>
              </Cell>
              <Cell align="right">
                <span className="font-mono text-muted">{sig(p.observed_cmax, 4)}</span>
              </Cell>
              <Cell align="right">
                <span className="font-mono text-ink">{sig(p.predicted_cmax, 4)}</span>
              </Cell>
              <Cell align="right">
                <span className={cx("font-mono", off ? "text-amber" : "text-muted")}>
                  {sig(cmaxFold, 3)}×
                </span>
              </Cell>
              <Cell align="right">
                <span className="font-mono text-muted">{sig(p.observed_tmax_h, 3)} h</span>
              </Cell>
              <Cell align="right">
                <span className="font-mono text-ink">{sig(p.predicted_tmax_h, 3)} h</span>
              </Cell>
              <Cell align="right">
                <span className="font-mono text-[10px] text-muted">
                  {p.mass_balance_relative_error.toExponential(1)}
                </span>
              </Cell>
            </Row>
          );
        })}
      </Table>
      <Hint>
        Predicted tmax is nearly identical across subjects while observed tmax ranges from{" "}
        {sig(Math.min(...data.predictions.map((p) => p.observed_tmax_h)), 3)} to{" "}
        {sig(Math.max(...data.predictions.map((p) => p.observed_tmax_h)), 3)} h. That spread
        is real between-subject variability in gastric emptying, which this model does not
        represent. It is the clearest structural weakness the test exposes.
      </Hint>
    </Panel>
  );
}

// ===========================================================================
// Caveats — same visual weight as the result
// ===========================================================================
function CaveatPanel({ data }: { data: PbpkOralValidation }) {
  return (
    <Panel
      title="What this result does not establish"
      subtitle="Read before quoting any number above"
      actions={<Badge tone="warn">{data.caveats.length} caveats</Badge>}
    >
      <ul className="space-y-1.5">
        {data.caveats.map((c, i) => (
          <li key={i} className="flex gap-2 text-[12px] leading-relaxed text-muted">
            <span className="select-none text-amber">▸</span>
            <span>{c}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
