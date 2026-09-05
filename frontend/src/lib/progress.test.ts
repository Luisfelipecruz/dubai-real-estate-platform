/**
 * Every status line must be traceable to a real event.
 *
 * The fixtures are unedited captures of real runs. `agent-answered-empty.json` is a
 * 66.0-second run — seven steps, six tool calls, one of them failing, and an empty answer
 * body — which puts three of the things this surface must never paper over into a single
 * response.
 *
 * A test written against a hand-made object would pass while the real shape drifted, so
 * these use what the API actually returned.
 */

import ANSWERED_EMPTY from "./__fixtures__/agent-answered-empty.json";
import MAX_STEPS from "./__fixtures__/agent-max-steps.json";
import REFUSED from "./__fixtures__/agent-refused.json";
import type { AgentResponse } from "./copilot";
import {
  INITIAL_PROGRESS,
  KNOWN_TOOLS,
  eventsFromResponse,
  isKnownTool,
  markIncomplete,
  progressFrom,
  progressFromResponse,
  reduceProgress,
} from "./progress";
import { StreamIncomplete, readSSE, type StreamEvent } from "./stream";

const EMPTY_RUN = ANSWERED_EMPTY as unknown as AgentResponse;
const CAPPED_RUN = MAX_STEPS as unknown as AgentResponse;
const REFUSED_RUN = REFUSED as unknown as AgentResponse;

/** Every tool name the API can send, so a test can assert none of them leaks on screen. */
const TOOL_NAMES = [
  "resolve_area_name",
  "area_summary",
  "area_price_history",
  "list_areas",
  "area_neighbors",
  "ask_documents",
  "search_documents",
  "corpus_stats",
  "dataset_overview",
];

function sse(events: StreamEvent[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const body = events
    .map((e) => {
      const { type, ...rest } = e;
      return `event: ${type}\ndata: ${JSON.stringify(rest)}\n\n`;
    })
    .join("");
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(body));
      controller.close();
    },
  });
}

describe("the initial state", () => {
  it("says nothing at all before an event arrives", () => {
    expect(INITIAL_PROGRESS.status).toBe("idle");
    expect(INITIAL_PROGRESS.lines).toHaveLength(0);
    expect(INITIAL_PROGRESS.current).toBeNull();
  });

  it("has no way to advance itself — the reducer needs an event", () => {
    // The guarantee in the file header, stated as an assertion: there is no exported
    // function that produces a line from nothing.
    expect(progressFrom([])).toEqual(INITIAL_PROGRESS);
  });
});

describe("the real 66-second run", () => {
  const state = progressFromResponse(EMPTY_RUN);

  it("produces one line per tool call plus a closing line", () => {
    // Six tool calls over seven steps; step 7 called nothing.
    expect(EMPTY_RUN.usage.tool_calls).toBe(6);
    expect(state.lines).toHaveLength(7);
    expect(state.lines[6].key).toBe("closing");
  });

  it("counts the one real failure and does not soften it", () => {
    expect(EMPTY_RUN.usage.tool_errors).toBe(1);
    expect(state.failures).toBe(1);

    const failed = state.lines.filter((l) => l.tone === "failed");
    // The failed tool call, and the empty-answer closing line.
    expect(failed.map((l) => l.text)).toEqual([
      "Could not match that area name",
      "Gathered the data but could not write the summary",
    ]);
  });

  it("never shows the success sentence for the call that failed", () => {
    const step4 = state.lines.find((l) => l.step === 4);
    expect(step4?.tool).toBe("resolve_area_name");
    expect(step4?.tone).toBe("failed");
    expect(step4?.text).not.toBe("Matched the area to the official name");
  });

  it("names the empty answer instead of rendering a blank screen", () => {
    expect(EMPTY_RUN.outcome).toBe("answered");
    expect(EMPTY_RUN.answer).toBeNull();
    expect(state.emptyAnswer).toBe(true);
    expect(state.lines[6].text).toBe(
      "Gathered the data but could not write the summary",
    );
  });

  it("leaks no tool name, argument or payload into the visible text", () => {
    const visible = state.lines.map((l) => l.text).join(" ");
    for (const name of TOOL_NAMES) expect(visible).not.toContain(name);
    expect(visible).not.toContain("{");
    expect(visible).not.toContain("Business Bay");
  });

  it("keeps every tool name on the line, for the evidence view", () => {
    // Collapsed is not deleted. The status line does not render `tool`, but
    // nothing is thrown away either.
    const tools = state.lines.filter((l) => l.step > 0).map((l) => l.tool);
    expect(tools).toEqual([
      "resolve_area_name",
      "area_neighbors",
      "area_summary",
      "resolve_area_name",
      "area_price_history",
      "area_price_history",
    ]);
  });

  it("copies durations from the events and computes nothing", () => {
    const durations = state.lines.filter((l) => l.step > 0).map((l) => l.tookMs);
    expect(durations).toEqual([272, 344, 2181, 585, 1235, 765]);

    // No total, no average, no projection anywhere on the state object.
    expect(Object.keys(state)).not.toContain("totalMs");
    expect(Object.keys(state)).not.toContain("estimate");
  });

  it("ends in a terminal state with nothing in flight", () => {
    expect(state.status).toBe("finished");
    expect(state.current).toBeNull();
    expect(state.runId).toBe(EMPTY_RUN.run_id);
    expect(state.categories).toEqual(["meta", "geo", "sql"]);
  });
});

describe("the outcomes that are not an answer", () => {
  it("reads a refusal as a stop, not as a failure", () => {
    const state = progressFromResponse(REFUSED_RUN);
    expect(state.outcome).toBe("refused");
    expect(state.emptyAnswer).toBe(false);
    const closing = state.lines[state.lines.length - 1];
    // Not "failed" — a refusal is a 200 and the correct result for the questions m13a
    // proved unanswerable. Tone drives the colour, so this assertion is the one that
    // stops a refusal being rendered in red.
    expect(closing.tone).toBe("note");
    expect(closing.text).toBe(
      "Stopped — the available data cannot answer this",
    );
  });

  it("says a capped run is partial, in words", () => {
    const state = progressFromResponse(CAPPED_RUN);
    expect(state.outcome).toBe("max_steps");
    const closing = state.lines[state.lines.length - 1];
    expect(closing.text).toContain("partial");
    expect(closing.text).not.toContain("max_steps");
    expect(state.groundingWarnings[0]).toContain("step cap");
  });

  it("does not treat an empty answer on a refusal as a failed summary", () => {
    // `emptyAnswer` is scoped to `answered`. A refusal with no prose is not the defect.
    const state = progressFrom([
      {
        type: "done",
        run_id: "r",
        outcome: "refused",
        answer: null,
        categories: [],
        grounding_warnings: [],
        timings_ms: { generate: 0, tools: 0, total: 0 },
        usage: {
          steps: 0,
          tool_calls: 0,
          tool_errors: 0,
          cost_usd: null,
          cost_priced: false,
        },
      },
    ]);
    expect(state.emptyAnswer).toBe(false);
  });

  it("treats whitespace-only prose as empty", () => {
    const state = progressFrom([
      {
        type: "done",
        run_id: "r",
        outcome: "answered",
        answer: "   \n  ",
        categories: [],
        grounding_warnings: [],
        timings_ms: { generate: 0, tools: 0, total: 0 },
        usage: {
          steps: 0,
          tool_calls: 0,
          tool_errors: 0,
          cost_usd: null,
          cost_priced: false,
        },
      },
    ]);
    expect(state.emptyAnswer).toBe(true);
  });
});

describe("streams that do not behave", () => {
  it("handles a result whose step was never announced", () => {
    const state = progressFrom([
      {
        type: "result",
        step: 3,
        tool: "area_summary",
        ok: true,
        took_ms: 120,
        cost_usd: null,
        result: "{}",
      },
    ]);
    expect(state.lines).toHaveLength(1);
    expect(state.lines[0].text).toBe("Counted the transactions");
    expect(state.status).toBe("working");
  });

  it("replaces a step's line instead of appending a second one", () => {
    const state = progressFrom([
      {
        type: "step",
        step: 1,
        tool: "area_summary",
        category: "sql",
        arguments: {},
      },
      {
        type: "result",
        step: 1,
        tool: "area_summary",
        ok: true,
        took_ms: 10,
        cost_usd: null,
        result: "{}",
      },
      {
        type: "result",
        step: 1,
        tool: "area_summary",
        ok: false,
        took_ms: 11,
        cost_usd: null,
        result: "boom",
      },
    ]);
    expect(state.lines).toHaveLength(1);
    // The last event wins. A duplicate does not invent a second step.
    expect(state.lines[0].tone).toBe("failed");
    // …but both failures are counted, because both were reported.
    expect(state.failures).toBe(1);
  });

  it("does not resurrect a finished run", () => {
    const done = progressFromResponse(REFUSED_RUN);
    const after = reduceProgress(done, {
      type: "step",
      step: 9,
      tool: "area_summary",
      category: "sql",
      arguments: {},
    });
    expect(after.status).toBe("finished");
  });

  it("records a truncated stream as incomplete and keeps what arrived", async () => {
    const events: StreamEvent[] = eventsFromResponse(EMPTY_RUN).slice(0, 5);
    let state = INITIAL_PROGRESS;

    // Drive the REAL SSE reader over REAL bytes, then cut the body before `done`.
    await expect(
      readSSE(sse(events), (e) => {
        state = reduceProgress(state, e);
      }),
    ).rejects.toThrow(StreamIncomplete);

    expect(state.status).toBe("working");
    state = markIncomplete(state, "the stream ended without a `done` event");

    expect(state.status).toBe("incomplete");
    expect(state.status).not.toBe("finished");
    expect(state.outcome).toBeNull();
    expect(state.current).toBeNull();
    // The work that really happened is still on screen.
    expect(state.lines.map((l) => l.text)).toContain(
      "Matched the area to the official name",
    );
    expect(state.lines[state.lines.length - 1].text).toBe(
      "The connection ended before the run finished",
    );
  });

  it("does not overwrite a finished run when the reader complains late", () => {
    const done = progressFromResponse(REFUSED_RUN);
    expect(markIncomplete(done, "late").status).toBe("finished");
  });

  it("surfaces an error event without discarding the trace", () => {
    const state = progressFrom([
      {
        type: "step",
        step: 1,
        tool: "area_neighbors",
        category: "geo",
        arguments: {},
      },
      { type: "error", message: "provider timed out" },
    ]);
    expect(state.status).toBe("incomplete");
    expect(state.error).toBe("provider timed out");
    expect(state.lines).toHaveLength(1);
  });
});

describe("a tool this file has never heard of", () => {
  const unknown: StreamEvent[] = [
    {
      type: "step",
      step: 1,
      tool: "forecast_prices",
      category: "sql",
      arguments: {},
    },
    {
      type: "result",
      step: 1,
      tool: "forecast_prices",
      ok: true,
      took_ms: 42,
      cost_usd: null,
      result: "{}",
    },
  ];

  it("claims nothing about what it does", () => {
    expect(isKnownTool("forecast_prices")).toBe(false);
    const state = progressFrom(unknown);
    expect(state.lines[0].text).toBe("Finished a step");
  });

  it("still carries the real name for the evidence view", () => {
    expect(progressFrom(unknown).lines[0].tool).toBe("forecast_prices");
  });

  it("recognises all nine registered tools", () => {
    for (const name of TOOL_NAMES) expect(isKnownTool(name)).toBe(true);
  });
});

describe("the streaming and non-streaming paths agree", () => {
  it("produces the same lines whether the events arrive in one chunk or many", async () => {
    const events = eventsFromResponse(EMPTY_RUN);
    let streamed = INITIAL_PROGRESS;
    await readSSE(sse(events), (e) => {
      streamed = reduceProgress(streamed, e);
    });
    expect(streamed.lines).toEqual(progressFromResponse(EMPTY_RUN).lines);
  });

  it("emits a step and a result for every tool call, and one done", () => {
    const events = eventsFromResponse(EMPTY_RUN);
    expect(events.filter((e) => e.type === "step")).toHaveLength(6);
    expect(events.filter((e) => e.type === "result")).toHaveLength(6);
    expect(events.filter((e) => e.type === "done")).toHaveLength(1);
    expect(events[events.length - 1].type).toBe("done");
  });

  it("invents no per-tool cost, because the executor prices a step and not a tool", () => {
    for (const event of eventsFromResponse(EMPTY_RUN)) {
      if (event.type === "result") expect(event.cost_usd).toBeNull();
    }
  });
});

describe("the writing phase", () => {
  it("shows a status only once prose actually starts arriving", () => {
    const before = progressFrom([
      {
        type: "step",
        step: 1,
        tool: "area_summary",
        category: "sql",
        arguments: {},
      },
    ]);
    expect(before.current?.text).toBe("Counting transactions…");

    const after = reduceProgress(before, { type: "token", text: "Business " });
    expect(after.current?.text).toBe("Writing the answer…");
    expect(after.streamedText).toBe("Business ");
  });

  it("accumulates tokens without reordering or inserting anything", () => {
    const state = progressFrom([
      { type: "token", text: "Marsa " },
      { type: "token", text: "Dubai " },
      { type: "token", text: "recorded" },
    ]);
    expect(state.streamedText).toBe("Marsa Dubai recorded");
  });
});

describe("the phrase map and the tool catalogue", () => {
  it("has a real sentence for every registered tool", () => {
    // The guard that was missing: a tool was registered and the status line
    // said "Finished a step" for the tool the whole demo is built on, because nothing
    // tied PHRASES to the list of tools that actually exist.
    const missing = KNOWN_TOOLS.filter((t) => !isKnownTool(t));
    expect(missing).toEqual([]);
  });

  it("names the dataset-wide tool without saying 'area'", () => {
    // dataset_aggregate exists precisely because every other tool is area-scoped, so a
    // phrase mentioning an area would describe the tool it was built to replace.
    const line = reduceProgress(INITIAL_PROGRESS, {
      type: "step",
      step: 1,
      tool: "dataset_aggregate",
      category: "sql",
      arguments: {},
    }).lines.at(-1);
    expect(line?.text).toMatch(/dataset/i);
    expect(line?.text).not.toMatch(/area/i);
  });
});
