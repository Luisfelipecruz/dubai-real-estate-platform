/**
 * The evaluation endpoint's shapes, and the two rules that keep the page honest.
 *
 * RULE 1: THIS MODULE COMPUTES NO RATE. Every number here — the score, the margin against
 * each floor, the counts behind it — arrives already decided by
 * `api/services/evaluation/results.assess`, which is pure Python with its own tests. A
 * browser that could derive `passed / n` for itself would derive it for a run that
 * measured nothing, get `0/0`, and render `0.0%` or `NaN%` on a page whose entire subject
 * is whether this deployment's numbers can be trusted.
 *
 * RULE 2: A SCORE IS NOT A CURRENT STATEMENT UNLESS THE REGISTRY SAYS SO.
 * `EvalReport.registry` is not a footnote — it decides whether the score may be presented
 * as a fact at all. A tool registered after the run can answer questions the agent used to
 * decline, which moves every rate derived from them while the stored score and its
 * timestamp stay exactly as they were. `describeRegistry` turns that into the sentence a
 * reader needs before they read a number.
 */

/** `ok` and `fail` are results. `not_measured` is a third state and never either. */
export type FloorState = "ok" | "fail" | "not_measured";

export interface FloorCheck {
  /** `section.metric`, e.g. `agent.route_accuracy`. */
  key: string;
  floor: number;
  /** `null` when this run measured nothing under that section. Never rendered as 0. */
  actual: number | null;
  /** Signed distance from the floor. Absent when `actual` is null. */
  margin?: number;
  state: FloorState;
}

/**
 * What changed in the tool registry since the score was measured.
 *
 * `known: false` means the comparison could not be made — a result stored without a
 * fingerprint, or an API with the agent layer switched off. It is NOT "nothing changed",
 * and `stale` is `null` rather than `false` so that it cannot be rendered as fresh.
 */
export interface RegistryDrift {
  known: boolean;
  stale: boolean | null;
  measured_against: string[] | null;
  registered_now: string[] | null;
  added_since: string[];
  removed_since: string[];
}

export interface EvalReport {
  available: boolean;
  reason?: string;
  id?: number;
  recorded_at?: string;
  age_seconds?: number;
  suite?: string;
  provider?: string | null;
  duration_s?: number;
  gate_applied?: boolean;
  gate_passed?: boolean | null;
  thresholds_available: boolean;
  thresholds_recorded?: string | null;
  floors: FloorCheck[];
  targets?: Record<string, unknown>;
  summary?: { checked: number; ok: number; failing: number; not_measured: number };
  metrics?: Record<string, number>;
  fixtures?: Record<string, number> | null;
  counts?: Record<string, Record<string, unknown>> | null;
  registry?: RegistryDrift;
  caveat?: string | null;
}

const API_BASE =
  typeof window !== "undefined"
    ? process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    : process.env.INTERNAL_API_URL || "http://localhost:8000";

export async function fetchLatestEval(): Promise<EvalReport | null> {
  const response = await fetch(`${API_BASE}/evals/latest`);
  if (!response.ok) return null;
  return (await response.json()) as EvalReport;
}

/**
 * A rate as a percentage, or an em dash.
 *
 * There is no `?? 0` anywhere in this file. `formatRate(null)` is the reason: an
 * unmeasured floor and a floor measured at zero must not render the same way, and the
 * only place that distinction can be lost is here.
 */
export function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

/** The signed distance, with its sign kept. `+2.0 pts` reads differently from `2.0 pts`. */
export function formatMargin(margin: number | null | undefined): string {
  if (margin === null || margin === undefined || Number.isNaN(margin)) return "—";
  const points = margin * 100;
  return `${points >= 0 ? "+" : ""}${points.toFixed(1)} pts`;
}

/**
 * Coarse, and deliberately so. "6 days ago" is the resolution at which the age of a score
 * is actionable; "5 days, 4 hours and 11 minutes" invites precision the number cannot
 * support, since what actually matters is whether the code changed underneath it.
 */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  if (seconds < 0) return "in the future";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/**
 * The sentence that goes ABOVE the score, or null when there is nothing to warn about.
 *
 * Returns a severity as well as text, because "cannot tell" and "definitely drifted" are
 * different warnings and rendering both amber would flatten the one that matters.
 */
export function describeRegistry(
  registry: RegistryDrift | undefined,
): { level: "stale" | "unknown"; text: string } | null {
  if (!registry) return null;
  if (!registry.known) {
    return {
      level: "unknown",
      text:
        "This result carries no record of which tools were registered when it ran, so " +
        "whether it still describes the running system cannot be established.",
    };
  }
  if (!registry.stale) return null;
  const parts: string[] = [];
  if (registry.added_since.length) {
    parts.push(
      `${registry.added_since.length} tool${registry.added_since.length === 1 ? "" : "s"} ` +
        `registered since (${registry.added_since.join(", ")})`,
    );
  }
  if (registry.removed_since.length) {
    parts.push(
      `${registry.removed_since.length} removed (${registry.removed_since.join(", ")})`,
    );
  }
  return {
    level: "stale",
    text:
      `Measured against a different tool layer: ${parts.join(", ")}. ` +
      "Re-run `make eval` before quoting this score.",
  };
}

/** Floors first, most severe first. A page that buries a failure under six passes has
 *  chosen the wrong default sort. */
export const FLOOR_ORDER: Record<FloorState, number> = {
  fail: 0,
  not_measured: 1,
  ok: 2,
};

export function sortFloors(floors: FloorCheck[]): FloorCheck[] {
  return [...floors].sort(
    (a, b) => FLOOR_ORDER[a.state] - FLOOR_ORDER[b.state] || a.key.localeCompare(b.key),
  );
}
