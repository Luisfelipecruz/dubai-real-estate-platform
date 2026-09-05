/**
 * Tests for the gate panel.
 *
 * The failure under test is a green score describing a system that no longer exists. A
 * tool registered after a run can answer questions the agent used to decline, so every
 * rate derived from them moves while the stored score and its timestamp do not. The panel
 * has to say that before it says the number.
 */
import { render, screen } from "@testing-library/react";
import { GatePanel } from "./GatePanel";
import type { EvalReport } from "@/lib/evals";

const FRESH: EvalReport = {
  available: true,
  id: 7,
  recorded_at: "2026-09-05T12:00:00Z",
  age_seconds: 3600,
  suite: "all",
  provider: "local",
  duration_s: 1800,
  gate_applied: true,
  gate_passed: true,
  thresholds_available: true,
  floors: [
    { key: "agent.answer_accuracy", floor: 0.7, actual: 0.8, margin: 0.1, state: "ok" },
    { key: "retrieval.dense_mrr", floor: 0.75, actual: null, state: "not_measured" },
  ],
  summary: { checked: 2, ok: 1, failing: 0, not_measured: 1 },
  counts: {
    agent: { n: 41, passed: 33, route_n: 11, route_ok: 10, fabricated: 0, decoyed: 0 },
  },
  fixtures: { answers: 41, routing: 16, retrieval: 20 },
  registry: {
    known: true,
    stale: false,
    measured_against: ["area_summary"],
    registered_now: ["area_summary"],
    added_since: [],
    removed_since: [],
  },
};

describe("a recorded, current result", () => {
  it("shows the gate verdict", () => {
    render(<GatePanel report={FRESH} />);
    expect(screen.getByText("GATE PASSED")).toBeInTheDocument();
  });

  it("draws no drift warning when the registry has not moved", () => {
    render(<GatePanel report={FRESH} />);
    expect(screen.queryByTestId("registry-drift")).toBeNull();
  });

  it("prints the denominators beside the rates", () => {
    // 33/41 and 30/40 are different claims that round close enough to be confused. The
    // counts are on the page so the two can be told apart.
    render(<GatePanel report={FRESH} />);
    expect(screen.getByTestId("denominators")).toHaveTextContent("answers 33/41");
    expect(screen.getByTestId("denominators")).toHaveTextContent("routes 10/11");
  });
});

describe("the third state", () => {
  it("renders an unmeasured floor as unmeasured, not as zero", () => {
    render(<GatePanel report={FRESH} />);
    const row = screen.getByTestId("floor-retrieval.dense_mrr");
    expect(row).toHaveAttribute("data-state", "not_measured");
    expect(row).toHaveTextContent("not measured");
    expect(row).not.toHaveTextContent("0.0%");
  });

  it("counts it separately in the summary line", () => {
    render(<GatePanel report={FRESH} />);
    expect(screen.getByTestId("gate-summary")).toHaveTextContent(
      /1 not measured by this suite/,
    );
  });
});

describe("a stale result", () => {
  const stale: EvalReport = {
    ...FRESH,
    registry: {
      known: true,
      stale: true,
      measured_against: ["area_summary"],
      registered_now: ["area_summary", "dataset_aggregate"],
      added_since: ["dataset_aggregate"],
      removed_since: [],
    },
  };

  it("warns before the score, naming the tool", () => {
    render(<GatePanel report={stale} />);
    const drift = screen.getByTestId("registry-drift");
    expect(drift).toHaveAttribute("data-level", "stale");
    expect(drift).toHaveTextContent("dataset_aggregate");
  });

  it("still shows the score, because the score is a real past reading", () => {
    // Hiding it would be the opposite failure: an unreadable page teaches nobody that the
    // measurement is owed. It is shown, dated, and qualified.
    render(<GatePanel report={stale} />);
    expect(screen.getByText("GATE PASSED")).toBeInTheDocument();
  });
});

describe("an unverifiable result", () => {
  it("distinguishes 'cannot tell' from 'unchanged'", () => {
    render(
      <GatePanel
        report={{
          ...FRESH,
          registry: {
            known: false,
            stale: null,
            measured_against: null,
            registered_now: null,
            added_since: [],
            removed_since: [],
          },
        }}
      />,
    );
    expect(screen.getByTestId("registry-drift")).toHaveAttribute("data-level", "unknown");
  });
});

describe("an ungated run", () => {
  it("draws no verdict where none was computed", () => {
    render(
      <GatePanel
        report={{ ...FRESH, gate_applied: false, gate_passed: null }}
      />,
    );
    expect(screen.queryByText("GATE PASSED")).toBeNull();
    expect(screen.queryByText("GATE FAILED")).toBeNull();
    expect(screen.getByText("gate not applied")).toBeInTheDocument();
  });
});

describe("nothing recorded yet", () => {
  const empty: EvalReport = {
    available: false,
    reason: "No eval run has been recorded. Run `make eval`, which grades the fixtures.",
    thresholds_available: true,
    floors: [
      { key: "agent.answer_accuracy", floor: 0.7, actual: null, state: "not_measured" },
    ],
  };

  it("still lists the floors, because they exist without a run", () => {
    render(<GatePanel report={empty} />);
    expect(screen.getByTestId("floor-table")).toBeInTheDocument();
    expect(screen.getByTestId("floor-agent.answer_accuracy")).toHaveAttribute(
      "data-state",
      "not_measured",
    );
  });

  it("says what to run", () => {
    render(<GatePanel report={empty} />);
    expect(screen.getByTestId("gate-panel")).toHaveTextContent("make eval");
  });

  it("shows no gate badge at all", () => {
    render(<GatePanel report={empty} />);
    expect(screen.queryByText(/GATE (PASSED|FAILED)/)).toBeNull();
  });
});
