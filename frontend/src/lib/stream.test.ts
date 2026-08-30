/**
 * Tests for the SSE client.
 *
 * These cover the cases plan §11.6 names: events arriving out of order, a stream that
 * ends mid-run, a `done` that never comes. They are worth more than the usual "does the
 * happy path work" because the happy path is the one a local API on a fast loopback will
 * always take — frames arrive whole, in order, promptly — and every failure below is one
 * that only shows up against a slow or dying server, in front of an audience.
 */
import {
  SSEParser,
  StreamIncomplete,
  readSSE,
  streamAgentRun,
  probeStreaming,
  toStreamEvent,
  type StreamEvent,
} from "./stream";

/** Build a ReadableStream that emits the given strings as separate chunks. */
function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

function frame(event: string, payload: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
}

const DONE = frame("done", {
  run_id: "r1",
  outcome: "answered",
  answer: "42",
  categories: ["sql"],
  grounding_warnings: [],
  timings_ms: { generate: 1, tools: 2, total: 3 },
  usage: {
    steps: 1,
    tool_calls: 1,
    tool_errors: 0,
    cost_usd: 0,
    cost_priced: true,
  },
});

// ── the parser ──────────────────────────────────────────────────────────────

describe("SSEParser", () => {
  it("emits a complete frame and keeps an incomplete one buffered", () => {
    const parser = new SSEParser();
    expect(parser.push("event: step\ndata: {}\n\nevent: token\ndata: ")).toEqual([
      { event: "step", data: "{}" },
    ]);
    expect(parser.pending).toBe("event: token\ndata: ");
  });

  it("reassembles a frame split across chunk boundaries", () => {
    // The case that breaks a parser written against a fast local server. A single
    // logical event arrives as five unrelated network chunks, one of which splits the
    // JSON payload mid-token.
    const parser = new SSEParser();
    const pieces = ["even", "t: st", 'ep\ndata: {"st', 'ep": 1}', "\n\n"];
    const collected = pieces.flatMap((p) => parser.push(p));
    expect(collected).toEqual([{ event: "step", data: '{"step": 1}' }]);
  });

  it("accepts CRLF and bare CR line endings", () => {
    const parser = new SSEParser();
    expect(parser.push("event: step\r\ndata: {}\r\n\r\n")).toEqual([
      { event: "step", data: "{}" },
    ]);
  });

  it("joins multiple data lines with a newline, as the spec requires", () => {
    const parser = new SSEParser();
    expect(parser.push("event: token\ndata: line one\ndata: line two\n\n")).toEqual([
      { event: "token", data: "line one\nline two" },
    ]);
  });

  it("ignores comment keep-alives without emitting an event", () => {
    // Proxies close idle connections, so servers send `: ping` comments during a long
    // run. A parser that treats these as events shows phantom steps.
    const parser = new SSEParser();
    expect(parser.push(": keep-alive\n\n")).toEqual([]);
    expect(parser.push(": ping\nevent: token\ndata: {}\n\n")).toEqual([
      { event: "token", data: "{}" },
    ]);
  });

  it("strips exactly one leading space after the colon", () => {
    const parser = new SSEParser();
    // Two spaces in: one is framing, the second belongs to the value.
    expect(parser.push("event: token\ndata:  padded\n\n")).toEqual([
      { event: "token", data: " padded" },
    ]);
  });

  it("emits several frames arriving in one chunk", () => {
    const parser = new SSEParser();
    const out = parser.push(frame("step", { step: 1 }) + frame("step", { step: 2 }));
    expect(out.map((f) => f.data)).toEqual(['{"step":1}', '{"step":2}']);
  });
});

// ── event decoding ──────────────────────────────────────────────────────────

describe("toStreamEvent", () => {
  it("tags the payload with its event name", () => {
    expect(toStreamEvent({ event: "step", data: '{"step":1,"tool":"x"}' })).toEqual({
      type: "step",
      step: 1,
      tool: "x",
    });
  });

  it("drops unknown event names rather than throwing", () => {
    // The server must be able to add a heartbeat or a cost warning without this client
    // being redeployed in lockstep.
    expect(toStreamEvent({ event: "invented_later", data: "{}" })).toBeNull();
  });

  it("reports malformed JSON as an error event instead of throwing", () => {
    const event = toStreamEvent({ event: "step", data: "{not json" });
    expect(event).toMatchObject({ type: "error" });
    expect((event as { message: string }).message).toContain("malformed");
  });
});

// ── reading a stream ────────────────────────────────────────────────────────

describe("readSSE", () => {
  it("delivers every event in order and resolves when done arrives", async () => {
    const seen: StreamEvent[] = [];
    await readSSE(
      streamOf(
        frame("step", { step: 1, tool: "resolve_area_name", category: "meta" }),
        frame("result", { step: 1, ok: true, took_ms: 272 }),
        DONE,
      ),
      (e) => seen.push(e),
    );
    expect(seen.map((e) => e.type)).toEqual(["step", "result", "done"]);
  });

  it("throws StreamIncomplete when the stream ends without done", async () => {
    // THE CASE THAT MUST NOT BE SILENT. A run that dies at step 4 of 8 otherwise leaves
    // four steps and a spinner on screen, indistinguishable from a run still working,
    // and the user waits for something that will never arrive.
    const seen: StreamEvent[] = [];
    await expect(
      readSSE(streamOf(frame("step", { step: 1 })), (e) => seen.push(e)),
    ).rejects.toThrow(StreamIncomplete);
    expect(seen).toHaveLength(1);
  });

  it("reports an unterminated trailing frame in the error message", async () => {
    await expect(
      readSSE(streamOf("event: step\ndata: {\"ste"), () => {}),
    ).rejects.toThrow(/mid-frame/);
  });

  it("keeps the events it did receive before the stream broke", async () => {
    const seen: StreamEvent[] = [];
    await expect(
      readSSE(
        streamOf(frame("step", { step: 1 }), frame("step", { step: 2 })),
        (e) => seen.push(e),
      ),
    ).rejects.toThrow(StreamIncomplete);
    // Partial findings survive a failure — the same judgement the executor makes when a
    // provider dies mid-run rather than discarding five successful steps.
    expect(seen).toHaveLength(2);
  });

  it("decodes a multi-byte character split across a chunk boundary", async () => {
    // The fifth encoding trap in this project would be a NARROW NO-BREAK SPACE arriving
    // as two halves. `/ask` returns U+202F in real answers ("k = 60"), so this is the
    // live case, not a hypothetical one.
    const encoded = new TextEncoder().encode(
      frame("token", { text: "k = 60" }),
    );
    const cut = 22;
    const seen: StreamEvent[] = [];
    await readSSE(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoded.slice(0, cut));
          controller.enqueue(encoded.slice(cut));
          controller.enqueue(new TextEncoder().encode(DONE));
          controller.close();
        },
      }),
      (e) => seen.push(e),
    );
    expect(seen[0]).toEqual({ type: "token", text: "k = 60" });
  });
});

// ── the request ─────────────────────────────────────────────────────────────

describe("streamAgentRun", () => {
  it("sends the question as `q`, which is the field the API actually takes", async () => {
    // Not `question`. The API rejects `{"question": ...}` with a 422, and this test is
    // here because the plan's own prose says "question" and a frontend written from it
    // would fail on every call.
    const fetchImpl = jest.fn().mockResolvedValue(
      new Response(DONE, { status: 200 }),
    ) as unknown as typeof fetch;

    await streamAgentRun({
      question: "how many?",
      maxSteps: 4,
      onEvent: () => {},
      fetchImpl,
      apiBase: "http://api",
    });

    const url = (fetchImpl as unknown as jest.Mock).mock.calls[0][0] as string;
    expect(url).toContain("q=how+many%3F");
    expect(url).toContain("max_steps=4");
  });

  it("surfaces the API's own detail message on a non-2xx", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "LLM_PROVIDER=none" }), { status: 503 }),
    ) as unknown as typeof fetch;

    await expect(
      streamAgentRun({ question: "q", onEvent: () => {}, fetchImpl }),
    ).rejects.toThrow("LLM_PROVIDER=none");
  });
});

// ── the capability probe ────────────────────────────────────────────────────

describe("probeStreaming", () => {
  it("is false against the API as it exists today", async () => {
    // `/agent/stream` is specified but unbuilt — its endpoint and the executor hook it
    // needs are both inside m15's uncommitted manifest. This test documents that the
    // page's degraded path is the LIVE path right now, not a defensive branch nobody
    // takes.
    const fetchImpl = jest.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ paths: { "/agent/query": {}, "/agent/runs": {} } }),
        { status: 200 },
      ),
    ) as unknown as typeof fetch;
    await expect(probeStreaming(fetchImpl, "http://api")).resolves.toBe(false);
  });

  it("is true once the endpoint appears in the schema", async () => {
    const fetchImpl = jest.fn().mockResolvedValue(
      new Response(JSON.stringify({ paths: { "/agent/stream": {} } }), { status: 200 }),
    ) as unknown as typeof fetch;
    await expect(probeStreaming(fetchImpl, "http://api")).resolves.toBe(true);
  });

  it("is false, not a crash, when the API is unreachable", async () => {
    // The stack is expected to run with the API down; the page reports that separately.
    const fetchImpl = jest
      .fn()
      .mockRejectedValue(new TypeError("fetch failed")) as unknown as typeof fetch;
    await expect(probeStreaming(fetchImpl, "http://api")).resolves.toBe(false);
  });
});
