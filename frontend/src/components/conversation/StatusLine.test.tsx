import { render, screen } from "@testing-library/react";
import { StatusLine } from "./StatusLine";
import ANSWERED_EMPTY from "@/lib/__fixtures__/agent-answered-empty.json";
import type { AgentResponse } from "@/lib/copilot";
import {
  INITIAL_PROGRESS,
  markIncomplete,
  progressFrom,
  progressFromResponse,
} from "@/lib/progress";

const EMPTY_RUN = ANSWERED_EMPTY as unknown as AgentResponse;

describe("StatusLine", () => {
  it("renders nothing before an event arrives", () => {
    const { container } = render(<StatusLine state={INITIAL_PROGRESS} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows one row per event and the closing line", () => {
    render(<StatusLine state={progressFromResponse(EMPTY_RUN)} />);
    expect(screen.getAllByTestId("status-row")).toHaveLength(7);
  });

  it("shows no tool name, argument or payload", () => {
    render(<StatusLine state={progressFromResponse(EMPTY_RUN)} />);
    const text = screen.getByTestId("status-line").textContent ?? "";
    expect(text).not.toContain("resolve_area_name");
    expect(text).not.toContain("area_price_history");
    expect(text).not.toContain("{");
  });

  it("marks the failed call as failed rather than as a tick", () => {
    // M-62: 10.3% of tool calls fail. A surface where every line is a tick is
    // claiming a reliability the system does not have.
    render(<StatusLine state={progressFromResponse(EMPTY_RUN)} />);
    expect(screen.getByText("Could not match that area name")).toBeInTheDocument();
    expect(screen.getAllByTestId("icon-failed").length).toBeGreaterThan(0);
  });

  it("renders measured durations and no estimate", () => {
    render(<StatusLine state={progressFromResponse(EMPTY_RUN)} />);
    // 2181 ms, formatted by the shared helper. Nothing on screen projects a total.
    expect(screen.getByText("2.2 s")).toBeInTheDocument();
    expect(screen.queryByText(/remaining/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/usually takes/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("shows the in-flight line with a spinner and marks the region busy", () => {
    const state = progressFrom([
      {
        type: "step",
        step: 1,
        tool: "area_neighbors",
        category: "geo",
        arguments: {},
      },
    ]);
    render(<StatusLine state={state} />);
    expect(screen.getByText("Checking which areas border it…")).toBeInTheDocument();
    expect(screen.getByTestId("status-line")).toHaveAttribute("aria-busy", "true");
  });

  it("stops claiming to be busy once the run finishes", () => {
    render(<StatusLine state={progressFromResponse(EMPTY_RUN)} />);
    expect(screen.getByTestId("status-line")).toHaveAttribute("aria-busy", "false");
  });

  it("surfaces a truncated stream instead of leaving a spinner up", () => {
    const partial = progressFrom([
      {
        type: "step",
        step: 1,
        tool: "area_summary",
        category: "sql",
        arguments: {},
      },
    ]);
    render(
      <StatusLine state={markIncomplete(partial, "the run did not finish")} />,
    );
    expect(screen.getByTestId("status-error")).toHaveTextContent(
      "the run did not finish",
    );
    expect(
      screen.getByText("The connection ended before the run finished"),
    ).toBeInTheDocument();
  });

  it("does not render a refusal as a failure", () => {
    const state = progressFrom([
      {
        type: "done",
        run_id: "r",
        outcome: "refused",
        answer: "I can't answer that.",
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
    render(<StatusLine state={state} />);
    expect(screen.getByTestId("status-row")).toHaveAttribute("data-tone", "note");
    expect(screen.queryByTestId("icon-failed")).not.toBeInTheDocument();
  });
});
