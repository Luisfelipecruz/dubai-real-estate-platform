/**
 * The panel's data shapes, and the formatting rules that stop them lying.
 *
 * ONE RULE ABOVE THE OTHERS: THIS MODULE COMPUTES NO RATE FROM COUNTS.
 *
 * Every rate arrives already decided by `api/services/observability/shaping.py`, which is
 * where the denominators live and where `null` means "not measured". If the browser could
 * derive `refused / runs` for itself, it would derive it for an hour with no runs, get
 * `0/0`, and render `NaN%` or — much worse — `0.0%`, which reads as a perfect hour. So the
 * counts are here to be *shown beside* a rate, never to produce one, and `Bucket` carries
 * both because the sample size is part of what the number means.
 *
 * The second rule follows from the first: `null` is a value with a rendering, and it is
 * never `0`. `formatRate(null)` is an em dash. There is no default, no `?? 0`, and no
 * `.toFixed()` reachable from a nullable without passing through here.
 */

import { formatMs } from "@/lib/copilot";

/** What `trend()` concluded. `indistinguishable` is a real answer, not a missing one. */
export type TrendDirection = "up" | "down" | "flat" | "indistinguishable" | "unknown";

export interface Trend {
  metric: string;
  current: number | null;
  previous: number | null;
  delta: number | null;
  direction: TrendDirection;
  /** The denominator each side was measured over. `null` for a metric that is not a rate. */
  current_n: number | null;
  previous_n: number | null;
  /** The finest change these denominators can express, 1/n. `null` when not a rate. */
  resolution: number | null;
}

export interface Bucket {
  /** ISO 8601, UTC. The start of the interval, not its midpoint. */
  start: string;
  runs: number;
  answered: number;
  refused: number;
  max_steps: number;
  failed: number;
  /** Runs that reported `answered` and returned nothing. The M-47 population. */
  answered_empty: number;
  tool_calls: number;
  tool_errors: number;
  unverified_numbers: number;
  /** Blank below the sample floor: `percentile_disc(0.95)` is the maximum under 20 runs. */
  p50_ms: number | null;
  p95_ms: number | null;
  cost_usd: number | null;
  cost_complete: boolean;
  refusal_rate: number | null;
  tool_error_rate: number | null;
  empty_answer_rate: number | null;
  cap_rate: number | null;
}

export interface HealthSnapshot {
  bucket: "hour" | "day";
  current: Bucket | null;
  previous: Bucket | null;
  /** Intervals with no runs between the two compared buckets. */
  gap_buckets: number;
  trends: Trend[];
  comparable: boolean;
  reason: string | null;
}

export interface ToolBreakdown {
  tool_name: string;
  category: string;
  calls: number;
  errors: number;
  error_rate: number | null;
  p50_ms: number | null;
  first_seen: string;
  last_seen: string;
}

/**
 * The tool error rate, and whether the failing tool can be named.
 *
 * `attributable` is the field that matters. `agent_runs` stores `tool_calls` and
 * `tool_errors` as integers and the per-call records are discarded when the request ends,
 * so the platform can state a 10.3% error rate and cannot say which tool produced it.
 * `reason` and `remedy` carry that, and the renderer is required to show them — a per-tool
 * chart fed by a table that never received per-tool rows renders as "no errors", which is
 * the same pixels as a healthy system.
 */
export interface ToolAttribution {
  runs: number;
  tool_calls: number;
  tool_errors: number;
  tool_error_rate: number | null;
  attributable: boolean;
  by_tool: ToolBreakdown[];
  reason: string | null;
  remedy: string | null;
}

/**
 * Which way is bad, per metric.
 *
 * A metric with no entry here gets a neutral tone. That is deliberate: a new metric added
 * to the API and not to this table renders grey, which is wrong-but-harmless, whereas a
 * default of "up is bad" would confidently colour an improvement red.
 */
export const METRIC_POLARITY: Record<string, "lower_is_better"> = {
  refusal_rate: "lower_is_better",
  tool_error_rate: "lower_is_better",
  empty_answer_rate: "lower_is_better",
  cap_rate: "lower_is_better",
  p95_ms: "lower_is_better",
};

export const METRIC_LABEL: Record<string, string> = {
  refusal_rate: "Refused",
  tool_error_rate: "Tool errors",
  empty_answer_rate: "Answered but empty",
  cap_rate: "Hit the step cap",
  p95_ms: "p95 latency",
};

export type TrendTone = "alarm" | "better" | "neutral" | "unknown";

/**
 * The tone a trend may be painted, and the reason `indistinguishable` exists as a
 * direction rather than as a boolean beside `up`.
 *
 * A flag next to a red arrow gets ignored — the arrow is what the eye reads. Making it a
 * direction of its own means there is no branch in this function that can paint a
 * three-run movement as an alarm: the only inputs that reach `alarm` are `up` and `down`,
 * which the API returns only when the movement exceeds its own sample's resolution.
 */
export function trendTone(trend: Trend): TrendTone {
  if (trend.direction === "unknown") return "unknown";
  if (trend.direction === "flat" || trend.direction === "indistinguishable") {
    return "neutral";
  }
  if (METRIC_POLARITY[trend.metric] !== "lower_is_better") return "neutral";
  return trend.direction === "up" ? "alarm" : "better";
}

/** A percentage, or an em dash. Never `0.0%` standing in for "nothing was measured". */
export function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

/** A signed change in percentage POINTS, which is not a percentage of a percentage. */
export function formatDelta(delta: number | null | undefined): string {
  if (delta === null || delta === undefined || Number.isNaN(delta)) return "—";
  const points = delta * 100;
  const sign = points > 0 ? "+" : "";
  return `${sign}${points.toFixed(1)} pts`;
}

/** A latency, or an em dash when the bucket was too thin to state one. */
export function formatLatency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return formatMs(ms);
}

/**
 * The denominators, spelled out: "3 vs 2 runs".
 *
 * Shown next to every rate trend, because "the refusal rate rose 33 points" and "1 of 3
 * versus 0 of 2" are the same fact and only one of them is honest on its own.
 */
export function formatSample(trend: Trend): string | null {
  if (trend.current_n === null || trend.previous_n === null) return null;
  return `${trend.current_n} vs ${trend.previous_n}`;
}

/** The value of one metric on one bucket, without going near its counts. */
export function metricValue(bucket: Bucket, metric: string): number | null {
  switch (metric) {
    case "refusal_rate":
      return bucket.refusal_rate;
    case "tool_error_rate":
      return bucket.tool_error_rate;
    case "empty_answer_rate":
      return bucket.empty_answer_rate;
    case "cap_rate":
      return bucket.cap_rate;
    case "p95_ms":
      return bucket.p95_ms;
    default:
      return null;
  }
}

export interface Segment {
  /** Index into the original bucket array, so a point can be traced back to its hour. */
  index: number;
  value: number;
}

/**
 * Split a series into the runs of consecutive measured points.
 *
 * This is rule 2 made structural. A chart drawn from one continuous path over a series
 * containing gaps draws a straight line across the hour with no traffic, and that line is
 * indistinguishable from an hour of steady performance. Splitting into segments means the
 * renderer has nothing to draw across a gap even if it wants to: the gap is not a point
 * with a missing value, it is the absence of a segment.
 *
 * A lone measured point between two gaps becomes a segment of length one, which a renderer
 * must draw as a dot. Dropping it would hide the only measurement in that window.
 */
export function segments(values: (number | null)[]): Segment[][] {
  const out: Segment[][] = [];
  let run: Segment[] = [];
  values.forEach((value, index) => {
    if (value === null || Number.isNaN(value)) {
      if (run.length > 0) out.push(run);
      run = [];
      return;
    }
    run.push({ index, value });
  });
  if (run.length > 0) out.push(run);
  return out;
}

/**
 * The upper bound of a chart's y axis.
 *
 * Returns `null` for a series with nothing in it, so the caller renders "no data" rather
 * than an axis from 0 to 0. Rates are NOT forced to 1.0: an axis fixed at 100% flattens a
 * refusal rate moving between 18% and 40% into two indistinguishable stubs, and that
 * movement is the entire point of the chart.
 */
export function axisMax(values: (number | null)[]): number | null {
  const measured = values.filter(
    (v): v is number => v !== null && !Number.isNaN(v),
  );
  if (measured.length === 0) return null;
  const top = Math.max(...measured);
  return top > 0 ? top : 1;
}

/** `2026-08-29T20:00:00Z` → `20:00`. UTC in, UTC out; the API buckets in UTC. */
export function bucketLabel(start: string, bucket: "hour" | "day" = "hour"): string {
  const at = new Date(start);
  if (Number.isNaN(at.getTime())) return start;
  if (bucket === "day") {
    return at.toISOString().slice(0, 10);
  }
  return at.toISOString().slice(11, 16);
}
