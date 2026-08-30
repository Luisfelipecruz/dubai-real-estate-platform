/**
 * Tests for the tool trace.
 *
 * Built against the shape of a real run: seven steps, six tool calls, one of which
 * failed. The failed call is the interesting one — a trace that quietly drops it would
 * describe a cleaner run than the one that happened.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EvidenceTrace } from "./EvidenceTrace";
import type { AgentStep } from "@/lib/copilot";

function step(overrides: Partial<AgentStep> = {}): AgentStep {
  return {
    step: 1,
    text: null,
    tool_calls: [],
    input_tokens: 100,
    output_tokens: 20,
    cost_usd: 0,
    latency_ms: 272,
    stop_reason: null,
    ...overrides,
  };
}

const RESOLVE_AREA = {
  step: 1,
  name: "resolve_area_name",
  category: "meta",
  arguments: { name: "Business Bay" },
  ok: true,
  duration_ms: 272,
  result: '{"area_name_en": "Business Bay"}',
  repeated: false,
};

describe("EvidenceTrace", () => {
  it("renders one row per step", () => {
    render(
      <EvidenceTrace
        steps={[step({ step: 1 }), step({ step: 2 }), step({ step: 3 })]}
      />,
    );
    expect(screen.getByText("step 1")).toBeInTheDocument();
    expect(screen.getByText("step 3")).toBeInTheDocument();
  });

  it("shows a failed tool call rather than hiding it", () => {
    // The run captured while writing this page called `resolve_area_name` twice and the
    // second attempt errored. Ten percent of all tool calls in this deployment fail;
    // that is a real number and the trace is where it is visible.
    render(
      <EvidenceTrace
        steps={[step({ tool_calls: [{ ...RESOLVE_AREA, ok: false }] })]}
      />,
    );
    expect(screen.getByText("resolve_area_name")).toBeInTheDocument();
  });

  it("expands to show arguments and the raw tool result", async () => {
    const user = userEvent.setup();
    render(<EvidenceTrace steps={[step({ tool_calls: [RESOLVE_AREA] })]} />);

    expect(screen.queryByText(/tool error/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button"));

    // Both blocks are asserted separately: the arguments the model chose and the payload
    // the tool returned are different evidence, and "Business Bay" alone appears in both.
    expect(screen.getByText(/"name": "Business Bay"/)).toBeInTheDocument();
    expect(screen.getByText(/area_name_en/)).toBeInTheDocument();
  });

  it("labels a repeated call as served from cache", async () => {
    const user = userEvent.setup();
    render(
      <EvidenceTrace
        steps={[step({ tool_calls: [{ ...RESOLVE_AREA, repeated: true }] })]}
      />,
    );
    await user.click(screen.getByRole("button"));
    expect(screen.getByText(/served from cache/i)).toBeInTheDocument();
  });

  it("renders an unpriced step as an em dash, not as $0.00", () => {
    // `cost_usd: null` means the model is not in the rate table. Rendering it as $0.00
    // asserts that unknown is zero.
    render(<EvidenceTrace steps={[step({ cost_usd: null })]} />);
    expect(screen.getByText(/—/)).toBeInTheDocument();
  });

  it("renders a genuinely free step as $0.00", () => {
    render(<EvidenceTrace steps={[step({ cost_usd: 0 })]} />);
    expect(screen.getByText(/\$0\.00/)).toBeInTheDocument();
  });

  it("says so when a step called no tools", () => {
    render(<EvidenceTrace steps={[step()]} />);
    expect(screen.getByText("reasoning only")).toBeInTheDocument();
  });

  it("handles a run with no steps at all", () => {
    // The refused run in this session's captures: one turn, zero tools.
    render(<EvidenceTrace steps={[]} />);
    expect(screen.getByText(/without calling a tool/i)).toBeInTheDocument();
  });
});
