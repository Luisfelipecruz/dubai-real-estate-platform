import { AlertTriangle, CheckCircle2, CircleSlash, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import {
  describeCoverage,
  describeRegistry,
  formatAge,
  formatMargin,
  formatRate,
  sortFloors,
  type EvalReport,
  type FloorState,
} from "@/lib/evals";

/**
 * The regression gate, with its measurement and its expiry date.
 *
 * WHAT THIS COMPONENT REFUSES TO DRAW
 * -----------------------------------
 * A score on its own. `eval/thresholds.yaml` is a set of floors, each carrying a written
 * argument for its number, and the harness produces the values — but a value beside a
 * floor is still not enough to act on without knowing whether it describes the system
 * running now.
 *
 * Three things are therefore drawn BEFORE the number, in this order:
 *
 *   1. Whether the tool registry has moved since the run. A score measured against nine
 *      tools is not a statement about a ten-tool system.
 *   2. Whether the gate was applied at all. An ungated run has no pass/fail, and drawing
 *      one from its absence would be inventing a verdict.
 *   3. Whether the route rate covers the whole linked set. A question that errored is
 *      absent from both sides of that rate, so an infrastructure timeout RAISES it — the
 *      one direction of movement a reader will not think to distrust.
 *   4. Which floors this run did not measure. `not_measured` is a third state — an
 *      agent-only run measures nothing under `retrieval.` — and collapsing it into either
 *      neighbour turns a partial suite into either a false pass or a false alarm.
 */

const STATE_ICON: Record<FloorState, typeof CheckCircle2> = {
  ok: CheckCircle2,
  fail: XCircle,
  not_measured: CircleSlash,
};

const STATE_CLASS: Record<FloorState, string> = {
  ok: "text-emerald-700",
  fail: "text-red-700",
  not_measured: "text-[--muted-foreground]",
};

const STATE_LABEL: Record<FloorState, string> = {
  ok: "meets floor",
  fail: "BELOW FLOOR",
  not_measured: "not measured",
};

/** Both warnings above the score render identically apart from severity, so they share a
 *  shell. `urgent` is amber; anything else is the muted "cannot tell" treatment, because
 *  drawing "unknown" and "definitely wrong" the same colour flattens the one that matters. */
function Notice({
  testId,
  level,
  urgent,
  children,
}: {
  testId: string;
  level: string;
  urgent: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      data-testid={testId}
      data-level={level}
      className={
        urgent
          ? "flex gap-2 rounded-md border border-amber-200 bg-amber-50 p-3"
          : "flex gap-2 rounded-md border border-[--border] bg-[--muted] p-3"
      }
    >
      <AlertTriangle
        className={
          urgent
            ? "mt-0.5 h-4 w-4 shrink-0 text-amber-700"
            : "mt-0.5 h-4 w-4 shrink-0 text-[--muted-foreground]"
        }
      />
      <p
        className={
          urgent
            ? "text-xs leading-relaxed text-amber-900"
            : "text-xs leading-relaxed text-[--muted-foreground]"
        }
      >
        {children}
      </p>
    </div>
  );
}

export function GatePanel({ report }: { report: EvalReport }) {
  const drift = describeRegistry(report.registry);
  const coverage = describeCoverage(report.coverage);

  if (!report.available) {
    return (
      <Card className="p-5" data-testid="gate-panel" data-available="false">
        <div className="flex gap-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
          <div className="space-y-2">
            <p className="text-sm font-semibold text-[--foreground]">
              No eval run has been recorded on this deployment.
            </p>
            <p className="text-xs leading-relaxed text-[--muted-foreground]">
              {report.reason}
            </p>
            <p className="text-xs leading-relaxed text-[--muted-foreground]">
              The floors below exist regardless — they are arguments written in{" "}
              <code>eval/thresholds.yaml</code> before any run, not readings taken from
              one. What is missing is the measurement, and an empty column is the honest
              way to show it.
            </p>
          </div>
        </div>
        <FloorTable report={report} />
      </Card>
    );
  }

  const agent = (report.counts?.agent ?? {}) as Record<string, number>;

  return (
    <Card className="p-5 space-y-4" data-testid="gate-panel" data-available="true">
      {drift && (
        <Notice testId="registry-drift" level={drift.level} urgent={drift.level === "stale"}>
          {drift.text}
        </Notice>
      )}

      {coverage && (
        <Notice
          testId="route-coverage"
          level={coverage.level}
          urgent={coverage.level === "partial"}
        >
          {coverage.text}
        </Notice>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {report.gate_applied ? (
          <Badge variant={report.gate_passed ? "success" : "destructive"}>
            {report.gate_passed ? "GATE PASSED" : "GATE FAILED"}
          </Badge>
        ) : (
          /* Not a verdict. A run without --gate compared nothing, and a grey badge that
             says so is the only thing that can go here. */
          <Badge variant="secondary">gate not applied</Badge>
        )}
        <span className="font-mono text-[11px] text-[--muted-foreground]">
          suite {report.suite} · {report.provider ?? "provider unrecorded"} ·{" "}
          {formatAge(report.age_seconds)}
          {report.duration_s ? ` · took ${Math.round(report.duration_s / 60)} min` : ""}
        </span>
      </div>

      {report.summary && (
        <p className="text-xs text-[--muted-foreground]" data-testid="gate-summary">
          {report.summary.ok} of {report.summary.checked} floors met
          {report.summary.failing > 0 && `, ${report.summary.failing} below floor`}
          {report.summary.not_measured > 0 &&
            `, ${report.summary.not_measured} not measured by this suite`}
          .
        </p>
      )}

      <FloorTable report={report} />

      {/* The denominators, beside the rates rather than under them. 0.750 is 30/40 or
          3/4, and the fixture size changes over time — a rate whose denominator is not on
          the page cannot be compared with one somebody wrote down last month. */}
      {Object.keys(agent).length > 0 && (
        <p
          className="font-mono text-[11px] text-[--muted-foreground]"
          data-testid="denominators"
        >
          answers {String(agent.passed)}/{String(agent.n)} · routes{" "}
          {String(agent.route_ok)}/{String(agent.route_n)}
          {/* The linked total appears only when it differs from the graded one. On a
              complete run the two are the same number and printing it twice adds noise;
              on a partial run its absence is the whole problem. */}
          {report.coverage?.known && !report.coverage.complete
            ? ` of ${report.coverage.linked} linked`
            : ""}{" "}
          · fabricated {String(agent.fabricated)} · decoyed {String(agent.decoyed)}
          {report.fixtures ? ` · fixtures ${JSON.stringify(report.fixtures)}` : ""}
        </p>
      )}

      {report.caveat && (
        <p className="whitespace-pre-line border-t border-[--border] pt-3 text-[11px] leading-relaxed text-[--muted-foreground]">
          {report.caveat}
        </p>
      )}
    </Card>
  );
}

function FloorTable({ report }: { report: EvalReport }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs" data-testid="floor-table">
        <thead>
          <tr className="border-b border-[--border] text-[--muted-foreground]">
            <th className="py-1.5 pr-3 font-medium">threshold</th>
            <th className="py-1.5 pr-3 font-medium">floor</th>
            <th className="py-1.5 pr-3 font-medium">measured</th>
            <th className="py-1.5 pr-3 font-medium">margin</th>
            <th className="py-1.5 pr-3 font-medium">state</th>
          </tr>
        </thead>
        <tbody>
          {sortFloors(report.floors).map((check) => {
            const Icon = STATE_ICON[check.state];
            return (
              <tr
                key={check.key}
                data-testid={`floor-${check.key}`}
                data-state={check.state}
                className="border-b border-[--border] last:border-0"
              >
                <td className="py-1.5 pr-3 font-mono">{check.key}</td>
                <td className="py-1.5 pr-3 font-mono text-[--muted-foreground]">
                  {formatRate(check.floor)}
                </td>
                <td className="py-1.5 pr-3 font-mono">{formatRate(check.actual)}</td>
                <td className="py-1.5 pr-3 font-mono text-[--muted-foreground]">
                  {formatMargin(check.margin)}
                </td>
                <td className={`py-1.5 pr-3 ${STATE_CLASS[check.state]}`}>
                  <span className="inline-flex items-center gap-1">
                    <Icon className="h-3 w-3" />
                    {STATE_LABEL[check.state]}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
