/**
 * The formatting and shaping rules, driven from the six real hours in the fixture.
 *
 * Everything asserted here is a way the panel could state something the data does not
 * support. None of it is about appearance.
 */
import {
  LIVE_HEALTH,
  LIVE_HOURLY,
  WIDE_TREND,
} from "@/lib/observability.fixture";
import {
  axisMax,
  bucketLabel,
  formatDelta,
  formatLatency,
  formatRate,
  formatSample,
  metricValue,
  segments,
  trendTone,
  type Trend,
} from "@/lib/observability";

describe("null is a value, and it is not zero", () => {
  it("renders an unmeasured rate as an em dash rather than 0.0%", () => {
    expect(formatRate(null)).toBe("—");
    expect(formatRate(undefined)).toBe("—");
    expect(formatRate(NaN)).toBe("—");
  });

  it("still renders a genuine zero as a zero", () => {
    // The 22:00 hour really did refuse nothing. That is a measurement, and it is not
    // the same fact as the 19:00 hour, which measured nothing at all.
    expect(formatRate(0)).toBe("0.0%");
    expect(formatRate(LIVE_HOURLY[5].refusal_rate)).toBe("0.0%");
    expect(formatRate(LIVE_HOURLY[2].refusal_rate)).toBe("—");
  });

  it("renders a suppressed percentile as an em dash and not as instant", () => {
    expect(formatLatency(LIVE_HOURLY[6].p95_ms)).toBe("—");
    expect(formatLatency(LIVE_HOURLY[6].p50_ms)).toBe(formatLatency(13829));
  });
});

describe("a delta is in points, not percent of a percent", () => {
  it("signs the direction and names the unit", () => {
    expect(formatDelta(0.216)).toBe("+21.6 pts");
    expect(formatDelta(-0.216)).toBe("-21.6 pts");
    expect(formatDelta(0)).toBe("0.0 pts");
    expect(formatDelta(null)).toBe("—");
  });
});

describe("a movement smaller than its sample cannot be painted as an alarm", () => {
  it("gives an indistinguishable trend a neutral tone", () => {
    const refusal = LIVE_HEALTH.trends[0];
    expect(refusal.direction).toBe("indistinguishable");
    expect(trendTone(refusal)).toBe("neutral");
  });

  it("gives the same metric an alarm tone once the sample supports it", () => {
    expect(trendTone(WIDE_TREND)).toBe("alarm");
  });

  it("treats a fall in a lower-is-better metric as better, not as an alarm", () => {
    expect(trendTone({ ...WIDE_TREND, direction: "down" })).toBe("better");
  });

  it("never colours a metric it has no polarity for", () => {
    const unknown: Trend = { ...WIDE_TREND, metric: "citations_per_answer" };
    expect(trendTone(unknown)).toBe("neutral");
  });

  it("reports an unmeasurable comparison as unknown", () => {
    const p95 = LIVE_HEALTH.trends[4];
    expect(p95.direction).toBe("unknown");
    expect(trendTone(p95)).toBe("unknown");
  });

  it("spells out the denominators behind every rate comparison", () => {
    expect(formatSample(LIVE_HEALTH.trends[0])).toBe("3 vs 2");
    expect(formatSample(LIVE_HEALTH.trends[4])).toBeNull();
  });
});

describe("a gap in the series is not a point", () => {
  it("splits the live hours at 19:00 into two segments", () => {
    const values = LIVE_HOURLY.map((b) => b.refusal_rate);
    const parts = segments(values);
    expect(parts).toHaveLength(2);
    expect(parts[0].map((p) => p.index)).toEqual([0, 1]);
    expect(parts[1].map((p) => p.index)).toEqual([3, 4, 5, 6]);
  });

  it("keeps a lone measured interval between two gaps as its own segment", () => {
    const parts = segments([null, 0.4, null]);
    expect(parts).toHaveLength(1);
    expect(parts[0]).toEqual([{ index: 1, value: 0.4 }]);
  });

  it("returns nothing at all when nothing was measured", () => {
    expect(segments([null, null])).toEqual([]);
    expect(segments([])).toEqual([]);
  });

  it("returns one segment when the series is continuous", () => {
    expect(segments([0.1, 0.2, 0.3])).toHaveLength(1);
  });
});

describe("the axis is scaled to what happened", () => {
  it("does not stretch a rate axis to 100%", () => {
    const top = axisMax(LIVE_HOURLY.map((b) => b.refusal_rate));
    // The refusal rate never exceeded 40%. Fixing the axis at 1.0 would flatten the
    // 18.4% -> 40.0% climb -- the movement the chart exists to show -- into two stubs.
    expect(top).toBeCloseTo(0.4);
  });

  it("has no upper bound to report when nothing was measured", () => {
    expect(axisMax([null, null])).toBeNull();
    expect(axisMax([])).toBeNull();
  });

  it("avoids a zero-height axis when every measurement is zero", () => {
    expect(axisMax([0, 0])).toBe(1);
  });
});

describe("the browser reads rates and never derives them", () => {
  it("reports a null rate even when the counts beside it would divide cleanly", () => {
    // 32 refusals out of 87 runs is 36.8%, and this bucket says the rate is null.
    // Anything that recomputed would return 0.368 here and hide the API's judgement.
    const doctored = { ...LIVE_HOURLY[3], refusal_rate: null };
    expect(metricValue(doctored, "refusal_rate")).toBeNull();
    expect(doctored.refused).toBe(32);
    expect(doctored.runs).toBe(87);
  });

  it("returns null for a metric it does not know", () => {
    expect(metricValue(LIVE_HOURLY[0], "made_up_metric")).toBeNull();
  });
});

describe("bucket labels", () => {
  it("reads the hour in UTC, which is what the API bucketed in", () => {
    expect(bucketLabel(LIVE_HOURLY[0].start)).toBe("17:00");
    expect(bucketLabel(LIVE_HOURLY[6].start)).toBe("23:00");
  });

  it("reads a day bucket as a date", () => {
    expect(bucketLabel(LIVE_HOURLY[0].start, "day")).toBe("2026-08-29");
  });

  it("returns an unparseable value unchanged rather than Invalid Date", () => {
    expect(bucketLabel("not a timestamp")).toBe("not a timestamp");
  });
});
