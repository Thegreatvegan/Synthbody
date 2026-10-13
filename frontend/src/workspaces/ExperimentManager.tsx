/**
 * Experiment Manager.
 *
 * Stored runs, grouped into experiments, with the one feature that makes a
 * simulation platform trustworthy: a reproduce button that re-executes a saved
 * run from its recorded request and compares the input hash, the engine
 * revision and the resulting curve point by point.
 */
import { useEffect, useState } from "react";
import {
  Badge,
  Button,
  Cell,
  EmptyState,
  Field,
  Hint,
  Metric,
  Modal,
  Notice,
  Panel,
  Row,
  SectionLabel,
  Splitter,
  Table,
  TextArea,
  TextInput,
  ValidationBadge,
  cx,
  useToast,
} from "../components/ui";
import { api, ApiError } from "../lib/api";
import { relativeTime, shortHash, sig, timestamp } from "../lib/format";
import { useStore } from "../lib/store";
import type { AuditEntry, ReproduceResult, SimulationSummary, StoredSimulation } from "../lib/types";

export function ExperimentManager() {
  const experiments = useStore((s) => s.experiments);
  const refreshExperiments = useStore((s) => s.refreshExperiments);
  const activeExperimentId = useStore((s) => s.activeExperimentId);
  const setActiveExperiment = useStore((s) => s.setActiveExperiment);
  const toast = useToast();

  const [filter, setFilter] = useState<number | null>(null);
  const [sims, setSims] = useState<SimulationSummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<StoredSimulation | null>(null);
  const [repro, setRepro] = useState<ReproduceResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [audit, setAudit] = useState<AuditEntry[]>([]);

  const loadSims = async () => {
    try {
      setSims(await api.simulations(filter != null ? { experiment_id: filter, limit: 500 } : { limit: 500 }));
    } catch {
      setSims([]);
    }
  };

  useEffect(() => {
    void loadSims();
    void api.audit(60).then((a) => setAudit(a.entries)).catch(() => setAudit([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  useEffect(() => {
    if (selected == null) {
      setDetail(null);
      return;
    }
    setRepro(null);
    void api.simulation(selected).then(setDetail).catch(() => setDetail(null));
  }, [selected]);

  const reproduce = async () => {
    if (selected == null) return;
    setBusy(true);
    try {
      const r = await api.reproduce(selected);
      setRepro(r);
      toast.push({
        tone: r.bitwise_identical ? "ok" : "warn",
        title: r.bitwise_identical ? "Exactly reproduced" : "Reproduction differed",
        detail: r.verdict,
      });
    } catch (e) {
      toast.push({
        tone: "danger",
        title: "Could not reproduce",
        detail: e instanceof ApiError ? e.message : String(e),
      });
    } finally {
      setBusy(false);
    }
  };

  const duplicate = async () => {
    if (selected == null) return;
    try {
      await api.duplicate(selected);
      await loadSims();
      toast.push({ tone: "ok", title: "Run duplicated" });
    } catch (e) {
      toast.push({ tone: "danger", title: "Could not duplicate", detail: String(e) });
    }
  };

  const removeSim = async (id: number) => {
    try {
      await api.deleteSimulation(id);
      if (selected === id) setSelected(null);
      await loadSims();
      await refreshExperiments();
    } catch (e) {
      toast.push({ tone: "danger", title: "Could not delete", detail: String(e) });
    }
  };

  return (
    <Splitter
      storageKey="exp-main"
      initial={0.22}
      min={0.16}
      max={0.38}
      first={
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-1">
          <Panel
            title={`Experiments (${experiments.length})`}
            className="max-h-[48%] shrink-0"
            scroll
            dense
            actions={
              <Button size="xs" variant="subtle" onClick={() => setNewOpen(true)}>
                + New
              </Button>
            }
          >
            <button
              onClick={() => setFilter(null)}
              className={cx(
                "flex w-full items-center gap-2 border-b border-line px-2 py-1.5 text-left text-xs",
                filter == null ? "bg-accent-wash text-ink" : "text-ink-dim hover:bg-raised",
              )}
            >
              <span className="flex-1">All stored runs</span>
              <Badge>{sims.length}</Badge>
            </button>
            {experiments.map((e) => (
              <div
                key={e.id}
                className={cx(
                  "border-b border-line",
                  filter === e.id ? "bg-accent-wash" : "hover:bg-raised",
                )}
              >
                <button
                  onClick={() => setFilter(e.id)}
                  className="w-full px-2 py-1.5 text-left"
                >
                  <div className="flex items-center gap-1.5">
                    <span className="min-w-0 flex-1 truncate text-xs text-ink">{e.name}</span>
                    <Badge>{e.n_simulations}</Badge>
                  </div>
                  {e.description && (
                    <div className="truncate text-[9px] text-ink-ghost">{e.description}</div>
                  )}
                  <div className="mt-0.5 flex items-center gap-1">
                    {e.tags.map((t) => (
                      <Badge key={t} tone="neutral">
                        {t}
                      </Badge>
                    ))}
                    <span className="ml-auto text-[9px] text-ink-ghost">{relativeTime(e.updated_at)}</span>
                  </div>
                </button>
                <div className="flex gap-1 px-2 pb-1">
                  <button
                    onClick={() => setActiveExperiment(e.id)}
                    className={cx(
                      "text-[9px]",
                      activeExperimentId === e.id ? "text-accent" : "text-ink-ghost hover:text-accent",
                    )}
                  >
                    {activeExperimentId === e.id ? "● filing new runs here" : "file new runs here"}
                  </button>
                  <button
                    onClick={async () => {
                      if (
                        !window.confirm(
                          `Delete experiment "${e.name}" and its ${e.n_simulations} stored run(s)? This cannot be undone.`,
                        )
                      )
                        return;
                      try {
                        await api.deleteExperiment(e.id);
                        if (filter === e.id) setFilter(null);
                        if (activeExperimentId === e.id) setActiveExperiment(null);
                        await refreshExperiments();
                        await loadSims();
                      } catch (err) {
                        toast.push({ tone: "danger", title: "Could not delete", detail: String(err) });
                      }
                    }}
                    className="ml-auto text-[9px] text-ink-ghost hover:text-danger"
                  >
                    delete
                  </button>
                </div>
              </div>
            ))}
          </Panel>

          <Panel title="Audit log" subtitle="state-changing actions" className="min-h-0 flex-1" scroll dense>
            {audit.length === 0 ? (
              <div className="p-2 text-xs text-ink-faint">No entries.</div>
            ) : (
              audit.map((a) => (
                <div key={a.id} className="border-b border-line/50 px-2 py-1 font-mono text-[9px]">
                  <div className="flex gap-1.5">
                    <span className="text-ink-ghost">{relativeTime(a.at)}</span>
                    <span className="text-accent">{a.action}</span>
                  </div>
                  <div className="truncate text-ink-ghost">{JSON.stringify(a.detail)}</div>
                </div>
              ))
            )}
            <div className="border-t border-line p-2">
              <Hint>
                An append-only record of what was run and when. It supports reconstructing a
                session; it is not a tamper-proof ledger and SYNTHBODY makes no such claim.
              </Hint>
            </div>
          </Panel>

          <NewExperimentModal
            open={newOpen}
            onClose={() => setNewOpen(false)}
            onCreated={async () => {
              await refreshExperiments();
              setNewOpen(false);
            }}
          />
        </div>
      }
      second={
        <Splitter
          storageKey="exp-detail"
          initial={0.48}
          min={0.3}
          max={0.7}
          first={
            <div className="flex min-h-0 flex-1 flex-col p-1">
              <Panel
                title={`Stored runs (${sims.length})`}
                className="min-h-0 flex-1"
                scroll
                dense
                actions={
                  <Button size="xs" variant="ghost" onClick={() => void loadSims()}>
                    refresh
                  </Button>
                }
              >
                {sims.length === 0 ? (
                  <EmptyState title="No stored runs">
                    Runs are stored when "Save into experiment" is set in the Studio, or whenever a
                    simulation is executed with persistence enabled. Each stored run keeps its full
                    request and provenance, so it can be re-executed later and checked for exact
                    reproduction.
                  </EmptyState>
                ) : (
                  <Table
                    compact
                    headers={[
                      "Run",
                      "Model",
                      "Type",
                      { label: "Cmax", align: "right" },
                      { label: "AUC", align: "right" },
                      { label: "ms", align: "right" },
                      "Hash",
                      "When",
                      "",
                    ]}
                  >
                    {sims.map((s) => (
                      <Row
                        key={s.id}
                        selected={selected === s.id}
                        onClick={() => setSelected(s.id)}
                        tone={!s.solver_success ? "danger" : s.solver_warning_count > 0 ? "warn" : undefined}
                      >
                        <Cell>
                          <div className="flex items-center gap-1.5">
                            <span className="truncate text-ink">{s.label}</span>
                            {s.solver_warning_count > 0 && (
                              <Badge tone="warn" title={`${s.solver_warning_count} solver warning(s)`}>
                                {s.solver_warning_count}
                              </Badge>
                            )}
                          </div>
                          {s.drug_id && <div className="text-[9px] text-ink-ghost">{s.drug_id}</div>}
                        </Cell>
                        <Cell dim mono>
                          {s.model_id}
                        </Cell>
                        <Cell>
                          <Badge tone={s.kind === "population" ? "violet" : "neutral"}>{s.kind}</Badge>
                        </Cell>
                        <Cell align="right" mono>
                          {sig(
                            (s.key_metrics["cmax"] ?? s.key_metrics["cmax_median"]) as number | null,
                            4,
                          )}
                        </Cell>
                        <Cell align="right" mono dim>
                          {sig(s.key_metrics["auc_0_last"] as number | null, 4)}
                        </Cell>
                        <Cell align="right" mono dim>
                          {(s.wall_time_s * 1000).toFixed(0)}
                        </Cell>
                        <Cell mono dim title={s.input_hash}>
                          {shortHash(s.input_hash, 7)}
                        </Cell>
                        <Cell dim title={timestamp(s.created_at)}>
                          {relativeTime(s.created_at)}
                        </Cell>
                        <Cell align="right">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              void removeSim(s.id);
                            }}
                            className="text-ink-ghost hover:text-danger"
                            title="Delete this run"
                          >
                            ✕
                          </button>
                        </Cell>
                      </Row>
                    ))}
                  </Table>
                )}
              </Panel>
            </div>
          }
          second={
            <div className="flex min-h-0 flex-1 flex-col p-1">
              <Panel
                title={detail ? `Run #${detail.id}: ${detail.label}` : "Run detail"}
                className="min-h-0 flex-1"
                scroll
                actions={
                  detail && (
                    <>
                      <Button size="xs" variant="default" loading={busy} onClick={() => void reproduce()}>
                        Reproduce
                      </Button>
                      <Button size="xs" variant="subtle" onClick={() => void duplicate()}>
                        Duplicate
                      </Button>
                    </>
                  )
                }
              >
                {!detail ? (
                  <EmptyState title="Select a run">
                    Pick a stored run to see its full request, provenance and solver diagnostics,
                    and to re-execute it for a reproducibility check.
                  </EmptyState>
                ) : (
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <ValidationBadge status={detail.validation_status} full />
                      <Badge mono>{detail.model_id}</Badge>
                      {detail.drug_id && <Badge mono tone="accent">{detail.drug_id}</Badge>}
                      <Badge>{detail.kind}</Badge>
                    </div>

                    {repro && <ReproductionReport r={repro} />}

                    <SectionLabel>Request as recorded</SectionLabel>
                    <pre className="max-h-48 overflow-auto rounded border border-line bg-void p-2 font-mono text-[9px] leading-relaxed text-ink-dim">
                      {JSON.stringify(detail.request, null, 2)}
                    </pre>

                    <SectionLabel>Reproducibility record</SectionLabel>
                    <Metric label="Input hash" value={detail.input_hash.replace("sha256:", "")} />
                    <Metric label="Record hash" value={detail.record_hash.replace("sha256:", "")} />
                    <Metric label="Engine revision" value={detail.provenance.engine_revision} />
                    <Metric label="Software version" value={detail.provenance.software_version} />
                    <Metric label="Executed" value={timestamp(detail.created_at)} />
                    <Metric label="Platform" value={detail.provenance.platform} />

                    {detail.provenance.solver && (
                      <>
                        <SectionLabel>Solver diagnostics</SectionLabel>
                        <Metric label="Method" value={detail.provenance.solver.method} />
                        <Metric label="RHS evaluations" value={detail.provenance.solver.n_rhs_evaluations} digits={8} />
                        <Metric
                          label="Mass balance error"
                          value={
                            detail.provenance.solver.mass_balance_relative_error != null
                              ? detail.provenance.solver.mass_balance_relative_error.toExponential(2)
                              : "n/a"
                          }
                          tone={
                            (detail.provenance.solver.mass_balance_relative_error ?? 0) < 1e-6
                              ? "ok"
                              : "warn"
                          }
                        />
                        {detail.provenance.solver.warnings.map((w, i) => (
                          <Notice key={i} tone="warn" compact>
                            {w}
                          </Notice>
                        ))}
                      </>
                    )}

                    <SectionLabel>Parameters</SectionLabel>
                    <Table compact headers={["Name", { label: "Value", align: "right" }, "Unit", "Origin"]}>
                      {detail.provenance.parameters.map((p) => (
                        <Row key={p.name}>
                          <Cell mono>{p.name}</Cell>
                          <Cell align="right" mono>
                            {sig(p.value, 5)}
                          </Cell>
                          <Cell dim mono>
                            {p.unit || "—"}
                          </Cell>
                          <Cell dim>{p.origin}</Cell>
                        </Row>
                      ))}
                    </Table>

                    <Notice tone="neutral" compact>
                      {detail.disclaimer}
                    </Notice>
                  </div>
                )}
              </Panel>
            </div>
          }
        />
      }
    />
  );
}

function ReproductionReport({ r }: { r: ReproduceResult }) {
  // The headline must agree with the checklist below it. Claiming exact
  // reproduction on the strength of the curve alone, while the input hash or
  // engine revision differs, is exactly the kind of quiet overstatement this
  // panel exists to prevent.
  const exact =
    r.bitwise_identical === true && r.input_hash_matches && r.engine_revision_matches;
  const curveOnly = r.bitwise_identical === true && !exact;
  return (
    <Notice
      tone={exact ? "ok" : curveOnly ? "info" : "warn"}
      title={
        exact
          ? "Exact reproduction verified"
          : curveOnly
            ? "Numbers reproduced, but the run metadata changed"
            : "Reproduction produced differences"
      }
    >
      <div className="mt-1 space-y-1">
        <CheckLine ok={r.input_hash_matches} label="Input hash matches" detail={shortHash(r.input_hash_reproduced, 16)} />
        <CheckLine
          ok={r.engine_revision_matches}
          label="Engine revision unchanged"
          detail={`${r.engine_revision_original} → ${r.engine_revision_now}`}
        />
        <CheckLine
          ok={r.max_absolute_curve_difference === 0}
          label="Curve identical point by point"
          detail={
            r.max_absolute_curve_difference != null
              ? `max absolute difference ${r.max_absolute_curve_difference.toExponential(2)}`
              : "could not compare"
          }
        />
      </div>
      <p className="mt-1.5">{r.verdict}</p>
      {curveOnly && (
        <p className="mt-1">
          The predicted curve is identical point by point, so the science has not changed. What
          differs is the identifying metadata — most often because the engine revision was bumped
          after this run was stored. The numbers are reproduced; the stored hash simply belongs to
          an earlier build.
        </p>
      )}
      {!exact && !curveOnly && (
        <p className="mt-1">
          A difference in the curve means the engine no longer produces the same numbers for the
          same inputs. That is either an intentional change to the science (in which case the
          engine revision should have been bumped) or a regression.
        </p>
      )}
    </Notice>
  );
}

function CheckLine({ ok, label, detail }: { ok: boolean; label: string; detail: string }) {
  return (
    <div className="flex items-start gap-1.5 text-xs">
      <span className={ok ? "text-ok" : "text-warn"}>{ok ? "✓" : "✕"}</span>
      <span className="text-ink-dim">{label}</span>
      <span className="ml-auto truncate font-mono text-[9px] text-ink-ghost" title={detail}>
        {detail}
      </span>
    </div>
  );
}

function NewExperimentModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New experiment"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!name.trim()}
            onClick={async () => {
              setBusy(true);
              try {
                await api.createExperiment({
                  name: name.trim(),
                  description,
                  tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
                });
                setName("");
                setDescription("");
                setTags("");
                onCreated();
              } catch (e) {
                toast.push({ tone: "danger", title: "Could not create", detail: String(e) });
              } finally {
                setBusy(false);
              }
            }}
          >
            Create
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Name" inline={false}>
          <TextInput value={name} onChange={setName} autoFocus placeholder="Theophylline dose-interval exploration" />
        </Field>
        <Field label="Description" inline={false}>
          <TextArea
            value={description}
            onChange={setDescription}
            rows={4}
            placeholder="What question is this experiment asking? Which model and compound, and why that choice?"
          />
        </Field>
        <Field label="Tags (comma separated)" inline={false}>
          <TextInput value={tags} onChange={setTags} placeholder="dose-finding, theophylline" />
        </Field>
        <Hint>
          An experiment groups runs so they can be compared and reproduced together, and so a
          report can be generated across them.
        </Hint>
      </div>
    </Modal>
  );
}
