/**
 * Typed API client.
 *
 * Errors are surfaced with the server's own message. A simulation that fails
 * because a parameter is out of range should tell the user which parameter and
 * what the range is, not "request failed".
 */
import type {
  AuditEntry,
  ComparisonResponse,
  DatasetSummary,
  Drug,
  Experiment,
  Meta,
  ModelSpec,
  Patient,
  PatientInput,
  PatientPreview,
  PbpkStructuralCheck,
  PhysiologyResponse,
  PopulationRequest,
  PopulationResponse,
  Reference,
  ReproduceResult,
  SensitivityRequest,
  SensitivityResponse,
  SimulationRequest,
  SimulationResponse,
  SimulationSummary,
  StoredSimulation,
  ValidationReport,
  ValidationTargets,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function describe(status: number, body: unknown): string {
  if (typeof body === "string" && body) return body;
  if (body && typeof body === "object") {
    const d = (body as { detail?: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      // FastAPI validation errors: turn them into something a human can act on.
      return d
        .map((e) => {
          const loc = Array.isArray(e?.loc) ? e.loc.filter((x: unknown) => x !== "body").join(".") : "";
          return loc ? `${loc}: ${e?.msg ?? "invalid"}` : String(e?.msg ?? "invalid");
        })
        .join("; ");
    }
    if (d) return JSON.stringify(d);
  }
  return `Request failed with status ${status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (e) {
    throw new ApiError(
      0,
      "Cannot reach the SYNTHBODY API. Is the backend running on port 8000? " +
        "Start it with: uvicorn synthbody.api.main:app --port 8000",
      e,
    );
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let body: unknown = text;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      /* keep raw text */
    }
  }
  if (!res.ok) throw new ApiError(res.status, describe(res.status, body), body);
  return body as T;
}

const get = <T,>(p: string) => request<T>(p);
const post = <T,>(p: string, body?: unknown) =>
  request<T>(p, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const put = <T,>(p: string, body: unknown) =>
  request<T>(p, { method: "PUT", body: JSON.stringify(body) });
const del = (p: string) => request<void>(p, { method: "DELETE" });

export const api = {
  // ---- library
  meta: () => get<Meta>("/meta"),
  models: () => get<{ models: ModelSpec[] }>("/models").then((r) => r.models),
  model: (id: string) => get<ModelSpec>(`/models/${id}`),
  drugs: () =>
    get<{ drugs: Drug[]; curation_note: string; parameter_origin_legend: Record<string, string> }>(
      "/drugs",
    ),
  drug: (id: string) => get<Drug>(`/drugs/${id}`),
  references: (q?: { q?: string; topic?: string; kind?: string }) => {
    const p = new URLSearchParams();
    if (q?.q) p.set("q", q.q);
    if (q?.topic) p.set("topic", q.topic);
    if (q?.kind) p.set("kind", q.kind);
    const qs = p.toString();
    return get<{
      curation_note: string;
      n_total: number;
      n_matched: number;
      topics: string[];
      kinds: string[];
      references: Reference[];
    }>(`/references${qs ? `?${qs}` : ""}`);
  },
  reference: (id: string) => get<Reference>(`/references/${id}`),
  physiology: () => get<PhysiologyResponse>("/physiology"),
  datasets: () => get<{ datasets: DatasetSummary[] }>("/datasets").then((r) => r.datasets),
  dataset: (id: string) =>
    get<
      DatasetSummary & {
        observations: {
          subject_id: string;
          dose_mg: number;
          weight_kg: number | null;
          time_h: number[];
          concentration: number[];
        }[];
      }
    >(`/datasets/${id}`),

  // ---- patients
  patients: () => get<Patient[]>("/patients"),
  createPatient: (p: PatientInput) => post<Patient>("/patients", p),
  updatePatient: (id: number, p: PatientInput) => put<Patient>(`/patients/${id}`, p),
  deletePatient: (id: number) => del(`/patients/${id}`),
  previewPatient: (p: PatientInput) => post<PatientPreview>("/patients/preview", p),

  // ---- simulate
  simulate: (r: SimulationRequest) => post<SimulationResponse>("/simulate", r),
  compare: (r: { label: string; scenarios: SimulationRequest[]; persist?: boolean; experiment_id?: number | null }) =>
    post<ComparisonResponse>("/simulate/compare", r),
  population: (r: PopulationRequest) => post<PopulationResponse>("/simulate/population", r),
  sensitivity: (r: SensitivityRequest) => post<SensitivityResponse>("/simulate/sensitivity", r),

  // ---- experiments & runs
  experiments: () => get<Experiment[]>("/experiments"),
  createExperiment: (e: { name: string; description: string; tags: string[] }) =>
    post<Experiment>("/experiments", e),
  updateExperiment: (id: number, e: { name: string; description: string; tags: string[] }) =>
    put<Experiment>(`/experiments/${id}`, e),
  deleteExperiment: (id: number) => del(`/experiments/${id}`),

  simulations: (q?: { experiment_id?: number; model_id?: string; limit?: number }) => {
    const p = new URLSearchParams();
    if (q?.experiment_id != null) p.set("experiment_id", String(q.experiment_id));
    if (q?.model_id) p.set("model_id", q.model_id);
    if (q?.limit) p.set("limit", String(q.limit));
    const qs = p.toString();
    return get<SimulationSummary[]>(`/simulations${qs ? `?${qs}` : ""}`);
  },
  simulation: (id: number) => get<StoredSimulation>(`/simulations/${id}`),
  reproduce: (id: number) => post<ReproduceResult>(`/simulations/${id}/reproduce`),
  duplicate: (id: number, label?: string) =>
    post<SimulationResponse>(
      `/simulations/${id}/duplicate${label ? `?label=${encodeURIComponent(label)}` : ""}`,
    ),
  deleteSimulation: (id: number) => del(`/simulations/${id}`),
  audit: (limit = 200) => get<{ entries: AuditEntry[]; note: string }>(`/audit?limit=${limit}`),

  // ---- validation
  validationTargets: () => get<ValidationTargets>("/validation/targets"),
  validation: (targetId: string) => get<ValidationReport>(`/validation/${targetId}`),
  pbpkCheck: () => get<PbpkStructuralCheck>("/validation/pbpk/structural-check"),

  // ---- reports
  report: (r: {
    simulation_ids: number[];
    title: string;
    author?: string;
    include_validation?: boolean;
    include_references?: boolean;
    include_limitations?: boolean;
    format?: "markdown" | "json";
  }) => post<{ format: string; markdown: string; data: Record<string, unknown> }>("/reports", r),
};
