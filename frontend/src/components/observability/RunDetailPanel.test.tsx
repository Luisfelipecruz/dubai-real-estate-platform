/**
 * Tests for the run drill-in.
 *
 * The failure under test is a panel that answers "which tool failed" with silence. The
 * list row above it already reports `6 tool calls (2 failed)`; this component exists only
 * to say WHICH two and why, so every test here is about a way that could be lost — a
 * failure drawn without its message, an empty list drawn as "no tools were called", a
 * repeat summed into the error count, or the two different call counts conflated.
 */
import { render, screen } from "@testing-library/react";
import { RunDetailPanel } from "./RunDetailPanel";
import type { RunDetail, ToolStep } from "@/lib/copilot";

function step(over: Partial<ToolStep> = {}): ToolStep {
  return {
    id: 1,
    step: 1,
    tool_name: "dataset_aggregate",
    category: "sql",
    arguments: { dataset: "valuations", metric: "count" },
    ok: true,
    error: null,
    duration_ms: 189,
    repeated: false,
    created_at: "2026-09-05T12:00:00Z",
    ...over,
  };
}

function detail(over: Partial<RunDetail> = {}): RunDetail {
  const steps = over.tool_steps ?? [step()];
  return {
    run: {
      id: "9a953f73",
      created_at: "2026-09-05T12:00:00Z",
      provider: "ollama",
      model: "gpt-oss:20b",
      question: "How many valuations were recorded in 2024?",
      answer: "3,106.",
      outcome: "answered",
      steps: 2,
      tool_calls: steps.length,
      tool_errors: steps.filter((s) => !s.ok).length,
      categories: ["sql"],
      total_cost_usd: 0,
      cost_priced: false,
      input_tokens: 900,
      output_tokens: 120,
      latency_ms: 8400,
      tool_ms: 189,
      unverified_numbers: 0,
      ...over.run,
    },
    model_turns: [],
    model_turn_count: 2,
    tool_steps: steps,
    tool_step_count: steps.length,
    tool_steps_available: true,
    tool_steps_recorded: true,
    tool_steps_complete: true,
    tool_steps_note: null,
    ...over,
  };
}

describe("the calls behind a run", () => {
  it("names the tool, which is the whole reason this exists", () => {
    render(<RunDetailPanel detail={detail()} />);
    expect(screen.getByTestId("tool-step")).toHaveAttribute(
      "data-tool",
      "dataset_aggregate",
    );
  });

  it("shows the arguments, because 'failed on which name?' is the next question", () => {
    render(<RunDetailPanel detail={detail()} />);
    expect(screen.getByTestId("tool-step")).toHaveTextContent("valuations");
  });

  it("draws a failure with the message the model actually read", () => {
    // Not a summary of it. The run refused BECAUSE resolve_area_name said this, and the
    // text is what makes the refusal legible as correct rather than as a bug.
    render(
      <RunDetailPanel
        detail={detail({
          tool_steps: [
            step({
              tool_name: "resolve_area_name",
              category: "meta",
              ok: false,
              error: "No Dubai area matches 'Atlantis Tower'.",
            }),
          ],
        })}
      />,
    );
    expect(screen.getByTestId("tool-step")).toHaveAttribute("data-ok", "false");
    expect(screen.getByTestId("tool-step-error")).toHaveTextContent("Atlantis Tower");
  });

  it("marks a repeat as a repeat and not as a failure", () => {
    // A repeat is a ROUTING problem. Summing it into the tool error rate would attribute
    // a planning fault to the tool that answered correctly twice.
    render(
      <RunDetailPanel detail={detail({ tool_steps: [step({ repeated: true })] })} />,
    );
    expect(screen.getByTestId("repeated-call")).toBeInTheDocument();
    expect(screen.getByTestId("tool-step")).toHaveAttribute("data-ok", "true");
  });

  it("counts model turns separately from tool calls", () => {
    // Two different measurements. A page that showed one number would be asserting they
    // are the same, and they are not.
    render(
      <RunDetailPanel
        detail={detail({ tool_steps: [step(), step({ id: 2, step: 2 })], model_turn_count: 3 })}
      />,
    );
    const counts = screen.getByTestId("run-detail-counts");
    expect(counts).toHaveTextContent("2 tool calls recorded");
    expect(counts).toHaveTextContent("3 model turns");
  });
});

describe("an empty step list, which is four different facts", () => {
  it("prints the API's own sentence rather than inventing one", () => {
    // The component does not decide which state this is. `tool_steps_note` is computed
    // in `services/observability/queries` with its own tests, and re-deriving it here
    // would be a second place the rule lives.
    render(
      <RunDetailPanel
        detail={detail({
          tool_steps: [],
          tool_step_count: 0,
          tool_steps_recorded: false,
          tool_steps_complete: false,
          tool_steps_note:
            "This run made 6 tool call(s) and none were recorded. Attribution starts at migration 0005",
        })}
      />,
    );
    expect(screen.getByTestId("tool-steps-note")).toHaveTextContent(
      "none were recorded",
    );
  });

  it("never renders a missing record as 'no tools were called'", () => {
    render(
      <RunDetailPanel
        detail={detail({
          tool_steps: [],
          tool_step_count: 0,
          tool_steps_available: false,
          tool_steps_recorded: false,
          tool_steps_note: "agent_tool_calls does not exist -- run `alembic upgrade head`",
        })}
      />,
    );
    expect(screen.queryByText(/called no tools/)).toBeNull();
    expect(screen.getByTestId("tool-steps-note")).toHaveTextContent(
      "alembic upgrade head",
    );
  });

  it("stays silent when the steps agree with the run's own counter", () => {
    render(<RunDetailPanel detail={detail()} />);
    expect(screen.queryByTestId("tool-steps-note")).toBeNull();
  });
});

describe("the figures the run could not verify", () => {
  it("surfaces them, because an unverified number is the damaging output", () => {
    render(
      <RunDetailPanel
        detail={detail({ run: { ...detail().run, unverified_numbers: 2 } })}
      />,
    );
    expect(screen.getByTestId("run-detail")).toHaveTextContent("2 unverified figures");
  });

  it("says nothing when there were none", () => {
    render(<RunDetailPanel detail={detail()} />);
    expect(screen.getByTestId("run-detail")).not.toHaveTextContent("unverified");
  });
});
