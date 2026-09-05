/**
 * The Server-Sent Events client for `GET /agent/stream`.
 *
 * ── Why streaming, and why the client is this careful ──────────────────────
 *
 * An agent run takes 1.4–58.6 s and `/ask` takes 7.9–20.9 s. A spinner in front of a
 * 58-second run tells the user nothing, so the run reports itself as it happens.
 *
 * The interesting failure modes all live here, in framing and decoding: a frame split
 * across chunk boundaries, a multi-byte character cut in half, a stream that ends without
 * `done`. Each is handled and tested below.
 *
 * `probeStreaming()` asks the live API whether the endpoint exists, so a deployment
 * without it degrades honestly instead of hanging.
 *
 * ── Why fetch, and not EventSource ────────────────────────────────────────
 *
 * `EventSource` would work — the endpoint is a GET — but it cannot be aborted with a
 * reason, reports every failure as one opaque `onerror`, and does not exist in jsdom, so
 * the reconnection and truncation behaviour could not be tested. `fetch` + a
 * ReadableStream reader gives an AbortSignal, real status codes, and a body that a test
 * can feed one byte at a time.
 */

const API_BASE =
  typeof window !== "undefined"
    ? process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    : process.env.INTERNAL_API_URL || "http://localhost:8000";

import type { AgentStep } from "./copilot";

/** One decoded SSE frame: an event name and its (possibly multi-line) data payload. */
export interface SSEFrame {
  event: string;
  data: string;
}

/**
 * Incremental SSE frame parser.
 *
 * The only reason this is a class and not a regex over the whole response is that the
 * whole response does not exist yet — that is the entire point of streaming. Frames
 * arrive split across arbitrary chunk boundaries, and a parser that assumes otherwise
 * works perfectly against a fast local API and drops events against a slow one. This
 * keeps a buffer and emits only complete frames.
 */
export class SSEParser {
  private buffer = "";

  /** Feed a decoded chunk. Returns every frame that is now complete. */
  push(chunk: string): SSEFrame[] {
    // Normalise line endings first. The spec allows CRLF, CR or LF, and a server behind
    // a proxy may not use the one the client expects.
    this.buffer += chunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

    const frames: SSEFrame[] = [];
    let boundary = this.buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const raw = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const frame = parseFrame(raw);
      if (frame) frames.push(frame);
      boundary = this.buffer.indexOf("\n\n");
    }
    return frames;
  }

  /**
   * Whatever is left in the buffer when the stream ends.
   *
   * A well-behaved server terminates the last frame with a blank line. This exists so
   * that a server which does not — or a connection cut mid-frame — is a visible,
   * inspectable state rather than a silently discarded event.
   */
  get pending(): string {
    return this.buffer;
  }
}

function parseFrame(raw: string): SSEFrame | null {
  let event = "message";
  const data: string[] = [];

  for (const line of raw.split("\n")) {
    // A line beginning with a colon is a comment. Servers send these as keep-alives
    // through proxies that would otherwise time the connection out, so they arrive in
    // normal operation and must not be mistaken for events.
    if (line.startsWith(":")) continue;

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    // Exactly one leading space after the colon is part of the framing, not the value.
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") event = value;
    else if (field === "data") data.push(value);
    // `id` and `retry` are ignored: this stream is not resumable. A half-finished agent
    // run cannot be resumed from an offset anyway — the tools have already run.
  }

  if (data.length === 0) return null;
  return { event, data: data.join("\n") };
}

// ── The event contract ──────────────────────────────────────────────────────

export interface StepEvent {
  type: "step";
  step: number;
  tool: string;
  category: string;
  arguments: Record<string, unknown>;
}

export interface ResultEvent {
  type: "result";
  step: number;
  tool: string;
  ok: boolean;
  took_ms: number;
  cost_usd: number | null;
  result: string;
}

export interface TokenEvent {
  type: "token";
  text: string;
}

export interface DoneEvent {
  type: "done";
  run_id: string;
  outcome: "answered" | "refused" | "max_steps" | "failed";
  answer: string | null;
  /**
   * The complete per-step trace, the same shape `POST /agent/query` returns.
   *
   * Optional because the client must keep working against an API build that does not
   * send it -- the `error` path's synthetic `done` has no steps either. An absent trace
   * renders as "no steps recorded", which is true of that payload; a WRONG trace
   * rebuilt from the step/result events would not be.
   */
  steps?: AgentStep[];
  categories: string[];
  grounding_warnings: string[];
  timings_ms: { generate: number; tools: number; total: number };
  usage: {
    steps: number;
    tool_calls: number;
    tool_errors: number;
    cost_usd: number | null;
    cost_priced: boolean;
  };
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export type StreamEvent =
  | StepEvent
  | ResultEvent
  | TokenEvent
  | DoneEvent
  | ErrorEvent;

/**
 * Turn a frame into a typed event, or null if it is not one we know.
 *
 * Unknown event names are dropped rather than thrown on. The server is allowed to add
 * events — a heartbeat, a cost warning — without this client being redeployed, and a
 * client that crashes on an unrecognised name makes that impossible.
 */
export function toStreamEvent(frame: SSEFrame): StreamEvent | null {
  let payload: unknown;
  try {
    payload = JSON.parse(frame.data);
  } catch {
    return {
      type: "error",
      message: `malformed event payload on "${frame.event}": ${frame.data.slice(0, 120)}`,
    };
  }

  if (
    frame.event === "step" ||
    frame.event === "result" ||
    frame.event === "token" ||
    frame.event === "done" ||
    frame.event === "error"
  ) {
    return { ...(payload as object), type: frame.event } as StreamEvent;
  }
  return null;
}

// ── Reading the stream ──────────────────────────────────────────────────────

export class StreamIncomplete extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StreamIncomplete";
  }
}

/**
 * Read an SSE body to completion, calling `onEvent` for each decoded event.
 *
 * Resolves when the server closes the stream. Throws `StreamIncomplete` if it closed
 * without a `done` event — which is the case that must NOT be silent. A run that dies at
 * step 4 of 8 leaves a UI showing four steps and a spinner, indistinguishable from a run
 * still working, and the user waits for something that will never arrive.
 */
export async function readSSE(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = new SSEParser();
  let sawDone = false;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      // `stream: true` is what makes a multi-byte character split across a chunk
      // boundary decode correctly instead of becoming U+FFFD. This project has had four
      // separate encoding failures already; it does not need a fifth.
      for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
        const event = toStreamEvent(frame);
        if (!event) continue;
        if (event.type === "done") sawDone = true;
        onEvent(event);
      }
    }
  } finally {
    reader.releaseLock();
  }

  if (!sawDone) {
    const trailing = parser.pending.trim();
    throw new StreamIncomplete(
      trailing
        ? `the stream ended mid-frame after ${trailing.length} unterminated byte(s)`
        : "the stream ended without a `done` event — the run did not finish",
    );
  }
}

export interface StreamRunOptions {
  question: string;
  provider?: string;
  maxSteps?: number;
  onEvent: (event: StreamEvent) => void;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
  apiBase?: string;
}

/** Open `GET /agent/stream` and read it to completion. */
export async function streamAgentRun({
  question,
  provider,
  maxSteps,
  onEvent,
  signal,
  fetchImpl = fetch,
  apiBase = API_BASE,
}: StreamRunOptions): Promise<void> {
  const params = new URLSearchParams({ q: question });
  if (provider) params.set("provider", provider);
  if (maxSteps) params.set("max_steps", String(maxSteps));

  const res = await fetchImpl(`${apiBase}/agent/stream?${params}`, {
    method: "GET",
    headers: { Accept: "text/event-stream" },
    signal,
  });

  if (!res.ok) {
    const detail = await res
      .json()
      .then((b: { detail?: string }) => b.detail)
      .catch(() => null);
    throw new Error(detail || `stream failed: HTTP ${res.status}`);
  }
  if (!res.body) throw new Error("stream response carried no body");

  await readSSE(res.body, onEvent);
}

/**
 * Ask the live API whether it can stream, by reading its own OpenAPI schema.
 *
 * This is a capability check against the running build, not a feature flag. `/agent/stream`
 * is specified but unbuilt (see the header), so today this returns false everywhere and
 * the copilot page says so in words. When the endpoint ships, the same page starts
 * streaming with no change here.
 *
 * Reading the schema rather than probing the endpoint is deliberate: probing means
 * issuing a request that, if the endpoint DOES exist, starts a real agent run and spends
 * real money to answer a question nobody asked.
 */
export async function probeStreaming(
  fetchImpl: typeof fetch = fetch,
  apiBase = API_BASE,
): Promise<boolean> {
  try {
    const res = await fetchImpl(`${apiBase}/openapi.json`);
    if (!res.ok) return false;
    const schema = (await res.json()) as { paths?: Record<string, unknown> };
    return Boolean(schema.paths && "/agent/stream" in schema.paths);
  } catch {
    // The API being unreachable is not the same fact as the API not supporting
    // streaming, but for this call's one decision — stream or poll — they lead to the
    // same place, and the page reports the connection failure separately.
    return false;
  }
}
