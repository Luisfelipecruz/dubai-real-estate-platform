/**
 * The rendering rules, tested where they are decided.
 *
 * Every test here is about a way this page could tell a lie: an unmeasured floor drawn as
 * zero, a stale score drawn as current, an unknown registry drawn as unchanged, a failing
 * floor sorted below six passing ones. None of them is about whether a `<div>` appears.
 */

import {
  describeCoverage,
  describeRegistry,
  formatAge,
  formatMargin,
  formatRate,
  sortFloors,
  type FloorCheck,
  type RegistryDrift,
  type RouteCoverage,
} from "@/lib/evals";

describe("formatRate", () => {
  it("renders a rate as a percentage", () => {
    expect(formatRate(0.805)).toBe("80.5%");
  });

  it("renders null as an em dash and NOT as zero", () => {
    // The whole reason this function exists. `not_measured` and `measured at 0.0` are
    // different facts and 0.0% is a plausible-looking answer to a question nobody asked.
    expect(formatRate(null)).toBe("—");
    expect(formatRate(undefined)).toBe("—");
    expect(formatRate(0)).toBe("0.0%");
  });
});

describe("formatMargin", () => {
  it("keeps the sign, because the sign is the verdict", () => {
    expect(formatMargin(0.1)).toBe("+10.0 pts");
    expect(formatMargin(-0.08)).toBe("-8.0 pts");
  });

  it("renders a missing margin as an em dash", () => {
    expect(formatMargin(undefined)).toBe("—");
  });
});

describe("formatAge", () => {
  it.each([
    [30, "just now"],
    [60 * 5, "5 min ago"],
    [60 * 60, "1 hour ago"],
    [60 * 60 * 5, "5 hours ago"],
    [60 * 60 * 24, "1 day ago"],
    [60 * 60 * 24 * 6, "6 days ago"],
  ])("renders %i seconds as %s", (seconds, expected) => {
    expect(formatAge(seconds)).toBe(expected);
  });

  it("does not pretend a clock skew is an age", () => {
    expect(formatAge(-500)).toBe("in the future");
  });
});

describe("describeRegistry", () => {
  const base: RegistryDrift = {
    known: true,
    stale: false,
    measured_against: ["a"],
    registered_now: ["a"],
    added_since: [],
    removed_since: [],
  };

  it("says nothing when the registry has not moved", () => {
    expect(describeRegistry(base)).toBeNull();
  });

  it("names the tools registered since the run", () => {
    // The score describes a nine-tool system; a tenth is registered now.
    const got = describeRegistry({
      ...base,
      stale: true,
      added_since: ["dataset_aggregate"],
    });
    expect(got?.level).toBe("stale");
    expect(got?.text).toContain("dataset_aggregate");
    expect(got?.text).toContain("make eval");
  });

  it("reports removals separately from additions", () => {
    const got = describeRegistry({
      ...base,
      stale: true,
      added_since: ["new_tool"],
      removed_since: ["old_tool"],
    });
    expect(got?.text).toContain("new_tool");
    expect(got?.text).toContain("1 removed (old_tool)");
  });

  it("distinguishes 'cannot tell' from 'nothing changed'", () => {
    // Both would render as an absent warning if `known` were ignored, which would show a
    // score with no provenance as though its provenance had been checked and was fine.
    const got = describeRegistry({ ...base, known: false, stale: null });
    expect(got?.level).toBe("unknown");
    expect(got?.text).toContain("cannot be established");
  });

  it("returns null for a missing registry rather than throwing", () => {
    expect(describeRegistry(undefined)).toBeNull();
  });
});

describe("describeCoverage", () => {
  const complete: RouteCoverage = {
    known: true,
    complete: true,
    graded: 11,
    linked: 11,
    errors: 0,
    error_ids: [],
    rate: 1,
  };

  it("says nothing when every linked question was graded", () => {
    // A caveat printed under every score is a caveat nobody reads by the third visit.
    expect(describeCoverage(complete)).toBeNull();
  });

  it("names the questions that never answered", () => {
    const got = describeCoverage({
      ...complete,
      complete: false,
      graded: 10,
      errors: 1,
      error_ids: ["A-26"],
      rate: 0.909091,
    });
    expect(got?.level).toBe("partial");
    expect(got?.text).toContain("10 of 11");
    expect(got?.text).toContain("A-26");
  });

  it("says which way the missing question moved the rate", () => {
    // The direction is the point. A reader distrusts a number that fell; nobody
    // distrusts one that rose, and this one rose for an infrastructure reason.
    const got = describeCoverage({
      ...complete,
      complete: false,
      graded: 10,
      errors: 1,
      error_ids: ["A-26"],
      rate: 0.909091,
    });
    expect(got?.text).toContain("raises it");
  });

  it("agrees with itself about plurals", () => {
    const got = describeCoverage({
      ...complete,
      complete: false,
      graded: 8,
      errors: 3,
      error_ids: ["A-26", "A-31", "A-40"],
      rate: 0.727273,
    });
    expect(got?.text).toContain("they are");
  });

  it("distinguishes 'cannot tell' from 'nothing was missed'", () => {
    // Every result recorded before the harness kept both denominators lands here, and
    // reading that silence as a complete run is the error this level exists for.
    const got = describeCoverage({ ...complete, known: false, complete: null });
    expect(got?.level).toBe("unknown");
  });

  it("returns null for a missing coverage block rather than throwing", () => {
    expect(describeCoverage(undefined)).toBeNull();
  });
});

describe("sortFloors", () => {
  const floors: FloorCheck[] = [
    { key: "agent.route_accuracy", floor: 0.77, actual: 0.9, margin: 0.13, state: "ok" },
    { key: "retrieval.dense_mrr", floor: 0.75, actual: null, state: "not_measured" },
    { key: "agent.answer_accuracy", floor: 0.7, actual: 0.62, margin: -0.08, state: "fail" },
    { key: "agent.no_decoyed_answers", floor: 1, actual: 1, margin: 0, state: "ok" },
  ];

  it("puts failures first and unmeasured floors above passes", () => {
    expect(sortFloors(floors).map((f) => f.state)).toEqual([
      "fail",
      "not_measured",
      "ok",
      "ok",
    ]);
  });

  it("breaks ties by key so the order is stable between renders", () => {
    expect(sortFloors(floors).slice(2).map((f) => f.key)).toEqual([
      "agent.no_decoyed_answers",
      "agent.route_accuracy",
    ]);
  });

  it("does not mutate its input", () => {
    const before = floors.map((f) => f.key);
    sortFloors(floors);
    expect(floors.map((f) => f.key)).toEqual(before);
  });
});
