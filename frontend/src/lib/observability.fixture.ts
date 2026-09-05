/**
 * The six hours of 2026-08-29, exactly as Postgres reported them.
 *
 * Read out of the live table through `services/observability/queries.py` and transcribed,
 * not invented. Every honesty rule this milestone adds has a witness here:
 *
 *   19:00  no runs at all -- the gap the chart must not draw through
 *   22:00  two runs, so p95 is blank; `percentile_disc(0.95)` is the maximum below n = 20
 *   23:00  three runs, one of which answered and returned nothing: an empty-answer rate of
 *          100% that a naive panel would page someone about
 *   17:00  one blank answer that is NOT a bug -- a `failed` run, which is why the M-47
 *          denominator is `answered` and not `runs`
 *
 * NOT in `src/lib/__fixtures__/`, which is where m18 keeps its fixtures, and the reason is
 * mechanical rather than stylistic: that directory is staged as a DIRECTORY argument by an
 * uncommitted milestone, so a file added inside it would be swept into that milestone's
 * commit. Same fixture, path chosen so it lands where it belongs.
 */

import type { Bucket, HealthSnapshot, ToolAttribution } from "@/lib/observability";

function hour(n: number): string {
  return `2026-08-29T${String(n).padStart(2, "0")}:00:00.000Z`;
}

export const LIVE_HOURLY: Bucket[] = [
  {
    start: hour(17),
    runs: 49,
    answered: 39,
    refused: 9,
    max_steps: 0,
    failed: 1,
    answered_empty: 0,
    tool_calls: 73,
    tool_errors: 9,
    unverified_numbers: 9,
    p50_ms: 5997,
    p95_ms: 22085,
    cost_usd: 0,
    cost_complete: true,
    refusal_rate: 9 / 49,
    tool_error_rate: 9 / 73,
    empty_answer_rate: 0,
    cap_rate: 0,
  },
  {
    start: hour(18),
    runs: 32,
    answered: 26,
    refused: 6,
    max_steps: 0,
    failed: 0,
    answered_empty: 0,
    tool_calls: 44,
    tool_errors: 4,
    unverified_numbers: 1,
    p50_ms: 8294,
    p95_ms: 38886,
    cost_usd: 0,
    cost_complete: true,
    refusal_rate: 6 / 32,
    tool_error_rate: 4 / 44,
    empty_answer_rate: 0,
    cap_rate: 0,
  },
  {
    // The hour with no traffic. Every rate is null; none of them is zero.
    start: hour(19),
    runs: 0,
    answered: 0,
    refused: 0,
    max_steps: 0,
    failed: 0,
    answered_empty: 0,
    tool_calls: 0,
    tool_errors: 0,
    unverified_numbers: 0,
    p50_ms: null,
    p95_ms: null,
    cost_usd: null,
    cost_complete: false,
    refusal_rate: null,
    tool_error_rate: null,
    empty_answer_rate: null,
    cap_rate: null,
  },
  {
    start: hour(20),
    runs: 87,
    answered: 55,
    refused: 32,
    max_steps: 0,
    failed: 0,
    answered_empty: 5,
    tool_calls: 119,
    tool_errors: 12,
    unverified_numbers: 10,
    p50_ms: 7430,
    p95_ms: 46603,
    cost_usd: 0,
    cost_complete: true,
    refusal_rate: 32 / 87,
    tool_error_rate: 12 / 119,
    empty_answer_rate: 5 / 55,
    cap_rate: 0,
  },
  {
    start: hour(21),
    runs: 40,
    answered: 24,
    refused: 16,
    max_steps: 0,
    failed: 0,
    answered_empty: 2,
    tool_calls: 55,
    tool_errors: 5,
    unverified_numbers: 5,
    p50_ms: 7722,
    p95_ms: 43247,
    cost_usd: 0,
    cost_complete: true,
    refusal_rate: 16 / 40,
    tool_error_rate: 5 / 55,
    empty_answer_rate: 2 / 24,
    cap_rate: 0,
  },
  {
    // Two runs. p50 survives (percentile_disc(0.5) is not the maximum from n = 2);
    // p95 does not.
    start: hour(22),
    runs: 2,
    answered: 2,
    refused: 0,
    max_steps: 0,
    failed: 0,
    answered_empty: 0,
    tool_calls: 2,
    tool_errors: 0,
    unverified_numbers: 0,
    p50_ms: 2124,
    p95_ms: null,
    cost_usd: 0,
    cost_complete: true,
    refusal_rate: 0,
    tool_error_rate: 0,
    empty_answer_rate: 0,
    cap_rate: 0,
  },
  {
    start: hour(23),
    runs: 3,
    answered: 1,
    refused: 1,
    max_steps: 1,
    failed: 0,
    answered_empty: 1,
    tool_calls: 8,
    tool_errors: 1,
    unverified_numbers: 0,
    p50_ms: 13829,
    p95_ms: null,
    cost_usd: 0,
    cost_complete: true,
    refusal_rate: 1 / 3,
    tool_error_rate: 1 / 8,
    empty_answer_rate: 1,
    cap_rate: 1 / 3,
  },
];

/**
 * The comparison the API actually returned for those last two hours.
 *
 * Three of the four rate movements come back `indistinguishable`: a rate over two runs
 * moves in steps of 50 percentage points, so a 33-point change read off it is an artefact
 * of the denominator. The fourth, `empty_answer_rate`, does clear its own resolution --
 * both runs that claimed to answer returned nothing -- and stays a direction.
 */
export const LIVE_HEALTH: HealthSnapshot = {
  bucket: "hour",
  current: LIVE_HOURLY[6],
  previous: LIVE_HOURLY[5],
  gap_buckets: 0,
  comparable: true,
  reason: null,
  trends: [
    {
      metric: "refusal_rate",
      current: 1 / 3,
      previous: 0,
      delta: 1 / 3,
      direction: "indistinguishable",
      current_n: 3,
      previous_n: 2,
      resolution: 0.5,
    },
    {
      metric: "tool_error_rate",
      current: 0.125,
      previous: 0,
      delta: 0.125,
      direction: "indistinguishable",
      current_n: 8,
      previous_n: 2,
      resolution: 0.5,
    },
    {
      metric: "empty_answer_rate",
      current: 1,
      previous: 0,
      delta: 1,
      direction: "up",
      current_n: 1,
      previous_n: 2,
      resolution: 1,
    },
    {
      metric: "cap_rate",
      current: 1 / 3,
      previous: 0,
      delta: 1 / 3,
      direction: "indistinguishable",
      current_n: 3,
      previous_n: 2,
      resolution: 0.5,
    },
    {
      metric: "p95_ms",
      current: null,
      previous: null,
      delta: null,
      direction: "unknown",
      current_n: null,
      previous_n: null,
      resolution: null,
    },
  ],
};

/** The same two hours compared with enough runs behind them to conclude something. */
export const WIDE_TREND: HealthSnapshot["trends"][number] = {
  metric: "refusal_rate",
  current: 16 / 40,
  previous: 9 / 49,
  delta: 16 / 40 - 9 / 49,
  direction: "up",
  current_n: 40,
  previous_n: 49,
  resolution: 1 / 40,
};

/** What the API returns today: a real rate, and no way to say which tool produced it. */
export const UNATTRIBUTABLE: ToolAttribution = {
  runs: 213,
  tool_calls: 301,
  tool_errors: 31,
  tool_error_rate: 31 / 301,
  attributable: false,
  by_tool: [],
  reason:
    "per-call records are not persisted: agent_runs stores tool_calls and tool_errors " +
    "as integers, and the agent_tool_calls table is not present. The failing tool " +
    "cannot be named from stored data.",
  remedy:
    "migration 0004 adds agent_tool_calls; the producer is the per-step accounting in " +
    "services/agent/executor.py. Attribution begins at that migration and is not " +
    "backfilled -- there is no history to backfill from.",
};

/** What it will return once 0004 has a producer. Shape only; these counts are not measured. */
export const ATTRIBUTED: ToolAttribution = {
  runs: 4,
  tool_calls: 9,
  tool_errors: 2,
  tool_error_rate: 2 / 9,
  attributable: true,
  by_tool: [
    {
      tool_name: "resolve_area_name",
      category: "meta",
      calls: 4,
      errors: 2,
      error_rate: 0.5,
      p50_ms: 272,
      first_seen: hour(20),
      last_seen: hour(21),
    },
    {
      tool_name: "area_summary",
      category: "sql",
      calls: 5,
      errors: 0,
      error_rate: 0,
      p50_ms: 585,
      first_seen: hour(20),
      last_seen: hour(21),
    },
  ],
  reason: null,
  remedy: null,
};
