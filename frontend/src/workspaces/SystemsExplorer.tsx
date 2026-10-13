/**
 * Biological Systems Explorer.
 *
 * Draws the compartments and transport paths of the *currently selected model*
 * and nothing else. This is the important constraint: a diagram of a liver with
 * twelve metabolic pathways would be a lie when the active model is a
 * one-compartment fit with a single clearance term. What you see here is
 * exactly what the ODEs represent.
 *
 * When a PBPK model is selected the diagram becomes a real whole-body perfusion
 * map, with organ volumes and blood flows taken from the shipped physiology
 * dataset and partition coefficients predicted for the current compound.
 */
import { useEffect, useState } from "react";
import { Plot, type PlotSeries } from "../components/charts/Plot";
import {
  Badge,
  Button,
  Cell,
  EmptyState,
  Hint,
  Metric,
  Notice,
  Panel,
  Row,
  SectionLabel,
  Table,
  Tabs,
  ValidationBadge,
} from "../components/ui";
import { api } from "../lib/api";
import { pct, prettyUnit, sig, tissueColour } from "../lib/format";
import { useStore } from "../lib/store";
import type { PbpkStructuralCheck, PhysiologyResponse } from "../lib/types";

export function SystemsExplorer() {
  const setup = useStore((s) => s.setup);
  const models = useStore((s) => s.models);
  const spec = models.find((m) => m.model_id === setup.modelId) ?? null;
  const isPbpk = setup.modelId === "pbpk_perfusion_limited";
  const [tab, setTab] = useState<"diagram" | "physiology" | "partition" | "transport">("diagram");

  const [phys, setPhys] = useState<PhysiologyResponse | null>(null);
  const [check, setCheck] = useState<PbpkStructuralCheck | null>(null);

  useEffect(() => {
    void api.physiology().then(setPhys).catch(() => setPhys(null));
    void api.pbpkCheck().then(setCheck).catch(() => setCheck(null));
  }, []);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="shrink-0 border-b border-line bg-panel px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-ink">Biological systems in the active model</h2>
          {spec && <ValidationBadge status={spec.validation_status} full />}
          <Badge mono>{spec?.short_name ?? setup.modelId}</Badge>
          <span className="ml-auto text-2xs text-ink-faint">
            {spec?.observables.length ?? 0} outputs · {spec?.parameters.length ?? 0} parameters
          </span>
        </div>
        <Notice tone="info" compact>
          This view shows only the compartments and transport paths the active computational model
          actually represents. Switching model structure changes the diagram, because the biology
          SYNTHBODY can claim to simulate changes with it.
        </Notice>
      </div>

      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "diagram", label: "Compartment diagram" },
          { id: "physiology", label: "Reference physiology", badge: phys ? undefined : <Badge>…</Badge> },
          { id: "partition", label: "Tissue partitioning", badge: isPbpk ? undefined : <Badge>PBPK only</Badge> },
          { id: "transport", label: "What is not modelled" },
        ]}
      />

      <div className="min-h-0 flex-1 overflow-auto p-2">
        {tab === "diagram" && (isPbpk ? <PbpkDiagram check={check} /> : <CompartmentDiagram />)}
        {tab === "physiology" && <PhysiologyTable phys={phys} />}
        {tab === "partition" &&
          (isPbpk ? (
            <PartitionView check={check} />
          ) : (
            <EmptyState title="Tissue partitioning applies to the PBPK model only">
              The compartmental models have no tissue compartments: their volume of distribution is
              a single lumped parameter, not a sum over organs. Select the whole-body PBPK model to
              see predicted partition coefficients.
            </EmptyState>
          ))}
        {tab === "transport" && <NotModelled />}
      </div>
    </div>
  );
}

// ===========================================================================
// Compartmental diagram
// ===========================================================================
function CompartmentDiagram() {
  const setup = useStore((s) => s.setup);
  const models = useStore((s) => s.models);
  const lastRun = useStore((s) => s.lastRun);
  const spec = models.find((m) => m.model_id === setup.modelId);
  if (!spec) return null;

  const id = spec.model_id;
  const states = lastRun?.states ?? {};
  const t = lastRun?.time_h ?? [];

  // Peak amount in each state, used to size the compartment fill.
  const peak = (name: string) => {
    const s = states[name];
    return s ? Math.max(...s) : 0;
    };
  const allPeak = Math.max(1e-12, ...Object.keys(states).map(peak));

  const boxes: {
    key: string;
    label: string;
    sub: string;
    x: number;
    y: number;
    w: number;
    h: number;
    colour: string;
    state?: string;
  }[] = [];
  const arrows: { from: string; to: string; label: string; curve?: number }[] = [];

  if (id === "pk_1cmt_foa" || id === "pk_1cmt_mm") {
    boxes.push(
      { key: "depot", label: "Absorption depot", sub: "gut lumen", x: 40, y: 110, w: 130, h: 62, colour: "#ef9a63", state: "A_depot_mg" },
      { key: "central", label: "Central compartment", sub: "plasma + rapidly equilibrating tissue", x: 260, y: 110, w: 170, h: 62, colour: "#3fd3bd", state: "A_central_mg" },
      { key: "elim", label: "Eliminated", sub: id === "pk_1cmt_mm" ? "saturable pathway" : "first-order clearance", x: 520, y: 110, w: 130, h: 62, colour: "#67727c", state: "A_eliminated_mg" },
    );
    arrows.push(
      { from: "depot", to: "central", label: "ka" },
      { from: "central", to: "elim", label: id === "pk_1cmt_mm" ? "Vmax·C/(Km+C)" : "CL/V" },
    );
  } else if (id === "pk_2cmt") {
    boxes.push(
      { key: "depot", label: "Depot", sub: "oral only", x: 30, y: 180, w: 110, h: 56, colour: "#ef9a63", state: "A_depot_mg" },
      { key: "central", label: "Central", sub: "V1", x: 230, y: 180, w: 150, h: 56, colour: "#3fd3bd", state: "A_central_mg" },
      { key: "periph", label: "Peripheral", sub: "V2", x: 230, y: 50, w: 150, h: 56, colour: "#a98bdc", state: "A_peripheral_mg" },
      { key: "elim", label: "Eliminated", sub: "CL", x: 470, y: 180, w: 130, h: 56, colour: "#67727c", state: "A_eliminated_mg" },
    );
    arrows.push(
      { from: "depot", to: "central", label: "ka" },
      { from: "central", to: "periph", label: "Q/V1" },
      { from: "periph", to: "central", label: "Q/V2", curve: 1 },
      { from: "central", to: "elim", label: "CL/V1" },
    );
  }

  const byKey = new Map(boxes.map((b) => [b.key, b]));

  return (
    <div className="space-y-2">
      <Panel title="Compartment structure" subtitle={spec.name}>
        <svg viewBox="0 0 700 290" className="w-full" style={{ maxHeight: 300 }}>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 1 L 9 5 L 0 9 z" fill="#67727c" />
            </marker>
          </defs>

          {arrows.map((a, i) => {
            const f = byKey.get(a.from)!;
            const tb = byKey.get(a.to)!;
            const fx = f.x + f.w;
            const fy = f.y + f.h / 2;
            const tx = tb.x;
            const ty = tb.y + tb.h / 2;
            // Vertical pairs need a different anchor than horizontal ones.
            const vertical = Math.abs(f.y - tb.y) > 40;
            let d: string;
            let lx: number;
            let ly: number;
            if (vertical) {
              const x = f.x + f.w / 2 + (a.curve ? 26 : -26);
              const y1 = a.curve ? tb.y + tb.h : f.y;
              const y2 = a.curve ? f.y : tb.y + tb.h;
              d = `M${x},${y1} L${x},${y2}`;
              lx = x + 6;
              ly = (y1 + y2) / 2;
            } else {
              d = `M${fx},${fy} L${tx},${ty}`;
              lx = (fx + tx) / 2;
              ly = fy - 8;
            }
            return (
              <g key={i}>
                <path d={d} stroke="#67727c" strokeWidth={1.3} markerEnd="url(#arrow)" fill="none" />
                <text x={lx} y={ly} textAnchor="middle" className="fill-ink-faint font-mono" style={{ fontSize: 10 }}>
                  {a.label}
                </text>
              </g>
            );
          })}

          {boxes.map((b) => {
            const p = b.state ? peak(b.state) : 0;
            const fill = allPeak > 0 ? Math.min(1, p / allPeak) : 0;
            return (
              <g key={b.key}>
                <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={3} fill="#101418" stroke={b.colour} strokeWidth={1.4} />
                {/* Fill bar indicating the peak amount this compartment held. */}
                {fill > 0 && (
                  <rect
                    x={b.x + 1}
                    y={b.y + b.h - 5}
                    width={(b.w - 2) * fill}
                    height={4}
                    fill={b.colour}
                    opacity={0.65}
                  />
                )}
                <text x={b.x + b.w / 2} y={b.y + 22} textAnchor="middle" className="fill-ink" style={{ fontSize: 11, fontWeight: 600 }}>
                  {b.label}
                </text>
                <text x={b.x + b.w / 2} y={b.y + 36} textAnchor="middle" className="fill-ink-faint" style={{ fontSize: 9 }}>
                  {b.sub}
                </text>
                {b.state && p > 0 && (
                  <text x={b.x + b.w / 2} y={b.y + 50} textAnchor="middle" className="fill-ink-dim font-mono" style={{ fontSize: 9 }}>
                    peak {sig(p, 4)} mg
                  </text>
                )}
              </g>
            );
          })}
        </svg>
        {!lastRun && (
          <Hint>
            Run a simulation and each compartment will show the peak amount it held, with the bar
            at its base scaled to that peak.
          </Hint>
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
        <Panel title="Model states" subtitle="the actual ODE state vector">
          <Table headers={["State", { label: "Peak amount", align: "right" }, "Unit"]}>
            {Object.keys(states).length === 0
              ? spec.observables.map((o) => (
                  <Row key={o.name}>
                    <Cell>{o.label}</Cell>
                    <Cell align="right" dim>
                      —
                    </Cell>
                    <Cell dim mono>
                      {prettyUnit(o.unit)}
                    </Cell>
                  </Row>
                ))
              : Object.keys(states).map((n) => (
                  <Row key={n}>
                    <Cell mono>{n}</Cell>
                    <Cell align="right" mono>
                      {sig(peak(n), 4)}
                    </Cell>
                    <Cell dim mono>
                      mg
                    </Cell>
                  </Row>
                ))}
          </Table>
          {t.length > 0 && (
            <div className="mt-2">
              <StateFluxPlot />
            </div>
          )}
        </Panel>

        <Panel title="Assumptions this structure makes" scroll>
          <ul className="space-y-1.5">
            {spec.assumptions.map((a, i) => (
              <li key={i} className="flex gap-1.5 text-xs leading-relaxed text-ink-dim">
                <span className="text-ink-ghost">·</span>
                <span>{a}</span>
              </li>
            ))}
          </ul>
          <SectionLabel>Limitations</SectionLabel>
          <ul className="space-y-1.5">
            {spec.limitations.map((a, i) => (
              <li key={i} className="flex gap-1.5 text-xs leading-relaxed text-warn/90">
                <span className="text-warn">!</span>
                <span>{a}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}

function StateFluxPlot() {
  const lastRun = useStore((s) => s.lastRun);
  if (!lastRun) return null;
  const series: PlotSeries[] = Object.entries(lastRun.states).map(([name, y], i) => ({
    id: name,
    label: name.replace(/^A_/, "").replace(/_mg$/, "").replace(/_/g, " "),
    x: lastRun.time_h,
    y,
    colour: ["#ef9a63", "#3fd3bd", "#a98bdc", "#67727c", "#5aa9e6"][i % 5]!,
    width: 1.3,
  }));
  return (
    <Plot
      series={series}
      xLabel="Time"
      xUnit="h"
      yLabel="Amount"
      yUnit="mg"
      height={190}
    />
  );
}

// ===========================================================================
// PBPK diagram
// ===========================================================================
function PbpkDiagram({ check }: { check: PbpkStructuralCheck | null }) {
  const lastRun = useStore((s) => s.lastRun);

  // Layout: arterial spine on the left, venous spine on the right, organs
  // between. Gut and spleen route through the liver, which is the point of
  // drawing it this way rather than as a star.
  const organs = [
    { name: "brain", y: 24 },
    { name: "heart", y: 66 },
    { name: "muscle", y: 108 },
    { name: "adipose", y: 150 },
    { name: "skin", y: 192 },
    { name: "bone", y: 234 },
    { name: "rest", y: 276 },
    { name: "kidney", y: 318 },
  ];
  const portal = [
    { name: "gut", y: 372 },
    { name: "spleen", y: 408 },
  ];

  const peakC = (tissue: string) => {
    const s = lastRun?.observables[`C_${tissue}`];
    return s ? Math.max(...s) : null;
  };
  const allPeak = Math.max(
    1e-12,
    ...[...organs, ...portal, { name: "liver" }, { name: "lung" }]
      .map((o) => peakC(o.name) ?? 0),
  );

  const AX = 148;
  const VX = 470;
  const OX = 212;
  const OW = 196;

  const organBox = (name: string, y: number, h = 30) => {
    const kp = check?.partition_coefficients[name];
    const vol = check?.tissue_volumes_L[name];
    const flow = check?.tissue_flows_L_per_h[name];
    const p = peakC(name);
    const fill = p != null && allPeak > 0 ? Math.min(1, p / allPeak) : 0;
    return (
      <g key={name}>
        <rect x={OX} y={y} width={OW} height={h} rx={2} fill="#101418" stroke={tissueColour(name)} strokeWidth={1.2} />
        {fill > 0 && (
          <rect x={OX + 1} y={y + h - 4} width={(OW - 2) * fill} height={3} fill={tissueColour(name)} opacity={0.7} />
        )}
        <text x={OX + 7} y={y + 13} className="fill-ink" style={{ fontSize: 10, fontWeight: 600 }}>
          {name}
        </text>
        <text x={OX + 7} y={y + 24} className="fill-ink-ghost font-mono" style={{ fontSize: 8 }}>
          {vol != null ? `${vol.toFixed(2)} L` : ""} {flow != null ? `· Q ${flow.toFixed(1)} L/h` : ""}{" "}
          {kp != null ? `· Kp ${kp.toFixed(2)}` : ""}
        </text>
        {p != null && (
          <text x={OX + OW - 7} y={y + 13} textAnchor="end" className="fill-ink-dim font-mono" style={{ fontSize: 9 }}>
            {sig(p, 3)}
          </text>
        )}
        {/* arterial in, venous out */}
        <path d={`M${AX},${y + h / 2} L${OX},${y + h / 2}`} stroke="#e2655f" strokeWidth={1} opacity={0.6} />
        <path d={`M${OX + OW},${y + h / 2} L${VX},${y + h / 2}`} stroke="#5aa9e6" strokeWidth={1} opacity={0.6} />
      </g>
    );
  };

  return (
    <div className="space-y-2">
      <Panel
        title="Whole-body perfusion map"
        subtitle="arterial spine (left) → organs → venous spine (right)"
        actions={<ValidationBadge status="research_only" full />}
      >
        <Notice tone="warn" compact title="Research only">
          {check?.honest_scope ??
            "This PBPK model has not been validated against observed concentration-time data. Tissue concentrations are model output, not exposure predictions."}
        </Notice>
        <div className="mt-2 overflow-x-auto">
          <svg viewBox="0 0 640 470" style={{ minWidth: 560, maxHeight: 470 }} className="w-full">
            {/* spines */}
            <rect x={AX - 14} y={14} width={14} height={430} rx={3} fill="#2a1416" stroke="#e2655f" strokeWidth={1.2} />
            <text transform={`translate(${AX - 20},230) rotate(-90)`} textAnchor="middle" className="fill-danger" style={{ fontSize: 9, fontWeight: 600 }}>
              ARTERIAL BLOOD
            </text>
            <rect x={VX} y={14} width={14} height={430} rx={3} fill="#0f2130" stroke="#5aa9e6" strokeWidth={1.2} />
            <text transform={`translate(${VX + 24},230) rotate(-90)`} textAnchor="middle" className="fill-info" style={{ fontSize: 9, fontWeight: 600 }}>
              VENOUS BLOOD
            </text>

            {/* lung couples venous back to arterial */}
            <rect x={OX + 30} y={430} width={136} height={30} rx={2} fill="#101418" stroke={tissueColour("lung")} strokeWidth={1.3} />
            <text x={OX + 98} y={448} textAnchor="middle" className="fill-ink" style={{ fontSize: 10, fontWeight: 600 }}>
              lung
            </text>
            <path d={`M${VX},445 L${OX + 166},445`} stroke="#5aa9e6" strokeWidth={1.2} />
            <path d={`M${OX + 30},445 L${AX - 7},445 L${AX - 7},440`} stroke="#e2655f" strokeWidth={1.2} />

            {organs.map((o) => organBox(o.name, o.y))}

            {/* portal-drained organs feed the liver, not the vena cava */}
            {portal.map((o) => (
              <g key={o.name}>
                <rect x={OX} y={o.y} width={130} height={26} rx={2} fill="#101418" stroke={tissueColour(o.name)} strokeWidth={1.2} />
                <text x={OX + 6} y={o.y + 12} className="fill-ink" style={{ fontSize: 10, fontWeight: 600 }}>
                  {o.name}
                </text>
                <text x={OX + 6} y={o.y + 22} className="fill-ink-ghost font-mono" style={{ fontSize: 8 }}>
                  Q {check?.tissue_flows_L_per_h[o.name]?.toFixed(1) ?? "—"} L/h
                </text>
                <path d={`M${AX},${o.y + 13} L${OX},${o.y + 13}`} stroke="#e2655f" strokeWidth={1} opacity={0.6} />
                <path d={`M${OX + 130},${o.y + 13} L${OX + 160},${o.y + 13} L${OX + 160},398`} stroke="#b0d17a" strokeWidth={1.2} />
              </g>
            ))}
            <text x={OX + 164} y={388} className="fill-ok font-mono" style={{ fontSize: 8 }}>
              portal vein
            </text>

            {/* liver */}
            <rect x={OX + 168} y={366} width={150} height={44} rx={2} fill="#1a1510" stroke={tissueColour("liver")} strokeWidth={1.5} />
            <text x={OX + 243} y={382} textAnchor="middle" className="fill-ink" style={{ fontSize: 11, fontWeight: 600 }}>
              liver
            </text>
            <text x={OX + 243} y={394} textAnchor="middle" className="fill-ink-ghost font-mono" style={{ fontSize: 8 }}>
              {check ? `${check.tissue_volumes_L["liver"]?.toFixed(2)} L · Kp ${check.partition_coefficients["liver"]?.toFixed(2)}` : ""}
            </text>
            <text x={OX + 243} y={405} textAnchor="middle" className="fill-warn font-mono" style={{ fontSize: 8 }}>
              well-stirred CL
              {check ? ` = ${check.hepatic_blood_clearance_L_per_h.toFixed(2)} L/h` : ""}
            </text>
            <path d={`M${AX},388 L${OX},388 L${OX},366`} stroke="#e2655f" strokeWidth={1} opacity={0.5} />
            <path d={`M${OX + 318},388 L${VX},388`} stroke="#5aa9e6" strokeWidth={1.3} />

            {/* elimination arrows */}
            <path d={`M${OX + 243},410 L${OX + 243},424`} stroke="#e0a34a" strokeWidth={1.3} />
            <text x={OX + 248} y={424} className="fill-warn font-mono" style={{ fontSize: 8 }}>
              hepatic metabolism
            </text>
            <path d={`M${OX + OW},333 L${OX + OW + 20},333`} stroke="#e0a34a" strokeWidth={1.3} />
            <text x={OX + OW + 24} y={336} className="fill-warn font-mono" style={{ fontSize: 8 }}>
              renal CL {check ? "" : ""}
            </text>
          </svg>
        </div>
        {lastRun && lastRun.model_id === "pbpk_perfusion_limited" ? (
          <Hint>
            Numbers on the right of each organ are the peak tissue concentration from the last run,
            and the bar at the base of each box is scaled to the highest peak across all tissues.
          </Hint>
        ) : (
          <Hint>
            Run the PBPK model from the Studio and each organ will show the peak tissue
            concentration this model computed for it.
          </Hint>
        )}
      </Panel>

      {check && (
        <div className="grid grid-cols-1 gap-2 lg:grid-cols-3">
          <Panel title="Flow balance">
            <Metric label="Cardiac output" value={check.cardiac_output_L_per_h} unit="L/h" />
            <Metric
              label="Cardiac output"
              value={check.cardiac_output_L_per_h / 60}
              unit="L/min"
              hint="A reference adult is around 5–7 L/min, so this is a sanity check on the physiology dataset."
              tone={
                check.cardiac_output_L_per_h / 60 > 4 && check.cardiac_output_L_per_h / 60 < 9
                  ? "ok"
                  : "warn"
              }
            />
            <Metric label="Hepatic blood clearance" value={check.hepatic_blood_clearance_L_per_h} unit="L/h" />
            <Hint>
              Cardiac output is defined as the sum of the modelled tissue flows so that what leaves
              the arterial pool exactly equals what returns. That makes the mass-balance check
              meaningful rather than approximate.
            </Hint>
          </Panel>
          <Panel title="Predicted volume of distribution">
            <Metric label="Vss (absolute)" value={check.predicted_vss_L} unit="L" origin="derived" />
            <Metric label="Vss per kg" value={check.predicted_vss_L_per_kg} unit="L/kg" origin="derived" />
            <Metric label="Literature comparison" value={check.literature_comparison_L_per_kg} unit="L/kg" origin="inferred" />
            <Metric
              label="Fold difference"
              value={check.fold_difference}
              tone={check.passes_2_fold ? "ok" : "warn"}
            />
            <Notice tone={check.passes_2_fold ? "ok" : "warn"} compact>
              {check.passes_2_fold
                ? "Within 2-fold of the widely quoted value — the single external check this module passes."
                : "Outside 2-fold of the widely quoted value."}
            </Notice>
          </Panel>
          <Panel title="Physicochemical inputs">
            {Object.entries(check.inputs)
              .filter(([k]) => !k.endsWith("_origin"))
              .map(([k, v]) => (
                <div key={k} className="flex items-baseline justify-between gap-2 border-b border-line/40 py-1 last:border-0">
                  <span className="truncate text-xs text-ink-faint">{k.replace(/_/g, " ")}</span>
                  <span className="flex items-center gap-1">
                    <span className="font-mono text-xs text-ink">{String(v)}</span>
                    {typeof check.inputs[`${k}_origin`] === "string" && (
                      <span className="text-[9px] text-ink-ghost">
                        {String(check.inputs[`${k}_origin`]).split(" ")[0]}
                      </span>
                    )}
                  </span>
                </div>
              ))}
            <Notice tone="warn" compact>
              The log P here is a computed descriptor and the blood:plasma ratio is an illustrative
              default. The Vss agreement above inherits that uncertainty.
            </Notice>
          </Panel>
        </div>
      )}
    </div>
  );
}

// ===========================================================================
// Physiology
// ===========================================================================
function PhysiologyTable({ phys }: { phys: PhysiologyResponse | null }) {
  if (!phys) return <EmptyState title="Loading reference physiology…" />;
  const prov = phys.provenance as Record<string, unknown>;
  const totalFlow = phys.tissues.reduce((a, t) => (t.name === "lung" ? a : a + t.blood_flow_L_per_h), 0);

  return (
    <div className="space-y-2">
      <Panel title="Provenance of every physiological constant">
        <div className="space-y-1.5">
          <Metric label="Source" value={String(prov["extracted_from"] ?? "")} />
          <Metric label="Licence" value={String(prov["source_license"] ?? "")} />
          <Metric label="Extraction method" value={String(prov["extraction_method"] ?? "")} />
          <Metric label="Extracted on" value={String(prov["extraction_date"] ?? "")} />
          <SectionLabel>Primary citations</SectionLabel>
          {Object.entries((prov["key_primary_citations"] ?? {}) as Record<string, Record<string, string>>).map(
            ([key, c]) => (
              <div key={key} className="rounded border border-line bg-void/40 px-2 py-1.5">
                <div className="text-2xs font-semibold uppercase tracking-wide text-ink-faint">
                  {key.replace(/_/g, " ")}
                </div>
                <div className="mt-0.5 text-xs leading-snug text-ink-dim">{c["citation"]}</div>
                <div className="mt-1 flex flex-wrap items-center gap-1">
                  {c["pmid"] && <Badge mono tone="info">PMID {c["pmid"]}</Badge>}
                  {c["doi"] && <Badge mono>DOI {c["doi"]}</Badge>}
                </div>
                {c["note"] && (
                  <Notice tone="warn" compact>
                    {c["note"]}
                  </Notice>
                )}
              </div>
            ),
          )}
        </div>
      </Panel>

      <Panel title={`Reference adult physiology (${phys.reference_body_weight_kg} kg)`} scroll>
        <div className="mb-2 grid grid-cols-2 gap-x-4 md:grid-cols-4">
          {Object.entries(phys.whole_body)
            .filter(([k, v]) => typeof v === "number" && !k.includes("note"))
            .map(([k, v]) => (
              <Metric key={k} label={k.replace(/_/g, " ")} value={v as number} />
            ))}
        </div>
        {typeof phys.whole_body["cardiac_output_note"] === "string" && (
          <Notice tone="info" compact>
            {phys.whole_body["cardiac_output_note"] as string}
          </Notice>
        )}
        <div className="mt-2">
          <Table
            headers={[
              "Tissue",
              { label: "Volume", align: "right" },
              { label: "% BW", align: "right" },
              { label: "Flow", align: "right" },
              { label: "% CO", align: "right" },
              { label: "Water", align: "right" },
              { label: "Lipid", align: "right" },
              { label: "Protein", align: "right" },
              { label: "pH", align: "right" },
              "",
            ]}
          >
            {phys.tissues.map((t) => (
              <Row key={t.name} tone={t.composition_is_borrowed ? "warn" : undefined}>
                <Cell>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-sm" style={{ background: tissueColour(t.name) }} />
                    <span className="text-ink">{t.name}</span>
                  </span>
                </Cell>
                <Cell align="right" mono>
                  {t.volume_L.toFixed(3)} L
                </Cell>
                <Cell align="right" mono dim>
                  {(t.volume_fraction_of_body_weight * 100).toFixed(2)}
                </Cell>
                <Cell align="right" mono>
                  {t.blood_flow_L_per_h.toFixed(2)}
                </Cell>
                <Cell align="right" mono dim>
                  {t.name === "lung" ? "—" : ((t.blood_flow_L_per_h / totalFlow) * 100).toFixed(1)}
                </Cell>
                <Cell align="right" mono dim>
                  {t.f_water.toFixed(3)}
                </Cell>
                <Cell align="right" mono dim>
                  {t.f_lipid_total.toFixed(3)}
                </Cell>
                <Cell align="right" mono dim>
                  {t.f_protein.toFixed(3)}
                </Cell>
                <Cell align="right" mono dim>
                  {t.ph.toFixed(2)}
                </Cell>
                <Cell>
                  {t.composition_is_borrowed && (
                    <Badge tone="warn" title="This lumped compartment has no measured composition; muscle composition is assigned as an explicit modelling assumption.">
                      borrowed
                    </Badge>
                  )}
                  {phys.portal_drained_tissues.includes(t.name) && <Badge tone="ok">portal</Badge>}
                </Cell>
              </Row>
            ))}
          </Table>
        </div>
      </Panel>
    </div>
  );
}

// ===========================================================================
// Partition
// ===========================================================================
function PartitionView({ check }: { check: PbpkStructuralCheck | null }) {
  if (!check) return <EmptyState title="Loading partition prediction…" />;
  const entries = Object.entries(check.partition_coefficients).sort((a, b) => b[1] - a[1]);
  const max = Math.max(...entries.map(([, v]) => v));

  return (
    <div className="space-y-2">
      <Panel title="Predicted tissue:plasma partition coefficients" subtitle={check.method}>
        <Notice tone="warn" compact title="Method limitation">
          The Poulin–Theil tissue-composition method is known to predict poorly for
          moderate-to-strong bases, where binding to acidic phospholipids dominates. Rodgers–Rowland
          is the appropriate method for those compounds and is not implemented in this release.
        </Notice>
        <div className="mt-2 space-y-0.5">
          {entries.map(([name, v]) => (
            <div key={name} className="flex items-center gap-2">
              <span className="w-20 shrink-0 text-xs text-ink-dim">{name}</span>
              <span className="h-3 flex-1 rounded-sm bg-raised">
                <span
                  className="block h-full rounded-sm"
                  style={{ width: `${(v / max) * 100}%`, background: tissueColour(name) }}
                />
              </span>
              <span className="w-16 shrink-0 text-right font-mono text-xs text-ink tnum">
                {v.toFixed(3)}
              </span>
              <span className="w-24 shrink-0 text-right font-mono text-2xs text-ink-ghost">
                V {check.tissue_volumes_L[name]?.toFixed(2)} L
              </span>
            </div>
          ))}
        </div>
        <div className="mt-3">
          <SectionLabel>Contribution to steady-state volume of distribution</SectionLabel>
          <Hint>
            Vss is the sum of each tissue volume multiplied by its partition coefficient, plus the
            blood compartments. A tissue can dominate Vss either by being large (muscle, adipose) or
            by partitioning strongly.
          </Hint>
          <div className="mt-1.5 space-y-0.5">
            {entries
              .map(([name, kp]) => ({ name, contrib: kp * (check.tissue_volumes_L[name] ?? 0) }))
              .sort((a, b) => b.contrib - a.contrib)
              .map(({ name, contrib }) => (
                <div key={name} className="flex items-center gap-2">
                  <span className="w-20 shrink-0 text-xs text-ink-dim">{name}</span>
                  <span className="h-2.5 flex-1 rounded-sm bg-raised">
                    <span
                      className="block h-full rounded-sm"
                      style={{
                        width: `${(contrib / check.predicted_vss_L) * 100}%`,
                        background: tissueColour(name),
                      }}
                    />
                  </span>
                  <span className="w-14 shrink-0 text-right font-mono text-xs text-ink tnum">
                    {contrib.toFixed(2)} L
                  </span>
                  <span className="w-12 shrink-0 text-right font-mono text-2xs text-ink-ghost">
                    {pct(contrib / check.predicted_vss_L, 0)}
                  </span>
                </div>
              ))}
          </div>
        </div>
      </Panel>
    </div>
  );
}

// ===========================================================================
// What is not modelled
// ===========================================================================
function NotModelled() {
  const setWorkspace = useStore((s) => s.setWorkspace);
  const sections: { title: string; items: string[] }[] = [
    {
      title: "Physiology the white paper proposes and SYNTHBODY does not implement",
      items: [
        "Blood–brain barrier transport. Brain is an ordinary perfusion-limited compartment in the PBPK model, so CNS concentrations will be overestimated for actively excluded compounds.",
        "Active transporters (P-gp, OATP, OCT, BCRP). All transport here is passive and perfusion-limited.",
        "Biliary excretion and enterohepatic recirculation. The indomethacin source study reports recirculation; the two-compartment model cannot reproduce the resulting secondary peaks.",
        "Metabolite formation and tracking. Drug is eliminated into a bookkeeping state, not transformed into named species.",
        "Protein-binding displacement interactions. Fraction unbound is a constant input.",
        "Tissue heterogeneity within an organ. Each organ is one well-mixed compartment with no gradients.",
        "Lymphatic transport as a separate circuit.",
      ],
    },
    {
      title: "Biological systems not represented at all",
      items: [
        "Immune system, cytokine networks and inflammation cascades.",
        "Endocrine feedback axes (HPA, HPT, HPG) and circadian hormone rhythms.",
        "Neurotransmitter release, reuptake and receptor dynamics.",
        "Metabolic networks (glycolysis, TCA cycle, beta-oxidation) and ATP accounting.",
        "Microbiome and host–microbe co-metabolism.",
        "Cardiac electrophysiology, haemodynamics and pressure–volume loops.",
        "Disease progression of any kind, including tumour growth and mutation.",
        "Gene expression, transcriptional regulation and multi-omic integration.",
      ],
    },
    {
      title: "Capabilities that require data SYNTHBODY does not have",
      items: [
        "Patient-specific calibration from genomic, transcriptomic or proteomic input.",
        "Any form of imaging-derived parameterisation.",
        "Machine-learned correction of model predictions: there is no training corpus here, and an unvalidated learned correction would be worse than none.",
        "Non-linear mixed-effects (population) estimation. SYNTHBODY uses two-stage fitting and says so.",
      ],
    },
  ];

  return (
    <div className="space-y-2">
      <Notice tone="info" title="Why this page exists">
        A simulation platform is most dangerous where it is silent. These are the systems the
        SYNTHBODY white paper describes that this MVP does not implement. Nothing in the interface
        will produce a number for any of them, and no part of the product should be read as
        covering them.
      </Notice>
      {sections.map((s) => (
        <Panel key={s.title} title={s.title}>
          <ul className="space-y-1.5">
            {s.items.map((i, k) => (
              <li key={k} className="flex gap-2 text-xs leading-relaxed">
                <span className="shrink-0 text-ink-ghost">—</span>
                <span className="text-ink-dim">{i}</span>
              </li>
            ))}
          </ul>
        </Panel>
      ))}
      <div className="flex justify-center pb-2">
        <Button variant="subtle" onClick={() => setWorkspace("evidence")}>
          See the full feasibility assessment in the Evidence workspace
        </Button>
      </div>
    </div>
  );
}
