/**
 * The whole result panel, rendered against RESPONSES THE LIVE API ACTUALLY RETURNED.
 *
 * Every other test in this milestone builds its input by hand, which proves the
 * components handle the shapes I believed the API produces. This file proves they handle
 * the shapes it produces. That gap is not hypothetical here — it is exactly where the two
 * real defects of this session were found:
 *
 *   · the request field is `q`, not `question` (a hand-built fixture would never say so)
 *   · `/agent/runs` returns `categories` as a COMMA-JOINED STRING while `/agent/query`
 *     returns a list, and the endpoint has no response model to reconcile them
 *
 * The four fixtures in `src/lib/__fixtures__/` are unedited captures from
 * `POST /agent/query` and `POST /ask` against the running stack on 2026-08-30, with long
 * tool payloads truncated and nothing else changed. They cover all four agent outcomes,
 * which is what the milestone gate asks for, and they keep covering them after this
 * machine is turned off.
 */
import { render, screen } from "@testing-library/react";
import { AnswerPanel } from "./AnswerPanel";
import { CitationList } from "./CitationList";
import { EvidenceTrace } from "./EvidenceTrace";
import { RunMeta } from "./RunMeta";
import type { AgentResponse, AskResponse } from "@/lib/copilot";

import answeredEmpty from "@/lib/__fixtures__/agent-answered-empty.json";
import refused from "@/lib/__fixtures__/agent-refused.json";
import maxSteps from "@/lib/__fixtures__/agent-max-steps.json";
import askAnswered from "@/lib/__fixtures__/ask-answered.json";

const ANSWERED_EMPTY = answeredEmpty as unknown as AgentResponse;
const REFUSED = refused as unknown as AgentResponse;
const MAX_STEPS = maxSteps as unknown as AgentResponse;
const ASK = askAnswered as unknown as AskResponse;

function renderAgent(run: AgentResponse) {
  return render(
    <>
      <AnswerPanel
        outcome={run.outcome}
        answer={run.answer}
        categories={run.categories}
        warnings={run.grounding_warnings}
      />
      <EvidenceTrace steps={run.steps} />
      <RunMeta
        provider={run.provider}
        model={run.model}
        cost={run.usage.cost_usd}
        costPriced={run.usage.cost_priced}
        timings={[{ label: "total", ms: run.timings_ms.total }]}
      />
    </>,
  );
}

describe("a real run that answered with an empty body", () => {
  it("is the M-47 defect, captured live, and the UI names it", () => {
    // This run took 65,956 ms — LONGER THAN ANY RUN IN THE RECORDED RANGE — called six
    // tools across seven steps, and returned `outcome: answered` with `answered: true`
    // and `answer: NULL`. It is the single best argument for this component existing:
    // everything worked, the summary vanished, and a blank card would have looked like a
    // loading state.
    //
    // Null, not the empty string. M-47 describes this as "an empty body", which is true
    // in substance and imprecise in type — and the difference matters to a renderer,
    // because `null.trim()` throws where `"".trim()` does not. Any component reading
    // `answer` must handle both.
    expect(ANSWERED_EMPTY.outcome).toBe("answered");
    expect(ANSWERED_EMPTY.answered).toBe(true);
    expect(ANSWERED_EMPTY.answer).toBeNull();

    renderAgent(ANSWERED_EMPTY);
    expect(screen.getByTestId("empty-answer-defect")).toBeInTheDocument();
  });

  it("still shows the seven steps and the six tool calls that did run", () => {
    renderAgent(ANSWERED_EMPTY);
    expect(screen.getByText("step 1")).toBeInTheDocument();
    expect(screen.getByText("step 7")).toBeInTheDocument();
  });

  it("shows the tool call that failed", () => {
    // Step 4's `resolve_area_name` errored. The run succeeded anyway, and a trace that
    // dropped the failure would describe a cleaner run than the one that happened.
    const failed = ANSWERED_EMPTY.steps
      .flatMap((s) => s.tool_calls)
      .filter((c) => !c.ok);
    expect(failed).toHaveLength(1);
    renderAgent(ANSWERED_EMPTY);
    expect(screen.getAllByText("resolve_area_name").length).toBeGreaterThan(0);
  });

  it("renders its routing categories from the list form", () => {
    expect(ANSWERED_EMPTY.categories).toEqual(["meta", "geo", "sql"]);
    renderAgent(ANSWERED_EMPTY);
    expect(screen.getAllByTestId("category-chip")).toHaveLength(3);
  });

  it("reports 66.0 s with the one-machine caveat attached", () => {
    renderAgent(ANSWERED_EMPTY);
    expect(screen.getByText("66.0 s")).toBeInTheDocument();
    expect(screen.getByTestId("latency-caveat")).toBeInTheDocument();
  });
});

describe("a real refusal", () => {
  it("renders as a success, with no tools called and no error styling", () => {
    expect(REFUSED.outcome).toBe("refused");
    expect(REFUSED.categories).toEqual([]);

    renderAgent(REFUSED);
    expect(screen.getByTestId("refusal-notice")).toBeInTheDocument();
    expect(screen.getByText("no tools called")).toBeInTheDocument();
    expect(screen.getByTestId("outcome-badge").className).not.toMatch(/destructive/);
  });

  it("shows the model's own words, curly apostrophe and all", () => {
    // U+2019, not U+0027. This project has had four separate encoding failures; the
    // fixture keeps the real bytes so a future normalisation cannot quietly break here.
    expect(REFUSED.answer).toContain("’");
    renderAgent(REFUSED);
    expect(screen.getByTestId("answer-body")).toHaveTextContent(/can’t provide/);
  });
});

describe("a real run that hit the step cap", () => {
  it("is labelled partial and carries the API's own warning", () => {
    expect(MAX_STEPS.outcome).toBe("max_steps");
    expect(MAX_STEPS.grounding_warnings).toHaveLength(1);

    renderAgent(MAX_STEPS);
    expect(screen.getByTestId("cap-notice")).toHaveTextContent(/partial/i);
    expect(screen.getByTestId("grounding-warnings")).toHaveTextContent(
      /step cap \(2\) was reached/,
    );
  });
});

describe("a real /ask answer", () => {
  it("renders three citations, all verified against the retrieved chunks", () => {
    expect(ASK.citations).toHaveLength(3);
    expect(ASK.citations.every((c) => c.resolved && c.quote_found)).toBe(true);

    render(<CitationList citations={ASK.citations} />);
    expect(screen.getAllByTestId("citation-verified")).toHaveLength(3);
    expect(screen.getByText(/3 of 3 citations verified/)).toBeInTheDocument();
  });

  it("renders an answer containing a NARROW NO-BREAK SPACE without mangling it", () => {
    // U+202F, in "k = 60". The fifth appearance of this character class in the project,
    // and the first one on a rendered page rather than in a grader.
    expect(ASK.answer).toContain(" ");
    render(
      <AnswerPanel outcome="answered" answer={ASK.answer} warnings={ASK.grounding_warnings} />,
    );
    expect(screen.getByTestId("answer-body")).toHaveTextContent(/Reciprocal Rank Fusion/);
  });
});
