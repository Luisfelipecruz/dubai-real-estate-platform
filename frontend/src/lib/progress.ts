/**
 * Human-language progress, DERIVED from real events.
 *
 * ── What this file is, and what it deliberately is not ─────────────────────
 *
 * A reducer. It has no clock, no timer, no `setTimeout`, and no knowledge of how many
 * steps a run will take. It turns events that have already happened into sentences, and
 * if no event has arrived it has nothing to say — which is the entire guarantee.
 *
 * A scripted sequence of plausible statuses on a timer would look like progress and be a
 * lie about latency. The only reliable way not to write one is to build the thing that
 * produces the words with no ability to advance itself.
 *
 * ── The four rules, all of them measured ──────────────────────────────────
 *
 *  1. A FAILED TOOL NEVER SHOWS THE SUCCESS PHRASE. The measured tool error rate is
 *     10.3% — 31 failures in 301 calls. One call in ten fails, and a status line that
 *     cannot express a failure is claiming a reliability the system does not have.
 *
 *  2. AN EMPTY ANSWER IS A NAMED OUTCOME, NOT A BLANK SCREEN. A run can gather
 *     everything and produce no prose. With the tool trace collapsed, that is a blank
 *     screen after 66 seconds unless this file says otherwise.
 *
 *  3. A TRUNCATED STREAM IS NOT A FINISHED RUN. `readSSE` throws `StreamIncomplete`
 *     when the body closes without `done`; `markIncomplete` records that as its own
 *     status. "Still working" and "died at step 4" look identical otherwise.
 *
 *  4. NO NUMBER THAT DID NOT ARRIVE IN AN EVENT. `tookMs` is copied from a `result`
 *     event or left null. There is no estimate, no projected total, no percentage.
 */

import type {
  AgentOutcome,
  AgentResponse,
  AgentStep,
  ToolInvocation,
} from "./copilot";
import type { StreamEvent } from "./stream";

// ── The phrase book ─────────────────────────────────────────────────────────

/**
 * One tool, three sentences: what it is doing, what it did, and what happened when it
 * failed. The failure sentence is not optional and is not a softened version of the
 * success sentence — see rule 1 above.
 *
 * The keys are the tools registered in `api/services/agent/tools.py`. A tool absent from
 * this table is NOT given an invented description; see `PHRASES_UNKNOWN`.
 */
interface Phrases {
  working: string;
  done: string;
  failed: string;
}

const PHRASES: Record<string, Phrases> = {
  resolve_area_name: {
    working: "Finding the area you mean…",
    done: "Matched the area to the official name",
    failed: "Could not match that area name",
  },
  area_summary: {
    working: "Counting transactions…",
    done: "Counted the transactions",
    failed: "Could not read the transaction counts",
  },
  area_price_history: {
    working: "Looking up recorded prices…",
    done: "Read the recorded price history",
    failed: "Could not read the price history",
  },
  list_areas: {
    working: "Ranking areas by activity…",
    done: "Ranked the areas by activity",
    failed: "Could not rank the areas",
  },
  area_neighbors: {
    working: "Checking which areas border it…",
    done: "Found the bordering areas",
    failed: "Could not work out which areas border it",
  },
  ask_documents: {
    working: "Reading the documentation…",
    done: "Read the documentation",
    failed: "Could not read the documentation",
  },
  search_documents: {
    working: "Searching the documents…",
    done: "Searched the documents",
    failed: "Could not search the documents",
  },
  corpus_stats: {
    working: "Measuring the document index…",
    done: "Measured the document index",
    failed: "Could not measure the document index",
  },
  dataset_overview: {
    working: "Checking what data exists…",
    done: "Checked what data exists",
    failed: "Could not check what data exists",
  },
  // Answers questions about the whole dataset rather than one area, so the phrase must
  // not say "area" — that distinction is the reason the tool exists.
  dataset_aggregate: {
    working: "Adding up the whole dataset…",
    done: "Added up the whole dataset",
    failed: "Could not add up the dataset",
  },
};

/**
 * Every tool the agent can call, as the API registers it.
 *
 * **This list is duplicated on purpose and a test asserts it is complete.** When a tool
 * is registered on the server and has no phrase here, it narrates as "Finished a step" —
 * the fallback working exactly as designed, silently, for as long as nobody notices. What
 * was missing was anything that could FAIL when the two lists drift apart.
 *
 * A frontend unit test cannot call `GET /agent/tools`, so this is the same deliberate
 * duplication `test_main.py` uses for the router list: adding a tool breaks a test whose
 * message tells you to write its sentence.
 */
export const KNOWN_TOOLS = [
  "resolve_area_name",
  "area_summary",
  "area_price_history",
  "list_areas",
  "area_neighbors",
  "ask_documents",
  "search_documents",
  "corpus_stats",
  "dataset_overview",
  "dataset_aggregate",
] as const;

/**
 * What an UNRECOGNISED tool gets.
 *
 * `toStreamEvent` drops unknown *event names* on purpose so the server can add events
 * without a frontend deploy; the same has to be true of tool names, and the honest
 * handling is not a guess. A tool added to `TOOLS` after this file was written gets a
 * sentence that claims nothing about what it does. The real name still travels on
 * `ProgressLine.tool`, so the evidence view is complete even when the status line is
 * vague — which is the correct direction for the vagueness to point.
 */
const PHRASES_UNKNOWN: Phrases = {
  working: "Working on a step…",
  done: "Finished a step",
  failed: "A step failed",
};

function phrasesFor(tool: string): Phrases {
  return PHRASES[tool] ?? PHRASES_UNKNOWN;
}

/** Whether a tool name has a real sentence, as opposed to the generic fallback. */
export function isKnownTool(tool: string): boolean {
  return tool in PHRASES;
}

// ── State ───────────────────────────────────────────────────────────────────

export type ProgressStatus =
  /** No event has arrived. Not "starting" — nothing is known yet. */
  | "idle"
  /** At least one event arrived and no terminal event has. */
  | "working"
  /** A `done` event arrived. The run reached an outcome, including `refused`. */
  | "finished"
  /** The stream ended or errored before `done`. Rule 3. */
  | "incomplete";

export type LineTone = "working" | "done" | "failed" | "note";

export interface ProgressLine {
  /** Stable across re-renders; a `result` REPLACES its `step` line rather than adding. */
  key: string;
  /** The executor's step number, or 0 for lines that belong to the run as a whole. */
  step: number;
  tone: LineTone;
  /** Human language. Never contains a tool name, an argument, or a raw payload. */
  text: string;
  /**
   * The real tool name, carried for the evidence view and for tests.
   * The status line does not render it — the machinery stays out of the answer — but
   * nothing is dropped on the floor either. Collapsed is not deleted.
   */
  tool: string | null;
  /** Measured, from a `result` event. Null until one arrives. Rule 4. */
  tookMs: number | null;
}

export interface ProgressState {
  status: ProgressStatus;
  lines: ProgressLine[];
  /** The line describing what is happening NOW, or null when nothing is in flight. */
  current: ProgressLine | null;
  outcome: AgentOutcome | null;
  answer: string | null;
  /** Streamed prose, accumulated from `token` events. Empty when the server sends none. */
  streamedText: string;
  /** Rule 2: the run said `answered` and produced nothing to read. */
  emptyAnswer: boolean;
  /** How many `result` events reported `ok: false`. Counted, never estimated. */
  failures: number;
  /** Set by an `error` event or by `markIncomplete`. */
  error: string | null;
  runId: string | null;
  categories: string[];
  groundingWarnings: string[];
}

export const INITIAL_PROGRESS: ProgressState = {
  status: "idle",
  lines: [],
  current: null,
  outcome: null,
  answer: null,
  streamedText: "",
  emptyAnswer: false,
  failures: 0,
  error: null,
  runId: null,
  categories: [],
  groundingWarnings: [],
};

// ── The reducer ─────────────────────────────────────────────────────────────

/**
 * Fold one event into the state.
 *
 * Pure, and total: every event shape it does not understand leaves the state unchanged
 * rather than throwing. A status line that crashes the page on an unexpected event is
 * worse than one that says nothing.
 *
 * ORDERING IS NOT ASSUMED. SSE delivers in order over one connection, but a `result`
 * whose `step` was never announced still produces a line, and a second `result` for a
 * step that already has one replaces it instead of appending. Both cases are tested,
 * because "the events always arrive in order" is the kind of assumption that holds until
 * the endpoint this file was written before is actually built.
 */
export function reduceProgress(
  state: ProgressState,
  event: StreamEvent,
): ProgressState {
  switch (event.type) {
    case "step": {
      const line: ProgressLine = {
        key: `step-${event.step}`,
        step: event.step,
        tone: "working",
        text: phrasesFor(event.tool).working,
        tool: event.tool,
        tookMs: null,
      };
      return {
        ...state,
        status: state.status === "finished" ? state.status : "working",
        lines: upsert(state.lines, line),
        current: line,
      };
    }

    case "result": {
      const phrases = phrasesFor(event.tool);
      const line: ProgressLine = {
        key: `step-${event.step}`,
        step: event.step,
        // Rule 1, and it is one line of code because it has to be impossible to get
        // wrong: the success sentence is unreachable when `ok` is false.
        tone: event.ok ? "done" : "failed",
        text: event.ok ? phrases.done : phrases.failed,
        tool: event.tool,
        tookMs: event.took_ms,
      };
      return {
        ...state,
        status: state.status === "finished" ? state.status : "working",
        lines: upsert(state.lines, line),
        // Nothing is in flight the instant a result lands. The next `step` sets it again.
        current: null,
        failures: state.failures + (event.ok ? 0 : 1),
      };
    }

    case "token":
      return {
        ...state,
        status: state.status === "finished" ? state.status : "working",
        streamedText: state.streamedText + event.text,
        // The final synthesis turn is the one part of a run with no tool to name.
        current: {
          key: "writing",
          step: 0,
          tone: "working",
          text: "Writing the answer…",
          tool: null,
          tookMs: null,
        },
      };

    case "done": {
      const answer = event.answer;
      const emptyAnswer =
        event.outcome === "answered" && (answer ?? "").trim().length === 0;
      return {
        ...state,
        status: "finished",
        current: null,
        outcome: event.outcome,
        answer,
        emptyAnswer,
        runId: event.run_id,
        categories: event.categories ?? [],
        groundingWarnings: event.grounding_warnings ?? [],
        lines: [...state.lines, closingLine(event.outcome, emptyAnswer)],
      };
    }

    case "error":
      return {
        ...state,
        status: "incomplete",
        current: null,
        error: event.message,
      };

    default:
      return state;
  }
}

/**
 * The last line, which is the one a non-engineer actually reads.
 *
 * Four outcomes and none of them is "done". A refusal must not read as a failure or as an
 * answer, and a capped run must say it is partial — in words someone who has never read
 * this repository will understand.
 */
function closingLine(outcome: AgentOutcome, emptyAnswer: boolean): ProgressLine {
  if (emptyAnswer) {
    return {
      key: "closing",
      step: 0,
      tone: "failed",
      // Rule 2. This sentence is what stands between an empty answer and a blank screen.
      text: "Gathered the data but could not write the summary",
      tool: null,
      tookMs: null,
    };
  }
  const text: Record<AgentOutcome, string> = {
    answered: "Wrote the answer",
    refused: "Stopped — the available data cannot answer this",
    max_steps: "Ran out of steps before finishing — this answer is partial",
    failed: "The run did not complete",
  };
  return {
    key: "closing",
    step: 0,
    tone: outcome === "answered" ? "done" : "note",
    text: text[outcome],
    tool: null,
    tookMs: null,
  };
}

/** Replace the line with the same key, or append it. Keeps insertion order. */
function upsert(lines: ProgressLine[], line: ProgressLine): ProgressLine[] {
  const at = lines.findIndex((l) => l.key === line.key);
  if (at === -1) return [...lines, line];
  const next = lines.slice();
  next[at] = line;
  return next;
}

/**
 * Record that the stream ended without a `done` event.
 *
 * Call this from `readSSE`'s `StreamIncomplete` catch. Rule 3: a run that died at step 4
 * of 8 renders identically to one still working unless something says so, and the user
 * waits for a completion that will never arrive.
 *
 * The lines that DID arrive are kept. They describe work that really happened.
 */
export function markIncomplete(
  state: ProgressState,
  reason: string,
): ProgressState {
  if (state.status === "finished") return state;
  return {
    ...state,
    status: "incomplete",
    current: null,
    error: reason,
    lines: [
      ...state.lines,
      {
        key: "closing",
        step: 0,
        tone: "failed",
        text: "The connection ended before the run finished",
        tool: null,
        tookMs: null,
      },
    ],
  };
}

/** Fold a whole sequence. Convenience for tests and for the non-streaming path. */
export function progressFrom(events: StreamEvent[]): ProgressState {
  return events.reduce(reduceProgress, INITIAL_PROGRESS);
}

// ── The non-streaming path ──────────────────────────────────────────────────

/**
 * Convert a completed `AgentResponse` into the event sequence a compliant server would
 * have emitted for the same run.
 *
 * This exists so ONE reducer drives both paths. Today `/agent/stream` does not exist and
 * a run arrives as a single JSON body at the end; when the endpoint ships, the same
 * component renders the same sentences from real events with no rewrite.
 *
 * ┌──────────────────────────────────────────────────────────────────────────┐
 * │ EMIT THESE ALL AT ONCE. NEVER ON A TIMER.                                │
 * │                                                                          │
 * │ Every value here is true — the steps ran, the tools returned, the         │
 * │ durations are the executor's own measurements. What is NOT true is that   │
 * │ they arrived one at a time, and replaying them on an interval to make a   │
 * │ single 66-second response look like a live stream is a lie about latency  │
 * │ told with real data, which is worse than a spinner and not better.        │
 * │ Feeding them all in one tick produces a status list that appears complete │
 * │ the moment the response does. That is what happened.                      │
 * └──────────────────────────────────────────────────────────────────────────┘
 */
export function eventsFromResponse(res: AgentResponse): StreamEvent[] {
  const events: StreamEvent[] = [];

  for (const step of res.steps as AgentStep[]) {
    for (const call of step.tool_calls as ToolInvocation[]) {
      events.push({
        type: "step",
        step: step.step,
        tool: call.name,
        category: call.category,
        arguments: call.arguments,
      });
      events.push({
        type: "result",
        step: step.step,
        tool: call.name,
        ok: call.ok,
        took_ms: call.duration_ms,
        // Per-call cost is not in `ToolInvocation` — the executor prices a STEP, not a
        // tool. Null means unpriced, and inventing a division here would be exactly the
        // browser arithmetic, which this layer does not do.
        cost_usd: null,
        result: call.result,
      });
    }
  }

  events.push({
    type: "done",
    run_id: res.run_id,
    outcome: res.outcome,
    answer: res.answer,
    categories: res.categories ?? [],
    grounding_warnings: res.grounding_warnings ?? [],
    timings_ms: res.timings_ms,
    usage: {
      steps: res.usage.steps,
      tool_calls: res.usage.tool_calls,
      tool_errors: res.usage.tool_errors,
      cost_usd: res.usage.cost_usd,
      cost_priced: res.usage.cost_priced,
    },
  });

  return events;
}

/** The whole non-streaming path in one call. See the box above: no timers. */
export function progressFromResponse(res: AgentResponse): ProgressState {
  return progressFrom(eventsFromResponse(res));
}
