/**
 * Tests for the tool-error panel.
 *
 * The failure under test is a chart with no bars reading as a system with no failures.
 * 31 of 301 tool calls failed and the database cannot name one of them; the panel has to
 * say the second part as loudly as the first.
 */
import { render, screen } from "@testing-library/react";
import { AttributionNotice } from "./AttributionNotice";
import { ATTRIBUTED, UNATTRIBUTABLE } from "@/lib/observability.fixture";

describe("when the failing tool cannot be named", () => {
  it("states the rate, which is real", () => {
    render(<AttributionNotice attribution={UNATTRIBUTABLE} />);
    expect(screen.getByText("10.3%")).toBeInTheDocument();
    expect(screen.getByText(/31 of 301 calls/)).toBeInTheDocument();
  });

  it("renders no breakdown at all rather than an empty one", () => {
    render(<AttributionNotice attribution={UNATTRIBUTABLE} />);
    expect(screen.queryByTestId("attribution-table")).toBeNull();
    expect(screen.queryAllByTestId("attribution-row")).toHaveLength(0);
  });

  it("says the errors cannot be traced, in words", () => {
    render(<AttributionNotice attribution={UNATTRIBUTABLE} />);
    expect(screen.getByTestId("attribution-unavailable")).toHaveTextContent(
      /cannot be traced to a tool/i,
    );
  });

  it("quotes the reason from the API rather than paraphrasing it", () => {
    render(<AttributionNotice attribution={UNATTRIBUTABLE} />);
    expect(screen.getByTestId("attribution-reason")).toHaveTextContent(
      /agent_runs stores tool_calls and tool_errors as integers/,
    );
  });

  it("carries the remedy, so the reader knows what would fix it", () => {
    render(<AttributionNotice attribution={UNATTRIBUTABLE} />);
    expect(screen.getByTestId("attribution-remedy")).toHaveTextContent(
      /migration 0004/,
    );
  });

  it("marks its state in the DOM for the panel around it", () => {
    render(<AttributionNotice attribution={UNATTRIBUTABLE} />);
    expect(screen.getByTestId("attribution")).toHaveAttribute(
      "data-attributable",
      "false",
    );
  });
});

describe("once the per-call records exist", () => {
  it("names each tool with its own error rate", () => {
    render(<AttributionNotice attribution={ATTRIBUTED} />);
    const rows = screen.getAllByTestId("attribution-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("data-tool", "resolve_area_name");
    expect(rows[0]).toHaveTextContent("50.0%");
  });

  it("stops showing the caveat once it no longer applies", () => {
    render(<AttributionNotice attribution={ATTRIBUTED} />);
    expect(screen.queryByTestId("attribution-unavailable")).toBeNull();
    expect(screen.queryByText(/migration 0004/)).toBeNull();
  });

  it("shows a tool that never failed as 0.0% and not as an em dash", () => {
    render(<AttributionNotice attribution={ATTRIBUTED} />);
    const rows = screen.getAllByTestId("attribution-row");
    expect(rows[1]).toHaveAttribute("data-tool", "area_summary");
    expect(rows[1]).toHaveTextContent("0.0%");
  });
});
