/**
 * Tests for the badge, driven from the comparison the API actually returned.
 *
 * The specific failure under test: the last two recorded hours hold three runs and two,
 * and a naive badge turns them into four red alarms. Every assertion here is about what
 * the panel is allowed to claim from that.
 */
import { render, screen } from "@testing-library/react";
import { TrendBadge } from "./TrendBadge";
import { LIVE_HEALTH, WIDE_TREND } from "@/lib/observability.fixture";
import type { Trend } from "@/lib/observability";

const [REFUSAL, TOOL_ERRORS, EMPTY_ANSWERS, , P95] = LIVE_HEALTH.trends;

function toneOf(): string | null {
  return screen.getByTestId("trend-badge").getAttribute("data-tone");
}

it("does not raise an alarm from a movement three runs cannot measure", () => {
  render(<TrendBadge trend={REFUSAL} />);
  expect(toneOf()).toBe("neutral");
  expect(screen.queryByTestId("icon-up")).toBeNull();
  expect(screen.getByTestId("icon-noise")).toBeInTheDocument();
});

it("says why, in a sentence, rather than only in a colour", () => {
  render(<TrendBadge trend={REFUSAL} />);
  expect(screen.getByTestId("trend-caveat")).toHaveTextContent(
    /smaller than this sample can measure/i,
  );
  expect(screen.getByTestId("trend-caveat")).toHaveTextContent("50.0%");
});

it("prints the denominators next to the number, not behind a tooltip", () => {
  render(<TrendBadge trend={REFUSAL} />);
  expect(screen.getByTestId("trend-sample")).toHaveTextContent("3 vs 2 runs");
});

it("still shows the delta, because the number is real and only the conclusion is not", () => {
  render(<TrendBadge trend={REFUSAL} />);
  expect(screen.getByTestId("trend-delta")).toHaveTextContent("+33.3 pts");
});

it("does raise an alarm once the same metric has the runs behind it", () => {
  render(<TrendBadge trend={WIDE_TREND} />);
  expect(toneOf()).toBe("alarm");
  expect(screen.getByTestId("icon-up")).toBeInTheDocument();
  expect(screen.getByTestId("trend-sample")).toHaveTextContent("40 vs 49 runs");
  expect(screen.queryByTestId("trend-caveat")).toBeNull();
});

it("reads a fall in a lower-is-better metric as better", () => {
  const improving: Trend = {
    ...WIDE_TREND,
    current: 9 / 49,
    previous: 16 / 40,
    delta: 9 / 49 - 16 / 40,
    direction: "down",
  };
  render(<TrendBadge trend={improving} />);
  expect(toneOf()).toBe("better");
  expect(screen.getByTestId("icon-down")).toBeInTheDocument();
});

it("renders an unmeasured metric as an em dash and never as zero", () => {
  render(<TrendBadge trend={P95} />);
  expect(toneOf()).toBe("unknown");
  expect(screen.getByTestId("trend-delta")).toHaveTextContent("—");
  expect(screen.queryByText("0.0%")).toBeNull();
  expect(screen.getByTestId("trend-caveat")).toHaveTextContent(/not measured/i);
});

it("labels a latency delta in time and not in percentage points", () => {
  const slower: Trend = {
    metric: "p95_ms",
    current: 46603,
    previous: 38886,
    delta: 7717,
    direction: "up",
    current_n: null,
    previous_n: null,
    resolution: null,
  };
  render(<TrendBadge trend={slower} />);
  expect(screen.getByTestId("trend-delta")).not.toHaveTextContent("pts");
  expect(screen.getByTestId("trend-delta")).toHaveTextContent("+7.7 s");
});

it("keeps the metric and its direction readable from the DOM for the panel above it", () => {
  render(<TrendBadge trend={TOOL_ERRORS} />);
  const badge = screen.getByTestId("trend-badge");
  expect(badge).toHaveAttribute("data-metric", "tool_error_rate");
  expect(badge).toHaveAttribute("data-direction", "indistinguishable");
});

it("names the metric in words rather than by its column", () => {
  render(<TrendBadge trend={EMPTY_ANSWERS} />);
  expect(screen.getByText(/answered but empty/i)).toBeInTheDocument();
  expect(screen.queryByText("empty_answer_rate")).toBeNull();
});

it("shows the previous value beside the current one", () => {
  render(<TrendBadge trend={WIDE_TREND} />);
  expect(screen.getByText("40.0%")).toBeInTheDocument();
  expect(screen.getByText(/was 18\.4%/)).toBeInTheDocument();
});
