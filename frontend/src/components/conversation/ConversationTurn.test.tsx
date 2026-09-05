import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConversationTurn } from "./ConversationTurn";
import ANSWERED_EMPTY from "@/lib/__fixtures__/agent-answered-empty.json";
import MAX_STEPS from "@/lib/__fixtures__/agent-max-steps.json";
import REFUSED from "@/lib/__fixtures__/agent-refused.json";
import type { AgentResponse, AgentStep } from "@/lib/copilot";
import { INITIAL_PROGRESS, progressFrom, progressFromResponse } from "@/lib/progress";

const EMPTY_RUN = ANSWERED_EMPTY as unknown as AgentResponse;
const CAPPED_RUN = MAX_STEPS as unknown as AgentResponse;
const REFUSED_RUN = REFUSED as unknown as AgentResponse;

function answered(answer: string) {
  return progressFrom([
    {
      type: "done",
      run_id: "r",
      outcome: "answered",
      answer,
      categories: ["sql"],
      grounding_warnings: [],
      timings_ms: { generate: 1, tools: 1, total: 2 },
      usage: {
        steps: 1,
        tool_calls: 1,
        tool_errors: 0,
        cost_usd: null,
        cost_priced: false,
      },
    },
  ]);
}

describe("the default view", () => {
  it("shows the answer and no tool names", () => {
    render(
      <ConversationTurn
        question="How many sales in Business Bay?"
        state={answered("Business Bay recorded 44,312 sales.")}
        steps={EMPTY_RUN.steps as AgentStep[]}
      />,
    );
    expect(screen.getByTestId("turn-body")).toHaveTextContent("44,312 sales");
    const shown = screen.getByTestId("conversation-turn").textContent ?? "";
    expect(shown).not.toContain("resolve_area_name");
    expect(shown).not.toContain("area_summary");
  });

  it("shows the status line while the run is in flight", () => {
    const running = progressFrom([
      {
        type: "step",
        step: 1,
        tool: "resolve_area_name",
        category: "meta",
        arguments: {},
      },
    ]);
    render(<ConversationTurn question="q" state={running} steps={[]} />);
    expect(screen.getByText("Finding the area you mean…")).toBeInTheDocument();
    expect(screen.queryByTestId("turn-answer")).not.toBeInTheDocument();
  });

  it("says the trace is not live when the API cannot stream", () => {
    render(<ConversationTurn question="q" state={INITIAL_PROGRESS} steps={[]} />);
    expect(screen.getByTestId("not-live-notice")).toHaveTextContent(
      "nothing appears until the run finishes",
    );
  });

  it("drops that notice once the API can stream", () => {
    render(
      <ConversationTurn
        question="q"
        state={INITIAL_PROGRESS}
        steps={[]}
        streamingAvailable
      />,
    );
    expect(screen.queryByTestId("not-live-notice")).not.toBeInTheDocument();
  });
});

describe("the evidence is always one click away", () => {
  // The line that must not be crossed: evidence is one click away from every outcome.
  const cases: Array<[string, ReturnType<typeof progressFromResponse>, AgentStep[]]> = [
    ["an ordinary answer", answered("Marsa Dubai recorded 61,286 sales."), EMPTY_RUN.steps as AgentStep[]],
    ["an empty answer", progressFromResponse(EMPTY_RUN), EMPTY_RUN.steps as AgentStep[]],
    ["a refusal", progressFromResponse(REFUSED_RUN), REFUSED_RUN.steps as AgentStep[]],
    ["a capped run", progressFromResponse(CAPPED_RUN), CAPPED_RUN.steps as AgentStep[]],
  ];

  it.each(cases)("offers the toggle on %s", (_label, state, steps) => {
    render(<ConversationTurn question="q" state={state} steps={steps} />);
    expect(screen.getByTestId("evidence-toggle")).toBeInTheDocument();
  });

  it("reveals the complete, unmodified trace in one click", async () => {
    const user = userEvent.setup();
    render(
      <ConversationTurn
        question="q"
        state={progressFromResponse(EMPTY_RUN)}
        steps={EMPTY_RUN.steps as AgentStep[]}
      />,
    );

    expect(screen.queryByTestId("evidence-trace")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("evidence-toggle"));

    // The same evidence component, with all seven steps. Collapsed is not deleted.
    expect(screen.getByTestId("evidence-trace")).toBeInTheDocument();
    expect(screen.getByText("step 4")).toBeInTheDocument();
    expect(screen.getAllByText("resolve_area_name").length).toBeGreaterThan(0);
  });

  it("counts the steps and names the failures on the button itself", () => {
    render(
      <ConversationTurn
        question="q"
        state={progressFromResponse(EMPTY_RUN)}
        steps={EMPTY_RUN.steps as AgentStep[]}
      />,
    );
    // SEVEN steps, one of which contains a failed call. The old assertion said six,
    // because the label counted tool-producing steps while the panel below it listed
    // every step including the reasoning-only synthesis turn -- and the comment here
    // said "tool calls" while the label said "steps". The invariant is that the button
    // describes the panel it opens, so both now come from the same array.
    expect(screen.getByTestId("evidence-toggle")).toHaveTextContent("7 steps, 1 failed");
  });
});

describe("the outcomes that are not an answer", () => {
  it("names the empty-answer defect rather than showing a blank card", () => {
    render(
      <ConversationTurn
        question="q"
        state={progressFromResponse(EMPTY_RUN)}
        steps={EMPTY_RUN.steps as AgentStep[]}
      />,
    );
    // Behind a conversational surface this run is otherwise a blank
    // screen after 66 seconds.
    expect(screen.getByTestId("turn-empty")).toHaveTextContent(
      "could not write the summary",
    );
    expect(screen.queryByTestId("turn-body")).not.toBeInTheDocument();
  });

  it("reads a refusal as a deliberate stop, not an error", () => {
    render(
      <ConversationTurn
        question="q"
        state={progressFromResponse(REFUSED_RUN)}
        steps={REFUSED_RUN.steps as AgentStep[]}
      />,
    );
    const notice = screen.getByTestId("turn-refused");
    expect(notice).toHaveTextContent("can't answer that from the data I have");
    expect(notice).toHaveTextContent("intended behaviour");
    expect(notice).not.toHaveTextContent(/error|failed/i);
  });

  it("says a capped run is partial in words a non-engineer reads correctly", () => {
    render(
      <ConversationTurn
        question="q"
        state={progressFromResponse(CAPPED_RUN)}
        steps={CAPPED_RUN.steps as AgentStep[]}
      />,
    );
    const notice = screen.getByTestId("turn-capped");
    expect(notice).toHaveTextContent("ran out of steps");
    expect(notice).toHaveTextContent("partial");
    expect(notice).not.toHaveTextContent("max_steps");
  });
});

describe("grounding warnings", () => {
  const warnings = [
    "the step cap (2) was reached before the model produced an answer. Everything below is PARTIAL.",
  ];

  it("shows them WITHOUT a click", async () => {
    render(
      <ConversationTurn
        question="q"
        state={progressFromResponse(CAPPED_RUN)}
        steps={CAPPED_RUN.steps as AgentStep[]}
        warnings={warnings}
      />,
    );
    // Not evidence a curious reader might want — a caveat attached to the answer.
    // Hiding one behind a click would be suppressing it.
    expect(screen.getByTestId("turn-warnings")).toHaveTextContent("step cap (2)");
  });

  it("quotes them verbatim rather than paraphrasing", () => {
    render(
      <ConversationTurn
        question="q"
        state={progressFromResponse(CAPPED_RUN)}
        steps={CAPPED_RUN.steps as AgentStep[]}
        warnings={warnings}
      />,
    );
    expect(screen.getByText(warnings[0])).toBeInTheDocument();
  });
});
