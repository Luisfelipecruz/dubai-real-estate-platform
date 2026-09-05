import { ArrowDownRight, ArrowUpRight, Equal, HelpCircle, Waves } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  METRIC_LABEL,
  formatDelta,
  formatLatency,
  formatRate,
  formatSample,
  trendTone,
  type Trend,
} from "@/lib/observability";

/**
 * One metric, this bucket against the last, with the sample it was measured over.
 *
 * The component that would be easy to get wrong and expensive to have wrong. The live
 * table's two most recent hours hold three runs and two; compared naively they report the
 * refusal rate up 33 points, the empty-answer rate up 100, the step cap rate up 33 — four
 * alarms from five runs, on a panel whose entire purpose is being believed.
 *
 * So the badge cannot paint an alarm from a direction the API did not conclude. There is
 * no branch here that maps `indistinguishable` to a colour, and the run counts are printed
 * beside every rate rather than offered behind a tooltip: "+33.3 pts" and "3 vs 2 runs"
 * are the same fact, and only the pair of them is honest.
 */
export function TrendBadge({ trend }: { trend: Trend }) {
  const tone = trendTone(trend);
  const label = METRIC_LABEL[trend.metric] ?? trend.metric;
  const isLatency = trend.metric.endsWith("_ms");
  const format = isLatency ? formatLatency : formatRate;
  const sample = formatSample(trend);

  return (
    <div
      className="rounded-lg border border-[--border] p-4"
      data-testid="trend-badge"
      data-metric={trend.metric}
      data-direction={trend.direction}
      data-tone={tone}
    >
      <p className="text-xs uppercase tracking-wide text-[--muted-foreground]">{label}</p>

      <p className="mt-1 flex items-baseline gap-2">
        <span className="text-2xl font-semibold tabular-nums">
          {format(trend.current)}
        </span>
        <span className="text-xs text-[--muted-foreground]">
          was {format(trend.previous)}
        </span>
      </p>

      <p className={cn("mt-2 flex items-center gap-1.5 text-sm", TONE_CLASS[tone])}>
        <DirectionIcon direction={trend.direction} />
        <span className="tabular-nums" data-testid="trend-delta">
          {isLatency ? formatLatencyDelta(trend.delta) : formatDelta(trend.delta)}
        </span>
      </p>

      {/*
        The caveat is a sentence, not a colour. "Within what 3 runs can measure" says why
        the number is not an alarm; a grey arrow on its own just looks like a quiet metric.
      */}
      {trend.direction === "indistinguishable" && (
        <p className="mt-1 text-xs text-[--muted-foreground]" data-testid="trend-caveat">
          Smaller than this sample can measure
          {trend.resolution !== null && ` (steps of ${formatRate(trend.resolution)})`}
        </p>
      )}
      {trend.direction === "unknown" && (
        <p className="mt-1 text-xs text-[--muted-foreground]" data-testid="trend-caveat">
          Not measured in one of the two intervals
        </p>
      )}

      {sample && (
        <p className="mt-1 text-xs text-[--muted-foreground]" data-testid="trend-sample">
          {sample} runs
        </p>
      )}
    </div>
  );
}

const TONE_CLASS: Record<string, string> = {
  alarm: "text-red-600 dark:text-red-400",
  better: "text-emerald-600 dark:text-emerald-400",
  neutral: "text-[--muted-foreground]",
  unknown: "text-[--muted-foreground]",
};

function DirectionIcon({ direction }: { direction: Trend["direction"] }) {
  const size = "h-4 w-4 shrink-0";
  switch (direction) {
    case "up":
      return <ArrowUpRight className={size} data-testid="icon-up" />;
    case "down":
      return <ArrowDownRight className={size} data-testid="icon-down" />;
    case "flat":
      return <Equal className={size} data-testid="icon-flat" />;
    case "indistinguishable":
      return <Waves className={size} data-testid="icon-noise" />;
    default:
      return <HelpCircle className={size} data-testid="icon-unknown" />;
  }
}

/** A latency delta in milliseconds, signed. Not points — it is not a rate. */
function formatLatencyDelta(delta: number | null): string {
  if (delta === null || Number.isNaN(delta)) return "—";
  const sign = delta > 0 ? "+" : "-";
  return `${sign}${formatLatency(Math.abs(delta))}`;
}
