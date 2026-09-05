/**
 * The rendering rules, tested where they are decided.
 *
 * Every test here is about a way this page could tell a lie: an unmeasured floor drawn as
 * zero, a stale score drawn as current, an unknown registry drawn as unchanged, a failing
 * floor sorted below six passing ones. None of them is about whether a `<div>` appears.
 */

import {
  describeRegistry,
  formatAge,
  formatMargin,
  formatRate,
  sortFloors,
  type FloorCheck,
  type RegistryDrift,
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
