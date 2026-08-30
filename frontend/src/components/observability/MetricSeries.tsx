import {
  METRIC_LABEL,
  axisMax,
  bucketLabel,
  formatLatency,
  formatRate,
  metricValue,
  segments,
  type Bucket,
} from "@/lib/observability";

/**
 * One metric over time, drawn so that an interval with no runs cannot be drawn through.
 *
 * The chart exists because a lifetime average cannot answer "is it getting worse". Over
 * the 213 recorded runs the refusal rate is 30.0%; by hour it is 18.4, 18.8, —, 36.8,
 * 40.0. The single figure is the mean of a rising line and was true at no point in the
 * session.
 *
 * The hour with no runs at all is the reason this uses `segments()` rather than one path.
 * A continuous polyline joins 18:00 to 20:00 across an hour that never happened, and that
 * straight line is indistinguishable from an hour of steady performance — the chart would
 * be inventing its most reassuring data point. Split into segments there is nothing to
 * draw across the gap, and the gap gets a marked column instead.
 */
export function MetricSeries({
  buckets,
  metric,
  bucket = "hour",
  height = 96,
}: {
  buckets: Bucket[];
  metric: string;
  bucket?: "hour" | "day";
  height?: number;
}) {
  const label = METRIC_LABEL[metric] ?? metric;
  const isLatency = metric.endsWith("_ms");
  const format = isLatency ? formatLatency : formatRate;
  const values = buckets.map((b) => metricValue(b, metric));
  const top = axisMax(values);

  if (buckets.length === 0 || top === null) {
    return (
      <figure data-testid="metric-series" data-metric={metric}>
        <figcaption className="text-xs uppercase tracking-wide text-[--muted-foreground]">
          {label}
        </figcaption>
        <p className="mt-2 text-sm text-[--muted-foreground]" data-testid="series-empty">
          Nothing measured in this window.
        </p>
      </figure>
    );
  }

  const width = 100;
  const step = buckets.length > 1 ? width / (buckets.length - 1) : 0;
  const x = (index: number) => (buckets.length > 1 ? index * step : width / 2);
  const y = (value: number) => height - (value / top) * height;

  const paths = segments(values);
  const gaps = values
    .map((value, index) => (value === null ? index : -1))
    .filter((index) => index >= 0);

  return (
    <figure data-testid="metric-series" data-metric={metric}>
      <figcaption className="flex items-baseline justify-between">
        <span className="text-xs uppercase tracking-wide text-[--muted-foreground]">
          {label}
        </span>
        <span className="text-xs tabular-nums text-[--muted-foreground]">
          peak {format(top)}
        </span>
      </figcaption>

      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className="mt-2 h-24 w-full"
        role="img"
        aria-label={`${label}, ${buckets.length} intervals, ${gaps.length} with no runs`}
      >
        {/* Gaps first, so a measured point is never hidden behind one. */}
        {gaps.map((index) => (
          <rect
            key={`gap-${index}`}
            x={Math.max(0, x(index) - step / 2)}
            y={0}
            width={step || width}
            height={height}
            className="fill-[--muted] opacity-40"
            data-testid="series-gap"
            data-index={index}
          />
        ))}

        {paths.map((segment, i) => (
          <g key={`segment-${i}`} data-testid="series-segment">
            {segment.length > 1 && (
              <polyline
                fill="none"
                strokeWidth={2}
                vectorEffect="non-scaling-stroke"
                className="stroke-[--primary]"
                points={segment
                  .map((point) => `${x(point.index)},${y(point.value)}`)
                  .join(" ")}
              />
            )}
            {/* A lone measured interval between two gaps is a dot. Dropping it would
                hide the only measurement in that window. */}
            {segment.length === 1 && (
              <circle
                cx={x(segment[0].index)}
                cy={y(segment[0].value)}
                r={2.5}
                className="fill-[--primary]"
                data-testid="series-point"
              />
            )}
          </g>
        ))}
      </svg>

      {/* The axis is text, not ticks: at six buckets a reader wants the hours, and at
          sixty they want the ends. Both are readable; a rotated tick label is neither. */}
      <figcaption className="mt-1 flex justify-between text-xs tabular-nums text-[--muted-foreground]">
        <span>{bucketLabel(buckets[0].start, bucket)}</span>
        {gaps.length > 0 && (
          <span data-testid="series-gap-note">
            {gaps.length} {gaps.length === 1 ? "interval" : "intervals"} with no runs
          </span>
        )}
        <span>{bucketLabel(buckets[buckets.length - 1].start, bucket)}</span>
      </figcaption>
    </figure>
  );
}
