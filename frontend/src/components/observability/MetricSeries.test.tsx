/**
 * Tests for the chart, driven from the six real hours.
 *
 * One assertion carries the milestone: the hour with no runs must not be drawn through.
 * A single polyline over this series joins 18:00 to 20:00 with a straight line that is
 * indistinguishable from an hour of steady performance -- the chart would be inventing its
 * most reassuring data point.
 */
import { render, screen } from "@testing-library/react";
import { MetricSeries } from "./MetricSeries";
import { LIVE_HOURLY } from "@/lib/observability.fixture";

it("draws two segments across an hour with no runs, not one line through it", () => {
  render(<MetricSeries buckets={LIVE_HOURLY} metric="refusal_rate" />);
  expect(screen.getAllByTestId("series-segment")).toHaveLength(2);
});

it("marks the empty hour instead of leaving it to be read as a value", () => {
  render(<MetricSeries buckets={LIVE_HOURLY} metric="refusal_rate" />);
  const gaps = screen.getAllByTestId("series-gap");
  expect(gaps).toHaveLength(1);
  expect(gaps[0]).toHaveAttribute("data-index", "2");
  expect(screen.getByTestId("series-gap-note")).toHaveTextContent(
    "1 interval with no runs",
  );
});

it("says how many intervals were empty in the accessible name too", () => {
  render(<MetricSeries buckets={LIVE_HOURLY} metric="refusal_rate" />);
  expect(screen.getByRole("img")).toHaveAccessibleName(
    /7 intervals, 1 with no runs/i,
  );
});

it("treats a suppressed percentile as a gap rather than as a fast hour", () => {
  // p95 is blank for the 2-run and 3-run hours: below n = 20 it is the maximum. Those
  // two must break the line, not sit on the axis at zero.
  render(<MetricSeries buckets={LIVE_HOURLY} metric="p95_ms" />);
  expect(screen.getAllByTestId("series-gap")).toHaveLength(3);
  expect(screen.getByTestId("series-gap-note")).toHaveTextContent(
    "3 intervals with no runs",
  );
});

it("scales the axis to the movement rather than to 100%", () => {
  render(<MetricSeries buckets={LIVE_HOURLY} metric="refusal_rate" />);
  expect(screen.getByText("peak 40.0%")).toBeInTheDocument();
});

it("labels the ends of the window in UTC", () => {
  render(<MetricSeries buckets={LIVE_HOURLY} metric="refusal_rate" />);
  expect(screen.getByText("17:00")).toBeInTheDocument();
  expect(screen.getByText("23:00")).toBeInTheDocument();
});

it("says nothing was measured rather than drawing an axis from zero to zero", () => {
  const blank = LIVE_HOURLY.map((b) => ({ ...b, refusal_rate: null }));
  render(<MetricSeries buckets={blank} metric="refusal_rate" />);
  expect(screen.getByTestId("series-empty")).toHaveTextContent(
    /nothing measured/i,
  );
  expect(screen.queryAllByTestId("series-segment")).toHaveLength(0);
});

it("renders nothing to mislead when there are no buckets at all", () => {
  render(<MetricSeries buckets={[]} metric="refusal_rate" />);
  expect(screen.getByTestId("series-empty")).toBeInTheDocument();
});

it("draws a lone measured hour as a point rather than dropping it", () => {
  const isolated = LIVE_HOURLY.map((b, i) =>
    i === 3 ? b : { ...b, refusal_rate: null },
  );
  render(<MetricSeries buckets={isolated} metric="refusal_rate" />);
  expect(screen.getByTestId("series-point")).toBeInTheDocument();
});

it("does not recompute a rate from the counts standing beside it", () => {
  // Every bucket keeps its counts and reports a null rate. A component that divided
  // refused by runs would draw a full series here.
  const nulled = LIVE_HOURLY.map((b) => ({ ...b, tool_error_rate: null }));
  render(<MetricSeries buckets={nulled} metric="tool_error_rate" />);
  expect(screen.getByTestId("series-empty")).toBeInTheDocument();
});

it("names the metric in words", () => {
  render(<MetricSeries buckets={LIVE_HOURLY} metric="tool_error_rate" />);
  expect(screen.getByText(/tool errors/i)).toBeInTheDocument();
});
