/**
 * Tests for the copilot API layer.
 *
 * Most of these guard distinctions this repository has already paid for once: `$0.00`
 * against unpriced, a refusal against a failure, a comma-joined string against a list.
 * None of them is a formatting preference — each one is a fact the API reports and the
 * UI could quietly destroy.
 */
import {
  CopilotError,
  OUTCOME_STYLE,
  formatCost,
  formatMs,
  formatPercent,
  fetchRuns,
  parseCategories,
  runAgent,
  runAsk,
} from "./copilot";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// ── the request shape ───────────────────────────────────────────────────────

describe("request shapes", () => {
  it("posts the question as `q` to /agent/query", async () => {
    // The API's field is `q`. A body of `{"question": ...}` is a 422 on every call, and
    // this is the second place that mistake is guarded because it is the easiest one to
    // make from the written plan.
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ outcome: "answered" })) as unknown as typeof fetch;
    await runAgent("how many?", { maxSteps: 3 }, fetchImpl);

    const [url, init] = (fetchImpl as unknown as jest.Mock).mock.calls[0];
    expect(url).toContain("/agent/query");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      q: "how many?",
      max_steps: 3,
      provider: undefined,
    });
  });

  it("posts the question as `q` to /ask as well", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ answered: true })) as unknown as typeof fetch;
    await runAsk("what does the corpus say?", {}, fetchImpl);
    const body = JSON.parse(
      (fetchImpl as unknown as jest.Mock).mock.calls[0][1].body as string,
    );
    expect(body.q).toBe("what does the corpus say?");
  });

  it("passes the outcome filter through to /agent/runs", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(jsonResponse({ summary: {}, recent: [] })) as unknown as typeof fetch;
    await fetchRuns(5, "refused", fetchImpl);
    expect((fetchImpl as unknown as jest.Mock).mock.calls[0][0]).toContain(
      "limit=5&outcome=refused",
    );
  });
});

// ── error handling ──────────────────────────────────────────────────────────

describe("CopilotError", () => {
  it("keeps the status code, because 503 and 502 need different responses", async () => {
    // 503 = the LLM layer is off or unreachable, and the fix is a config change.
    // 502 = the provider answered with something unusable, and the fix is to retry.
    // `apiFetch` collapses both into a bare Error, which is why this layer exists.
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(
        jsonResponse({ detail: "the LLM layer is disabled (LLM_PROVIDER=none)" }, 503),
      ) as unknown as typeof fetch;

    await expect(runAgent("q", {}, fetchImpl)).rejects.toMatchObject({
      name: "CopilotError",
      status: 503,
      message: "the LLM layer is disabled (LLM_PROVIDER=none)",
    });
  });

  it("falls back to the status when the body carries no detail", async () => {
    const fetchImpl = jest
      .fn()
      .mockResolvedValue(new Response("<html>gateway</html>", { status: 502 })) as unknown as typeof fetch;
    await expect(runAgent("q", {}, fetchImpl)).rejects.toThrow("HTTP 502");
  });

  it("is an Error, so an unguarded catch still behaves", async () => {
    const err = new CopilotError(503, "off");
    expect(err).toBeInstanceOf(Error);
  });
});

// ── the distinctions that matter ────────────────────────────────────────────

describe("formatCost", () => {
  it("renders a real zero as $0.00", () => {
    // A local model genuinely costs zero dollars per token. That is a measurement.
    expect(formatCost(0, true)).toBe("$0.00");
  });

  it("renders an unpriced model as an em dash, NOT as $0.00", () => {
    // A model missing from the rate table has an UNKNOWN cost. Rendering it as $0.00
    // asserts that unknown is zero — the single distinction this repository has restated
    // in four separate milestones.
    expect(formatCost(null)).toBe("—");
    expect(formatCost(0, false)).toBe("—");
    expect(formatCost(undefined)).toBe("—");
  });

  it("keeps four decimals on sub-cent amounts so they do not round to zero", () => {
    expect(formatCost(0.0004)).toBe("$0.0004");
    expect(formatCost(1.5)).toBe("$1.50");
  });
});

describe("formatMs", () => {
  it("distinguishes a measured zero from an absent measurement", () => {
    expect(formatMs(0)).toBe("0 ms");
    expect(formatMs(null)).toBe("—");
  });

  it("switches to seconds above a second", () => {
    expect(formatMs(272)).toBe("272 ms");
    expect(formatMs(65956)).toBe("66.0 s");
  });
});

describe("formatPercent", () => {
  it("renders a rate, and an absent rate as an em dash", () => {
    expect(formatPercent(0.3004694835680751)).toBe("30%");
    expect(formatPercent(0)).toBe("0%");
    expect(formatPercent(null)).toBe("—");
  });
});

describe("parseCategories", () => {
  it("accepts the comma-joined string /agent/runs actually returns", () => {
    // Found by reading a live response. `agent_runs.categories` is a VARCHAR(128) and
    // the endpoint declares no response model, so it emits "meta,geo,sql" while
    // /agent/query emits ["meta","geo","sql"] for the same field name.
    expect(parseCategories("meta,geo,sql")).toEqual(["meta", "geo", "sql"]);
    expect(parseCategories("sql")).toEqual(["sql"]);
  });

  it("accepts the list /agent/query returns", () => {
    expect(parseCategories(["meta", "geo"])).toEqual(["meta", "geo"]);
  });

  it("returns an empty list for a run that called no tools", () => {
    // A refused run has null here, and `null.map()` would take the whole table down.
    expect(parseCategories(null)).toEqual([]);
    expect(parseCategories(undefined)).toEqual([]);
    expect(parseCategories("")).toEqual([]);
  });
});

describe("OUTCOME_STYLE", () => {
  it("does NOT render a refusal as destructive", () => {
    // Plan §11.4.1. A refusal is a successful 200: the model declined, or every route
    // reported the data cannot answer. On the golden set that is the CORRECT result for
    // exactly the questions m13a proved unanswerable, and a red box contradicts M-17.
    expect(OUTCOME_STYLE.refused.variant).toBe("secondary");
    expect(OUTCOME_STYLE.refused.variant).not.toBe("destructive");
  });

  it("reserves destructive for the one outcome that is an error", () => {
    expect(OUTCOME_STYLE.failed.variant).toBe("destructive");
    expect(OUTCOME_STYLE.answered.variant).toBe("success");
  });

  it("marks the step cap as partial rather than as a failure", () => {
    expect(OUTCOME_STYLE.max_steps.variant).toBe("warning");
    expect(OUTCOME_STYLE.max_steps.note).toMatch(/PARTIAL/);
  });

  it("covers all four outcomes, so no run can render without a style", () => {
    expect(Object.keys(OUTCOME_STYLE).sort()).toEqual([
      "answered",
      "failed",
      "max_steps",
      "refused",
    ]);
  });
});
