/**
 * Competitive benchmark tab.
 *
 * Two halves, deliberately presented together:
 *
 *   1. A benchmark that RAN — a-priori oral absorption prediction on openly
 *      licensed data, with the absorption rate derived from GI physiology and
 *      physicochemistry rather than fitted.
 *
 *   2. A benchmark that was REFUSED — the head-to-head against Simcyp,
 *      GastroPlus and GI-Sim, which cannot be run because the source study's
 *      inputs and clinical observations are paywalled.
 *
 * The refusal is shown as prominently as the result. A platform that quietly
 * dropped the comparison it could not support would be the more dangerous one.
 */
import { useEffect, useState } from "react";
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
  Spinner,
  Table,
  ValidationBadge,
  cx,
} from "../components/ui";
import { api } from "../lib/api";
import { pct, seriesColour, sig } from "../lib/format";
import type { GIPhysiology, OrbitoComparison, TheophyllineBenchmark } from "../lib/types";

export function BenchmarkTab() {
  const [theo, setTheo] = useState<TheophyllineBenchmark | null>(null);
  const [orbito, setOrbito] = useState<OrbitoComparison | null>(null);
  const [gi, setGi] = useState<GIPhysiology | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([api.benchmarkOrbito(), api.giPhysiology(), api.benchmarkTheophylline()])
      .then(([o, g, t]) => {
        if (cancelled) return;
        setOrbito(o);
        setGi(g);
        setTheo(t);
        setErr(null);
      })
      .catch((e) => !cancelled && setErr(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  if (err) {
    return (
      <div className="p-3">
        <Notice tone="danger" title="Could not run the benchmark">
          {err}
        </Notice>
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1 space-y-2 overflow-auto p-2">
      <OrbitoPanel data={orbito} loading={loading} />
      <TheophyllinePanel data={theo} loading={loading} />
      {gi && <GIPhysiologyPanel data={gi} />}
    </div>
  );
}

// ===========================================================================
// The refused comparison
// ===========================================================================
function OrbitoPanel({ data, loading }: { data: OrbitoComparison | null; loading: boolean }) {
  if (loading && !data) {
    return (
      <Panel title="Head-to-head vs Simcyp / GastroPlus / GI-Sim">
        <Spinner label="Checking the benchmark case library…" />
      </Panel>
    );
  }
  if (!data) return null;
  const refused = !data.comparison_available;

  return (
    <Panel
      title="Head-to-head vs Simcyp / GastroPlus / GI-Sim"
      subtitle="Sjögren, Thörn & Tannergren 2016 · 12 drugs · 44 oral administrations"
      actions={
        <Badge tone={refused ? "danger" : "ok"}>
          {refused ? "comparison refused" : `${data.n_administrations} administrations`}
        </Badge>
      }
    >
      <div className="space-y-2">
        <div>
          <SectionLabel>Published competitor results</SectionLabel>
          <Table
            headers={[
              "Software",
              { label: "AUC AAFE", align: "right" },
              { label: "Cmax AAFE", align: "right" },
              { label: "tmax AAFE", align: "right" },
            ]}
          >
            {Object.entries(data.published_results).map(([name, m]) => (
              <Row key={name}>
                <Cell>
                  <span className="text-ink">{name}</span>
                </Cell>
                <Cell align="right" mono>{m.auc.toFixed(1)}</Cell>
                <Cell align="right" mono>{m.cmax.toFixed(1)}</Cell>
                <Cell align="right" mono>{m.tmax.toFixed(1)}</Cell>
              </Row>
            ))}
            <Row tone={refused ? "danger" : undefined}>
              <Cell>
                <span className="font-semibold text-accent">SYNTHBODY</span>
              </Cell>
              {refused ? (
                <Cell span={3} dim>
                  <span className="text-danger">not computed — see below</span>
                </Cell>
              ) : (
                <>
                  <Cell align="right" mono>{sig(data.synthbody_results?.auc, 3)}</Cell>
                  <Cell align="right" mono>{sig(data.synthbody_results?.cmax, 3)}</Cell>
                  <Cell align="right" mono>{sig(data.synthbody_results?.tmax, 3)}</Cell>
                </>
              )}
            </Row>
          </Table>
          <Hint>{data.published_results_provenance}</Hint>
        </div>

        {refused ? (
          <>
            <Notice tone="danger" title="This comparison was refused, not failed">
              {data.refusal_reason}
            </Notice>

            <div>
              <SectionLabel>Access record — why the data is unobtainable</SectionLabel>
              <Table headers={["Check", "Result"]} compact>
                {Object.entries(data.access_record)
                  .filter(([k]) => k !== "consequence")
                  .map(([k, v]) => (
                    <Row key={k}>
                      <Cell dim>{k.replace(/_/g, " ")}</Cell>
                      <Cell mono className="text-ink-dim">{String(v)}</Cell>
                    </Row>
                  ))}
              </Table>
            </div>

            <div>
              <SectionLabel>What would be needed to run it</SectionLabel>
              <ul className="space-y-1">
                {(data.what_would_be_needed ?? []).map((x, i) => (
                  <li key={i} className="flex gap-2 text-xs leading-relaxed text-ink-dim">
                    <span className="text-ink-ghost">—</span>
                    <span>{x}</span>
                  </li>
                ))}
              </ul>
              <Notice tone="info" compact>
                {data.how_to_supply}
              </Notice>
            </div>
          </>
        ) : (
          <Notice tone={data.equivalent_experiment_count ? "info" : "warn"} title="Comparability">
            {data.comparability_caveat}
          </Notice>
        )}
      </div>
    </Panel>
  );
}

// ===========================================================================
// The benchmark that ran
// ===========================================================================
function TheophyllinePanel({ data, loading }: { data: TheophyllineBenchmark | null; loading: boolean }) {
  const [showSubject, setShowSubject] = useState<string | null>(null);

  if (loading && !data) {
    return (
      <Panel title="A-priori oral absorption benchmark">
        <Spinner label="Running the absorption model across the permeability sweep…" />
      </Panel>
    );
  }
  if (!data || !data.headline_result) return null;

  const h = data.headline_result;
  const m = h.evaluation.metrics;
  const selected = showSubject
    ? h.case_results.find((c) => c.case_id.split("-")[1] === showSubject)
    : h.case_results[0];

  const profile: PlotSeries[] = selected
    ? [
        {
          id: "pred",
          label: `Subject ${selected.case_id.split("-")[1]} predicted`,
          x: selected.time_h,
          y: selected.concentration,
          colour: "#3fd3bd",
          width: 1.8,
        },
      ]
    : [];

  const ovp: PlotSeries[] = [
    {
      id: "cmax",
      label: "Cmax",
      x: m.cmax?.observed ?? [],
      y: m.cmax?.predicted ?? [],
      colour: seriesColour(0),
      kind: "points",
      pointRadius: 4,
    },
    {
      id: "auc",
      label: "AUC",
      x: m.auc?.observed ?? [],
      y: m.auc?.predicted ?? [],
      colour: seriesColour(1),
      kind: "points",
      pointRadius: 4,
      hollow: true,
    },
  ];

  return (
    <Panel
      title="A-priori oral absorption benchmark — executed"
      subtitle={`${data.dataset.name} · held-out subjects ${data.held_out_subject_ids.join(", ")}`}
      actions={<ValidationBadge status="research_only" />}
    >
      <div className="space-y-2">
        <Notice tone="info" compact title="What is being tested">
          The absorption rate is derived entirely from gastric emptying, intestinal transit and
          permeability — it is <strong>never fitted</strong> to these profiles. Disposition comes
          from the calibration subjects only; the subjects shown are held out.
        </Notice>

        <div className="grid grid-cols-1 gap-2 lg:grid-cols-3">
          <div>
            <SectionLabel>Headline (pre-specified inputs)</SectionLabel>
            <Metric label="Mean predicted fabs" value={h.mean_predicted_fabs} tone="accent" />
            {(["auc", "cmax", "tmax"] as const).map((k) =>
              m[k]?.available ? (
                <Metric
                  key={k}
                  label={`${k.toUpperCase()} AAFE`}
                  value={m[k].aafe}
                  tone={m[k].aafe < 1.3 ? "ok" : m[k].aafe < 2.0 ? "warn" : "danger"}
                  hint={`AFE ${m[k].afe.toFixed(3)} · ${pct(m[k].fraction_within_2_fold, 0)} within 2-fold · n=${m[k].n}`}
                />
              ) : null,
            )}
          </div>

          <div>
            <SectionLabel>Physicochemical inputs</SectionLabel>
            {Object.entries(data.physchem).map(([k, v]) => (
              <div key={k} className="border-b border-line/40 py-1 last:border-0">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-xs text-ink-faint" title={v.source}>
                    {k.replace(/_/g, " ")}
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="font-mono text-xs text-ink">{sig(v.value, 4)}</span>
                    <OriginBadge origin={v.origin} />
                  </span>
                </div>
              </div>
            ))}
            <Hint>
              Permeability is <em>inferred</em>, so it is swept rather than chosen. The headline
              uses the value fixed before any result was computed.
            </Hint>
          </div>

          <div>
            <SectionLabel>Sensitivity to the inferred permeability</SectionLabel>
            <Table
              compact
              headers={[
                { label: "Peff", align: "right" },
                { label: "fabs", align: "right" },
                { label: "Cmax", align: "right" },
                { label: "tmax", align: "right" },
              ]}
            >
              {data.peff_sweep.map((s) => {
                const isHeadline =
                  Math.abs(s.peff_cm_per_s - data.prespecified_peff_cm_per_s) < 1e-12;
                return (
                  <Row key={s.peff_cm_per_s} selected={isHeadline}>
                    <Cell align="right" mono>
                      {s.peff_cm_per_s.toExponential(0)}
                      {isHeadline && <span className="ml-1 text-accent">◂</span>}
                    </Cell>
                    <Cell align="right" mono>{s.mean_predicted_fabs.toFixed(3)}</Cell>
                    <Cell align="right" mono>
                      {s.evaluation.metrics.cmax?.aafe.toFixed(3) ?? "—"}
                    </Cell>
                    <Cell align="right" mono dim>
                      {s.evaluation.metrics.tmax?.aafe.toFixed(3) ?? "—"}
                    </Cell>
                  </Row>
                );
              })}
            </Table>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-2 xl:grid-cols-2">
          <div className="group/plot">
            <SectionLabel>Predicted vs observed (identity + 2-fold envelope)</SectionLabel>
            <Plot
              series={ovp}
              identityLine
              foldLines={[2]}
              xLabel="Observed"
              yLabel="Predicted"
              xScale="log"
              yScale="log"
              height={260}
              onExportName="synthbody-apriori-pred-vs-obs"
            />
          </div>
          <div className="group/plot">
            <SectionLabel>
              Predicted profile
              <span className="ml-2 font-normal normal-case tracking-normal">
                {h.case_results.map((c) => {
                  const sid = c.case_id.split("-")[1]!;
                  const on = (showSubject ?? h.case_results[0]!.case_id.split("-")[1]) === sid;
                  return (
                    <button
                      key={sid}
                      onClick={() => setShowSubject(sid)}
                      className={cx(
                        "ml-1 rounded-xs border px-1 text-2xs",
                        on
                          ? "border-accent bg-accent-wash text-accent"
                          : "border-line text-ink-faint hover:text-ink",
                      )}
                    >
                      {sid}
                    </button>
                  );
                })}
              </span>
            </SectionLabel>
            <Plot
              series={profile}
              xLabel="Time"
              xUnit="h"
              yLabel="Plasma concentration"
              yUnit="mg/L"
              height={260}
              onExportName="synthbody-apriori-profile"
            />
          </div>
        </div>

        <div>
          <SectionLabel>Per-subject results (held out)</SectionLabel>
          <Table
            compact
            headers={[
              "Subject",
              { label: "Dose", align: "right" },
              { label: "fabs", align: "right" },
              { label: "AUC pred", align: "right" },
              { label: "AUC obs", align: "right" },
              { label: "Cmax pred", align: "right" },
              { label: "Cmax obs", align: "right" },
              { label: "tmax pred", align: "right" },
              { label: "tmax obs", align: "right" },
            ]}
          >
            {h.case_results.map((c) => (
              <Row key={c.case_id}>
                <Cell>
                  <span className="text-ink">{c.case_id.split("-")[1]}</span>
                </Cell>
                <Cell align="right" mono dim>{c.dose_mg.toFixed(0)}</Cell>
                <Cell align="right" mono>{c.predicted_fabs.toFixed(3)}</Cell>
                <Cell align="right" mono>{c.predicted_auc.toFixed(1)}</Cell>
                <Cell align="right" mono dim>{c.observed_auc?.toFixed(1)}</Cell>
                <Cell align="right" mono>{c.predicted_cmax.toFixed(2)}</Cell>
                <Cell align="right" mono dim>{c.observed_cmax?.toFixed(2)}</Cell>
                <Cell align="right" mono>{c.predicted_tmax_h.toFixed(2)}</Cell>
                <Cell align="right" mono dim>{c.observed_tmax_h?.toFixed(2)}</Cell>
              </Row>
            ))}
          </Table>
        </div>

        <Notice tone="warn" title="Scope — read before quoting any of these numbers">
          {data.honest_scope}
        </Notice>
        <Hint>{data.interpretation}</Hint>
        <Hint>{data.headline_note}</Hint>
      </div>
    </Panel>
  );
}

// ===========================================================================
// GI physiology behind the model
// ===========================================================================
function GIPhysiologyPanel({ data }: { data: GIPhysiology }) {
  const prov = data.provenance as Record<string, Record<string, unknown>>;
  const primary = prov["primary_source"] ?? {};
  const si = data.small_intestine;

  return (
    <Panel
      title="GI physiology behind the absorption model"
      subtitle="fasted state"
      actions={<Badge tone="ok">open access</Badge>}
    >
      <div className="grid grid-cols-1 gap-2 lg:grid-cols-3">
        <div>
          <SectionLabel>Stomach</SectionLabel>
          <Metric label="pH" value={data.stomach["ph"]} />
          <Metric label="Volume" value={data.stomach["volume_mL"]} unit="mL" />
          <Metric label="Half-emptying time" value={data.stomach["half_emptying_min"]} unit="min" />
          <Metric label="Emptying rate" value={data.stomach["emptying_rate_per_h"]} unit="1/h" />
        </div>
        <div>
          <SectionLabel>Small intestine</SectionLabel>
          <Metric label="Transit compartments" value={si.n_compartments} digits={2} />
          <Metric label="Total transit time" value={si.total_transit_min} unit="min" />
          <Metric label="Transit rate per compartment" value={si.transit_rate_per_h} unit="1/h" />
          <Metric label="Total liquid volume" value={si.total_volume_mL} unit="mL" />
          <Metric label="Length" value={si.length_cm} unit="cm" />
          <Metric label="Radius" value={si.radius_cm} unit="cm" />
        </div>
        <div>
          <SectionLabel>Regional pH and bile salts</SectionLabel>
          <Table compact headers={["#", { label: "pH", align: "right" }, { label: "Bile salt mM", align: "right" }]}>
            {si.ph_profile.map((ph, i) => (
              <Row key={i}>
                <Cell dim>SI {i + 1}</Cell>
                <Cell align="right" mono>{ph.toFixed(2)}</Cell>
                <Cell align="right" mono dim>{si.bile_salt_mM[i]?.toFixed(2)}</Cell>
              </Row>
            ))}
          </Table>
        </div>
      </div>

      <div className="mt-2 space-y-1.5">
        <Notice tone="ok" compact title="Primary source — retrieved and used">
          {String(primary["citation"] ?? "")}{" "}
          {primary["pmid"] ? `(PMID ${primary["pmid"]}, ${primary["pmc"]})` : ""}
        </Notice>
        <Hint>{String(primary["extraction_method"] ?? "")}</Hint>
        <Notice tone="warn" compact>
          {String((prov["honest_caveat"] as unknown) ?? "")}
        </Notice>
      </div>
    </Panel>
  );
}
