/**
 * Types and fetchers for the copilot endpoints.
 *
 * Every type here is transcribed from the pydantic models the API actually returns —
 * `api/models/agent.py` and `api/models/ask.py` — and not from what the endpoints were
 * expected to return. That distinction earned its keep before a line of UI existed: the
 * request field is `q`, not `question`, and a frontend written from the plan's prose
 * would have sent `{"question": ...}` and got a 422 on every call.
 *
 * The rule the whole page runs on (plan §11.4.4): NO NUMBER THE API DOES NOT RETURN.
 * There is no arithmetic in this file and there is none in the components. A frontend
 * that recomputes a median has re-introduced the exact drift `api/services/market.py`
 * exists to prevent, and it would do it somewhere nobody grades.
 */

const API_BASE =
  typeof window !== "undefined"
    ? process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    : process.env.INTERNAL_API_URL || "http://localhost:8000";

// ── /agent/query ────────────────────────────────────────────────────────────

/**
 * The four outcomes, and TWO OF THEM ARE SUCCESSES.
 *
 * This type is the reason the UI can be right about refusals. `refused` means the model
 * declined or every route reported the data cannot answer the question — which on the
 * golden set is the CORRECT result for exactly the questions m13a proved unanswerable.
 * Rendering it in red would contradict M-17.
 */
export type AgentOutcome = "answered" | "refused" | "max_steps" | "failed";

export interface ToolInvocation {
  step: number;
  name: string;
  category: string;
  arguments: Record<string, unknown>;
  ok: boolean;
  duration_ms: number;
  result: string;
  repeated: boolean;
}

export interface AgentStep {
  step: number;
  text: string | null;
  tool_calls: ToolInvocation[];
  input_tokens: number;
  output_tokens: number;
  /** Null means UNPRICED. It is not zero, and the UI must not render it as zero. */
  cost_usd: number | null;
  latency_ms: number;
  stop_reason: string | null;
}

export interface AgentUsage {
  steps: number;
  tool_calls: number;
  tool_errors: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  cost_priced: boolean;
}

export interface AgentTimings {
  generate: number;
  tools: number;
  total: number;
}

export interface AgentResponse {
  question: string;
  run_id: string;
  provider: string;
  model: string;
  outcome: AgentOutcome;
  answered: boolean;
  answer: string | null;
  categories: string[];
  steps: AgentStep[];
  grounding_warnings: string[];
  usage: AgentUsage;
  timings_ms: AgentTimings;
}

// ── /ask ────────────────────────────────────────────────────────────────────

export type Confidence = "high" | "medium" | "low";

/**
 * A citation AFTER checking, not as the model claimed it.
 *
 * `resolved` and `quote_found` fail for different reasons and the UI keeps them
 * distinct, because that difference is the whole point of the endpoint. An unresolved
 * chunk_id is a FABRICATED source. A resolved id whose quote is not in the chunk is a
 * paraphrase presented as a quotation — far more common, far easier to miss, and the
 * reason the quote is checked at all.
 */
export interface ResolvedCitation {
  chunk_id: number;
  quote: string;
  resolved: boolean;
  quote_found: boolean;
  source_type: string | null;
  source_id: string | null;
  heading_path: string | null;
}

export interface AskContext {
  chunk_id: number;
  source_type: string;
  source_id: string;
  heading_path: string | null;
  content: string;
  token_count: number;
  cosine_similarity: number | null;
  echoes_question: boolean;
}

export interface AskResponse {
  query: string;
  provider: string;
  model: string;
  answered: boolean;
  answer: string | null;
  unanswerable_reason: string | null;
  confidence: Confidence;
  citations: ResolvedCitation[];
  grounding_warnings: string[];
  contexts: AskContext[];
  retrieval: {
    mode: string;
    reranked: boolean;
    k: number;
    candidates_considered: number;
    lexical_relaxed: boolean;
  };
  usage: {
    input_tokens: number;
    output_tokens: number;
    cost_usd: number | null;
    cost_priced: boolean;
    repair_attempts: number;
    estimated_input_tokens: number;
  };
  timings_ms: { retrieve: number; generate: number; total: number };
  request_id: string | null;
}

// ── /agent/runs ─────────────────────────────────────────────────────────────

export interface RunsSummary {
  runs: number;
  answered: number;
  refused: number;
  hit_cap: number;
  failed: number;
  tool_calls: number;
  tool_errors: number;
  unverified_numbers: number;
  total_cost_usd: number;
  avg_steps: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  tool_p50_ms: number | null;
  refusal_rate: number | null;
  cap_rate: number | null;
  tool_error_rate: number | null;
}

export interface RunRow {
  id: string;
  created_at: string;
  provider: string;
  model: string;
  question: string;
  outcome: AgentOutcome;
  steps: number;
  tool_calls: number;
  tool_errors: number;
  /**
   * A COMMA-JOINED STRING, not a list — and this is not a typo.
   *
   * `/agent/query` returns `categories: list[str]` through its response model.
   * `/agent/runs` returns raw rows from `agent_runs`, where the column is a
   * `VARCHAR(128)` holding `"meta,geo,sql"`, and the endpoint declares no response model
   * at all, so nothing converts it. The same field name therefore has two different types
   * on two endpoints, and it is null for a run that called no tools.
   *
   * Found by reading a live response instead of the model. A frontend written from
   * `api/models/agent.py` would call `.map()` on a string on every row and throw on the
   * refused one. Use `parseCategories()`; never index this directly.
   */
  categories: string | null;
  total_cost_usd: number | null;
  cost_priced: boolean;
  latency_ms: number;
  tool_ms: number;
  unverified_numbers: number;
}

export interface RunsResponse {
  outcome_filter: string | null;
  summary: RunsSummary;
  recent: RunRow[];
}

export interface ToolCatalogue {
  provider: string;
  enabled: boolean;
  max_steps: number;
  max_cost_usd_per_run: number;
  total: number;
  tools: {
    name: string;
    category: string;
    description: string;
    parameters: Record<string, unknown>;
  }[];
}

// ── fetchers ────────────────────────────────────────────────────────────────

/**
 * A failure that carries its status code.
 *
 * The copilot pages need the code, not just a message: 503 means the LLM layer is
 * disabled or unreachable and the right response is an explanation of how to turn it on,
 * while 502 means the provider answered with something unusable and the right response is
 * "try again". Collapsing both into `new Error(detail)` — which `apiFetch` does — makes
 * those indistinguishable, and the stack is expected to run with `LLM_PROVIDER=none`.
 */
export class CopilotError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "CopilotError";
    this.status = status;
  }
}

async function post<T>(
  path: string,
  body: unknown,
  fetchImpl: typeof fetch = fetch,
  apiBase = API_BASE,
): Promise<T> {
  const res = await fetchImpl(`${apiBase}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res
      .json()
      .then((b: { detail?: unknown }) =>
        typeof b.detail === "string" ? b.detail : null,
      )
      .catch(() => null);
    throw new CopilotError(res.status, detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function get<T>(
  path: string,
  fetchImpl: typeof fetch = fetch,
  apiBase = API_BASE,
): Promise<T> {
  const res = await fetchImpl(`${apiBase}${path}`);
  if (!res.ok) {
    const detail = await res
      .json()
      .then((b: { detail?: unknown }) =>
        typeof b.detail === "string" ? b.detail : null,
      )
      .catch(() => null);
    throw new CopilotError(res.status, detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function runAgent(
  question: string,
  opts: { maxSteps?: number; provider?: string } = {},
  fetchImpl?: typeof fetch,
): Promise<AgentResponse> {
  return post<AgentResponse>(
    "/agent/query",
    { q: question, max_steps: opts.maxSteps, provider: opts.provider },
    fetchImpl,
  );
}

export function runAsk(
  question: string,
  opts: { k?: number; provider?: string } = {},
  fetchImpl?: typeof fetch,
): Promise<AskResponse> {
  return post<AskResponse>(
    "/ask",
    { q: question, k: opts.k, provider: opts.provider },
    fetchImpl,
  );
}

export function fetchRuns(
  limit = 20,
  outcome?: AgentOutcome,
  fetchImpl?: typeof fetch,
): Promise<RunsResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (outcome) params.set("outcome", outcome);
  return get<RunsResponse>(`/agent/runs?${params}`, fetchImpl);
}

export function fetchTools(fetchImpl?: typeof fetch): Promise<ToolCatalogue> {
  return get<ToolCatalogue>("/agent/tools", fetchImpl);
}

// ── formatting ──────────────────────────────────────────────────────────────

/**
 * `$0.00` and "unpriced" are DIFFERENT FACTS and this repository has said so four times.
 *
 * A local model genuinely costs zero dollars per token; a model missing from the rate
 * table has an unknown cost. Rendering both as `$0.00` asserts the second is the first.
 */
export function formatCost(cost: number | null | undefined, priced = true): string {
  if (cost === null || cost === undefined || !priced) return "—";
  if (cost === 0) return "$0.00";
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  return `$${cost.toFixed(2)}`;
}

/** Milliseconds are a fact too — `0 ms` is not the same as "not measured". */
export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatPercent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "—";
  return `${(rate * 100).toFixed(0)}%`;
}

/**
 * How an outcome should look. Note that `refused` is NEUTRAL, not destructive.
 *
 * Plan §11.4.1. `/agent/query` returns 200 for all four of these; only `failed` is an
 * error, and `max_steps` is the one that is genuinely partial.
 */
export const OUTCOME_STYLE: Record<
  AgentOutcome,
  { label: string; variant: "success" | "secondary" | "warning" | "destructive"; note: string }
> = {
  answered: {
    label: "answered",
    variant: "success",
    note: "The model produced prose and the tools backed it.",
  },
  refused: {
    label: "refused",
    variant: "secondary",
    note: "The model declined, or every route reported that the data cannot answer this. A refusal is a correct outcome, not a fault — it returns HTTP 200.",
  },
  max_steps: {
    label: "hit the step cap",
    variant: "warning",
    note: "The cap fired before the model finished. The findings below are PARTIAL.",
  },
  failed: {
    label: "failed",
    variant: "destructive",
    note: "The provider or the budget stopped the run. Any steps shown completed before the failure.",
  },
};

/**
 * Normalise the two shapes `categories` arrives in.
 *
 * `/agent/query` sends a list; `/agent/runs` sends `"meta,geo,sql"` or null. Both reach
 * the same chips, so the difference is absorbed here once rather than at each call site.
 */
export function parseCategories(
  value: string | string[] | null | undefined,
): string[] {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  return value
    .split(",")
    .map((c) => c.trim())
    .filter(Boolean);
}

/** Colour per routing category, so the routing evidence reads at a glance. */
export const CATEGORY_STYLE: Record<string, string> = {
  sql: "bg-sky-100 text-sky-800 border-sky-200",
  rag: "bg-violet-100 text-violet-800 border-violet-200",
  geo: "bg-emerald-100 text-emerald-800 border-emerald-200",
  meta: "bg-stone-100 text-stone-700 border-stone-200",
};
