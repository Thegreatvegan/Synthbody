/**
 * Compound library.
 *
 * Shows every drug SYNTHBODY can simulate, with each stored parameter and the
 * origin tag that says how much to trust it. This is deliberately the least
 * glamorous workspace: its job is to make the evidence behind a number
 * impossible to miss before anyone builds a conclusion on it.
 */
import { useMemo, useState } from "react";
import {
  Badge,
  Button,
  Cell,
  Collapsible,
  EmptyState,
  Hint,
  Metric,
  Notice,
  OriginBadge,
  Panel,
  Row,
  SectionLabel,
  Splitter,
  Table,
  Tabs,
  ValidationBadge,
  cx,
} from "../components/ui";
import { ORIGIN_META, prettyUnit, sig } from "../lib/format";
import { useStore } from "../lib/store";
import type { ParamEntry, ParameterOrigin } from "../lib/types";

export function Compounds() {
  const drugs = useStore((s) => s.drugs);
  const originLegend = useStore((s) => s.originLegend);
  const [selected, setSelected] = useState<string>(drugs[0]?.drug_id ?? "");
  const drug = drugs.find((d) => d.drug_id === selected) ?? drugs[0] ?? null;

  return (
    <Splitter
      storageKey="compounds"
      initial={0.24}
      min={0.17}
      max={0.4}
      first={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          <Panel title={`Compound library (${drugs.length})`} className="min-h-0 flex-1" scroll dense>
            {drugs.map((d) => (
              <button
                key={d.drug_id}
                onClick={() => setSelected(d.drug_id)}
                className={cx(
                  "flex w-full flex-col gap-1 border-b border-line px-2 py-1.5 text-left transition-colors duration-120",
                  d.drug_id === drug?.drug_id ? "bg-accent-wash" : "hover:bg-raised",
                )}
              >
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-xs font-medium text-ink">{d.name}</span>
                  {d.is_synthetic_demonstration && (
                    <Badge tone="danger" title="Not a real drug">
                      SYNTHETIC
                    </Badge>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  <ValidationBadge status={d.validation_status} />
                  <span className="truncate text-[9px] text-ink-ghost">{d.therapeutic_area}</span>
                </div>
              </button>
            ))}
          </Panel>

          <Panel title="Origin legend" className="shrink-0" scroll>
            <div className="space-y-1.5">
              {(Object.keys(ORIGIN_META) as ParameterOrigin[]).map((k) => (
                <div key={k} className="flex items-start gap-1.5">
                  <OriginBadge origin={k} />
                  <span className="text-[9px] leading-snug text-ink-ghost">
                    {originLegend[k] ?? ORIGIN_META[k].explain}
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      }
      second={drug ? <CompoundDetail drugId={drug.drug_id} /> : <EmptyState title="No compounds loaded" />}
    />
  );
}

function CompoundDetail({ drugId }: { drugId: string }) {
  const drug = useStore((s) => s.drugs.find((d) => d.drug_id === drugId))!;
  const models = useStore((s) => s.models);
  const references = useStore((s) => s.references);
  const datasets = useStore((s) => s.datasets);
  const selectDrug = useStore((s) => s.selectDrug);
  const setWorkspace = useStore((s) => s.setWorkspace);
  const [tab, setTab] = useState<"parameters" | "pd" | "covariates" | "limits" | "identity">("parameters");

  const originCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const block of Object.values(drug.pk_parameters ?? {})) {
      for (const entry of Object.values(block.values)) {
        counts[entry.origin] = (counts[entry.origin] ?? 0) + 1;
      }
    }
    return counts;
  }, [drug]);

  const weakest = useMemo(() => {
    const order: ParameterOrigin[] = [
      "illustrative", "inferred", "user", "derived", "literature_fitted", "fitted", "measured",
    ];
    for (const o of order) if (originCounts[o]) return o;
    return null;
  }, [originCounts]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="shrink-0 border-b border-line bg-panel px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold tracking-tight text-ink">{drug.name}</h2>
          <ValidationBadge status={drug.validation_status} full />
          {drug.atc_class && <Badge mono>ATC {drug.atc_class}</Badge>}
          {drug.is_synthetic_demonstration && <Badge tone="danger">NOT A REAL DRUG</Badge>}
          <div className="ml-auto flex gap-1">
            <Button
              size="sm"
              variant="primary"
              onClick={() => {
                selectDrug(drug.drug_id);
                setWorkspace("studio");
              }}
            >
              Load into Studio
            </Button>
          </div>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-2xs text-ink-faint">
          <span>{drug.therapeutic_area}</span>
          <span>·</span>
          <span>{drug.mechanism_summary}</span>
        </div>
        <div className="mt-1 text-2xs text-ink-ghost">
          <span className="text-ink-faint">Elimination:</span> {drug.primary_elimination}
        </div>
      </div>

      <div className="shrink-0 space-y-1.5 border-b border-line bg-surface px-3 py-2">
        <Notice
          tone={
            drug.is_synthetic_demonstration
              ? "danger"
              : drug.validation_status === "independently_validated"
                ? "ok"
                : "warn"
          }
          title={`Validation: ${drug.validation_status.replace(/_/g, " ")}`}
        >
          {drug.validation_note}
        </Notice>
        {!drug.is_synthetic_demonstration && <Hint>{drug.why_this_drug}</Hint>}
        {weakest && (
          <div className="flex items-center gap-1.5 text-2xs text-ink-faint">
            <span>Weakest evidence class present:</span>
            <OriginBadge origin={weakest} full />
            <span className="ml-2">
              {Object.entries(originCounts)
                .map(([k, v]) => `${v} ${k}`)
                .join(" · ")}
            </span>
          </div>
        )}
      </div>

      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "parameters", label: "PK parameters" },
          { id: "pd", label: "Pharmacodynamics", badge: drug.pd_model ? undefined : <Badge>none</Badge> },
          { id: "covariates", label: "Covariates" },
          { id: "limits", label: "Limitations", badge: <Badge tone="warn">{drug.limitations.length}</Badge> },
          { id: "identity", label: "Identity & references" },
        ]}
      />

      <div className="min-h-0 flex-1 overflow-auto p-2">
        {tab === "parameters" && (
          <div className="space-y-2">
            {Object.entries(drug.pk_parameters ?? {}).map(([modelId, block]) => {
              const spec = models.find((m) => m.model_id === modelId);
              return (
                <Panel
                  key={modelId}
                  title={spec?.name ?? modelId}
                  subtitle={block.parameterisation.replace(/_/g, " ")}
                  actions={spec && <ValidationBadge status={spec.validation_status} />}
                >
                  <Notice tone="info" compact>
                    {block.note}
                  </Notice>
                  <div className="mt-2">
                    <Table
                      headers={[
                        "Parameter",
                        { label: "Value", align: "right" },
                        "Unit",
                        "Origin",
                        { label: "BSV CV%", align: "right", hint: "Between-subject variability estimated from the fit." },
                        "Provenance",
                      ]}
                    >
                      {Object.entries(block.values).map(([name, e]) => (
                        <ParamRow key={name} name={name} entry={e} />
                      ))}
                    </Table>
                  </div>
                </Panel>
              );
            })}

            <Panel title="Population variability" subtitle="used when running cohort simulations">
              <Table
                headers={["Parameter", { label: "CV%", align: "right" }, "Origin", "Note"]}
              >
                {drug.population_variability.random_effects.map((r) => (
                  <Row key={r.parameter}>
                    <Cell>
                      <span className="text-ink">{r.parameter}</span>
                    </Cell>
                    <Cell align="right" mono>
                      {r.cv_percent.toFixed(1)}
                    </Cell>
                    <Cell>
                      <OriginBadge origin={r.origin as ParameterOrigin} />
                    </Cell>
                    <Cell dim>{r.note}</Cell>
                  </Row>
                ))}
              </Table>
              <div className="mt-2">
                <SectionLabel>Residual error model</SectionLabel>
                <Metric
                  label="Proportional CV"
                  value={`${drug.population_variability.residual_error.proportional_cv_percent}%`}
                  origin={drug.population_variability.residual_error.origin as ParameterOrigin}
                />
                <Metric
                  label="Additive SD"
                  value={drug.population_variability.residual_error.additive_sd}
                  unit="mg/L"
                />
                {drug.population_variability.residual_error.caveat && (
                  <Notice tone="warn" compact>
                    {drug.population_variability.residual_error.caveat}
                  </Notice>
                )}
              </div>
            </Panel>

            {drug.reference_concentration_band && (
              <Panel title="Reference concentration band">
                <div className="flex items-center gap-2">
                  <Badge tone="warn">
                    {drug.reference_concentration_band.low}–{drug.reference_concentration_band.high}{" "}
                    {prettyUnit(drug.reference_concentration_band.unit)}
                  </Badge>
                  <span className="text-xs text-ink-dim">{drug.reference_concentration_band.label}</span>
                  <OriginBadge origin={drug.reference_concentration_band.origin as ParameterOrigin} />
                </div>
                <Notice tone="warn" compact>
                  {drug.reference_concentration_band.caveat}
                </Notice>
              </Panel>
            )}
          </div>
        )}

        {tab === "pd" &&
          (drug.pd_model ? (
            <Panel
              title={`Pharmacodynamic model: ${drug.pd_model.structure.replace(/_/g, " ")}`}
              subtitle={drug.pd_model.response_variable}
            >
              <Notice tone="danger" title="Every parameter below is illustrative">
                {drug.pd_model.caveat}
              </Notice>
              <div className="mt-2">
                <Table headers={["Parameter", { label: "Value", align: "right" }, "Unit", "Origin", "Description"]}>
                  {Object.entries(drug.pd_model.values).map(([name, e]) => (
                    <ParamRow key={name} name={name} entry={e} hideBsv />
                  ))}
                </Table>
              </div>
            </Panel>
          ) : (
            <EmptyState title="No pharmacodynamic model">
              SYNTHBODY ships no concentration–effect model for this compound. Rather than invent
              one so the interface has another curve to draw, the capability is simply absent.
            </EmptyState>
          ))}

        {tab === "covariates" &&
          (Object.keys(drug.covariates ?? {}).length === 0 ? (
            <EmptyState title="No covariate model">
              This compound has no declared covariate relationships. Body-size scaling still
              applies through the virtual subject's weight.
            </EmptyState>
          ) : (
            <div className="space-y-2">
              {Object.entries(drug.covariates).map(([name, c]) => {
                const rec = c as Record<string, unknown>;
                return (
                  <Panel key={name} title={name.replace(/_/g, " ")}>
                    <div className="space-y-1.5">
                      {rec.applies_to != null && (
                        <Metric label="Affects" value={(rec.applies_to as string[]).join(", ")} />
                      )}
                      {rec.origin != null && (
                        <div className="flex items-center gap-1.5 text-xs text-ink-dim">
                          Evidence class: <OriginBadge origin={rec.origin as ParameterOrigin} full />
                        </div>
                      )}
                      {rec.method != null && <Hint>{String(rec.method)}</Hint>}
                      {rec.multiplier_smoker != null && (
                        <Metric label="Smoker multiplier" value={Number(rec.multiplier_smoker)} />
                      )}
                      {rec.multipliers != null && (
                        <Table headers={["Category", { label: "CL multiplier", align: "right" }]}>
                          {Object.entries(rec.multipliers as Record<string, number>).map(([k, v]) => (
                            <Row key={k}>
                              <Cell>{k.replace(/_/g, " ")}</Cell>
                              <Cell align="right" mono>
                                ×{v.toFixed(2)}
                              </Cell>
                            </Row>
                          ))}
                        </Table>
                      )}
                      {rec.caveat != null && (
                        <Notice tone="warn" compact>
                          {String(rec.caveat)}
                        </Notice>
                      )}
                      {Array.isArray(rec.reference_ids) && (rec.reference_ids as string[]).length > 0 && (
                        <RefList ids={rec.reference_ids as string[]} />
                      )}
                    </div>
                  </Panel>
                );
              })}
            </div>
          ))}

        {tab === "limits" && (
          <Panel title="Declared limitations" subtitle="what this compound's models cannot tell you">
            <ul className="space-y-2">
              {drug.limitations.map((l, i) => (
                <li key={i} className="flex gap-2 text-xs leading-relaxed">
                  <span className="shrink-0 text-warn">!</span>
                  <span className="text-ink-dim">{l}</span>
                </li>
              ))}
            </ul>
            <Notice tone="neutral" compact>
              SYNTHBODY lets you run simulations outside the conditions these models were validated
              under (other routes, other populations, chronic dosing). The software does not stop
              you, but the validation status does not travel with you.
            </Notice>
          </Panel>
        )}

        {tab === "identity" && (
          <div className="space-y-2">
            <Panel title="Chemical identity">
              {Object.keys(drug.identifiers).length === 0 ? (
                <Hint>No chemical identifiers: this is not a real compound.</Hint>
              ) : (
                <div className="grid grid-cols-1 gap-x-6 md:grid-cols-2">
                  {Object.entries(drug.identifiers).map(([k, v]) => (
                    <Metric key={k} label={k.replace(/_/g, " ")} value={String(v)} />
                  ))}
                </div>
              )}
            </Panel>

            <Panel title="Validation datasets used">
              {datasets.filter((d) => d.drug === drug.drug_id).length === 0 ? (
                <Hint>
                  No observed dataset is shipped for this compound, which is why nothing about it
                  can be independently validated here.
                </Hint>
              ) : (
                datasets
                  .filter((d) => d.drug === drug.drug_id)
                  .map((d) => (
                    <Collapsible key={d.dataset_id} title={d.name} defaultOpen>
                      <div className="space-y-2">
                        <Hint>{d.description}</Hint>
                        <div className="grid grid-cols-2 gap-x-4 md:grid-cols-4">
                          <Metric label="Subjects" value={d.n_subjects} digits={3} />
                          <Metric label="Observations" value={d.n_observations} digits={4} />
                          <Metric label="Route" value={d.route.replace("_", " ")} />
                          <Metric label="Units" value={prettyUnit(d.concentration_unit)} />
                        </div>
                        <Notice tone="info" compact title="Licence">
                          {d.license_note}
                        </Notice>
                        <Notice tone="neutral" compact title="Provenance">
                          {d.provenance}
                        </Notice>
                        <SectionLabel>Known limitations of this dataset</SectionLabel>
                        <ul className="space-y-1">
                          {d.known_limitations.map((l, i) => (
                            <li key={i} className="flex gap-1.5 text-xs text-warn/90">
                              <span>!</span>
                              <span>{l}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    </Collapsible>
                  ))
              )}
            </Panel>

            <Panel title="All references cited by this compound">
              <RefList
                ids={Array.from(
                  new Set(
                    JSON.stringify(drug)
                      .match(/"reference_ids":\s*\[([^\]]*)\]/g)
                      ?.flatMap((m) => m.match(/"([a-z0-9_]+)"/g) ?? [])
                      .map((s) => s.replace(/"/g, ""))
                      .filter((s) => s !== "reference_ids") ?? [],
                  ),
                )}
              />
              {references.length === 0 && <Hint>Reference library not loaded.</Hint>}
            </Panel>
          </div>
        )}
      </div>
    </div>
  );
}

function ParamRow({
  name,
  entry,
  hideBsv,
}: {
  name: string;
  entry: ParamEntry;
  hideBsv?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const weak = entry.origin === "illustrative" || entry.origin === "inferred";
  return (
    <>
      <Row tone={entry.origin === "illustrative" ? "danger" : entry.origin === "inferred" ? "warn" : undefined}>
        <Cell>
          <button onClick={() => setOpen((o) => !o)} className="text-left text-ink hover:text-accent">
            <span className="font-mono">{name}</span>
            {(entry.caveat || entry.corroboration || entry.description) && (
              <span className="ml-1 text-ink-ghost">{open ? "▾" : "▸"}</span>
            )}
          </button>
        </Cell>
        <Cell align="right" mono>
          {sig(entry.value, 5)}
        </Cell>
        <Cell dim mono>
          {prettyUnit(entry.unit) || "—"}
        </Cell>
        <Cell>
          <OriginBadge origin={entry.origin} />
        </Cell>
        {!hideBsv && (
          <Cell align="right" mono dim>
            {entry.between_subject_cv_percent != null ? entry.between_subject_cv_percent.toFixed(1) : "—"}
          </Cell>
        )}
        <Cell dim>
          {entry.fitted_from_dataset ? (
            <span title={`Subjects: ${entry.fitted_from_subjects?.join(", ")}`}>
              fitted from <span className="font-mono text-accent">{entry.fitted_from_dataset}</span>
              {entry.fitted_from_subjects && ` (n=${entry.fitted_from_subjects.length})`}
            </span>
          ) : weak ? (
            <span className="text-warn">not from a retrieved source</span>
          ) : (
            "—"
          )}
        </Cell>
      </Row>
      {open && (
        <Row>
          <Cell span={hideBsv ? 5 : 6}>
            <div className="space-y-1.5 py-1 pl-4">
              {entry.description && <div className="text-xs text-ink-dim">{entry.description}</div>}
              {entry.corroboration && (
                <Notice tone="ok" compact title="Independent corroboration">
                  {entry.corroboration}
                </Notice>
              )}
              {entry.caveat && (
                <Notice tone="warn" compact title="Caveat">
                  {entry.caveat}
                </Notice>
              )}
              {entry.note && <Hint>{entry.note}</Hint>}
              {entry.reference_ids && entry.reference_ids.length > 0 && (
                <RefList ids={entry.reference_ids} />
              )}
            </div>
          </Cell>
        </Row>
      )}
    </>
  );
}

function RefList({ ids }: { ids: string[] }) {
  const references = useStore((s) => s.references);
  const setWorkspace = useStore((s) => s.setWorkspace);
  const found = ids.map((id) => references.find((r) => r.id === id)).filter(Boolean);
  if (found.length === 0) return null;
  return (
    <div className="space-y-1">
      {found.map((r) => (
        <div key={r!.id} className="rounded border border-line bg-void/40 px-1.5 py-1">
          <div className="text-[11px] leading-snug text-ink-dim">{r!.citation}</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-1">
            {r!.pmid && <Badge mono tone="info">PMID {r!.pmid}</Badge>}
            {r!.doi && (
              <a
                href={`https://doi.org/${r!.doi}`}
                target="_blank"
                rel="noreferrer noopener"
                className="text-[9px] font-mono text-accent hover:underline"
              >
                {r!.doi}
              </a>
            )}
            <button
              onClick={() => setWorkspace("evidence")}
              className="ml-auto text-[9px] text-ink-ghost hover:text-accent"
            >
              details →
            </button>
          </div>
          {r!.access_note && (
            <div className="mt-0.5 text-[9px] leading-snug text-ink-ghost">{r!.access_note}</div>
          )}
        </div>
      ))}
    </div>
  );
}
