"use client";

import { useMemo, useState } from "react";

/**
 * Two small multiples over the same x-axis, deliberately NOT one dual-axis chart:
 * price and volume have different units, and two y-scales let you imply any
 * correlation you like by choosing the scales.
 *
 * Only sales are plotted. The rent extract is a 2026 year-to-date registration
 * snapshot, not a history -- plotting rent counts by contract start year draws a
 * fake 20x hockey stick, because the early years hold only the handful of
 * long-running contracts still active at export time. The API says so explicitly
 * via `rents_are_historical`.
 */

export interface HistoryPoint {
  period: string;
  sale_count: number;
  median_price_sqm: number | null;
  median_price: number | null;
  rent_count: number;
  median_annual_rent: number | null;
  is_partial: boolean;
}

const SERIES = "#2a78d6";
const GRID = "#e1e0d9";
const BASELINE = "#c3c2b7";
const MUTED = "#898781";
const INK = "#1a1c17";
const SURFACE = "#ffffff";

const W = 760;
const H = 210;
const PAD = { top: 16, right: 20, bottom: 26, left: 56 };

/**
 * Ticks from 0 up to the first "nice" value at or ABOVE max.
 *
 * The >= max part is load-bearing, not cosmetic. The caller uses the last tick as
 * the y-scale maximum, so a top tick below the data silently maps the biggest
 * values to a negative y — outside the viewBox, invisible, with no error. That is
 * how the Burj Khalifa chart lost 2022-2026: max was 26,602, the ticks stopped at
 * 20,000, and the entire recent peak was clipped off the top while the line still
 * looked plausible. Same defect clipped the tallest bar (1,324 sales against a
 * 1,000 top).
 */
function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0];
  const raw = max / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
  const top = Math.ceil(max / step) * step; // never below max
  const out: number[] = [];
  for (let v = 0; v <= top + step * 0.001; v += step) out.push(v);
  return out;
}

// Ticks are not always round thousands -- a 1,324 max yields a 1,500 top -- so
// round to a decimal only when the value needs one. toFixed(0) alone printed
// "2k" on a gridline that actually sat at 1,500.
const fmt = (n: number) => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(n % 1000 === 0 ? 0 : 1)}k`;
  return `${n}`;
};

interface PlotProps {
  points: HistoryPoint[];
  value: (p: HistoryPoint) => number | null;
  kind: "line" | "bar";
  title: string;
  unit: string;
  hover: number | null;
  setHover: (i: number | null) => void;
}

function Plot({ points, value, kind, title, unit, hover, setHover }: PlotProps) {
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const vals = points.map(value);
  const max = Math.max(...vals.map((v) => v ?? 0), 1);
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1];

  const x = (i: number) => PAD.left + (plotW * (i + 0.5)) / points.length;
  const y = (v: number) => PAD.top + plotH - (plotH * v) / top;

  // solid through the complete periods; the partial tail is dashed so it is never
  // read as a real decline
  const lastComplete = points.reduce((acc, p, i) => (p.is_partial ? acc : i), 0);
  const seg = (from: number, to: number) =>
    points
      .slice(from, to + 1)
      .map((p, k) => {
        const v = value(p);
        return v == null ? null : `${x(from + k)},${y(v)}`;
      })
      .filter(Boolean)
      .join(" ");

  const bandW = plotW / points.length;
  const barW = Math.min(24, bandW - 2); // 2px surface gap between neighbours

  return (
    <figure className="m-0">
      <figcaption className="mb-1 flex items-baseline justify-between">
        <span className="text-sm font-semibold" style={{ color: INK }}>
          {title}
        </span>
        <span className="text-xs" style={{ color: MUTED }}>
          {unit}
        </span>
      </figcaption>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: "100%", height: "auto", display: "block" }}
        role="img"
        aria-label={`${title} by year`}
        onMouseLeave={() => setHover(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(t)}
              y2={y(t)}
              stroke={t === 0 ? BASELINE : GRID}
              strokeWidth={1}
            />
            <text
              x={PAD.left - 8}
              y={y(t) + 3.5}
              textAnchor="end"
              fontSize={10}
              fill={MUTED}
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {fmt(t)}
            </text>
          </g>
        ))}

        {kind === "bar"
          ? points.map((p, i) => {
              const v = value(p) ?? 0;
              const h = Math.max(0, y(0) - y(v));
              const r = Math.min(4, h);
              return (
                <path
                  key={p.period}
                  d={`M${x(i) - barW / 2},${y(0)} L${x(i) - barW / 2},${y(v) + r}
                      Q${x(i) - barW / 2},${y(v)} ${x(i) - barW / 2 + r},${y(v)}
                      L${x(i) + barW / 2 - r},${y(v)}
                      Q${x(i) + barW / 2},${y(v)} ${x(i) + barW / 2},${y(v) + r}
                      L${x(i) + barW / 2},${y(0)} Z`}
                  fill={SERIES}
                  opacity={p.is_partial ? 0.4 : hover === null || hover === i ? 1 : 0.72}
                />
              );
            })
          : (
            <>
              <polyline
                points={seg(0, lastComplete)}
                fill="none"
                stroke={SERIES}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {lastComplete < points.length - 1 && (
                <polyline
                  points={seg(lastComplete, points.length - 1)}
                  fill="none"
                  stroke={SERIES}
                  strokeWidth={2}
                  strokeDasharray="4 4"
                  strokeLinecap="round"
                  opacity={0.65}
                />
              )}
              {points.map((p, i) => {
                const v = value(p);
                if (v == null) return null;
                const isEnd = i === points.length - 1;
                if (!isEnd && hover !== i) return null;
                return (
                  <circle
                    key={p.period}
                    cx={x(i)}
                    cy={y(v)}
                    r={4}
                    fill={SERIES}
                    stroke={SURFACE}
                    strokeWidth={2}
                  />
                );
              })}
            </>
          )}

        {/* x labels: every other year, so 19 of them do not collide */}
        {points.map((p, i) =>
          i % 2 === 0 || i === points.length - 1 ? (
            <text
              key={p.period}
              x={x(i)}
              y={H - 8}
              textAnchor="middle"
              fontSize={10}
              fill={MUTED}
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {p.period.slice(2)}
            </text>
          ) : null
        )}

        {hover !== null && (
          <line
            x1={x(hover)}
            x2={x(hover)}
            y1={PAD.top}
            y2={PAD.top + plotH}
            stroke={MUTED}
            strokeWidth={1}
            opacity={0.5}
          />
        )}

        {/* hit targets, wider than the marks */}
        {points.map((p, i) => (
          <rect
            key={p.period}
            x={PAD.left + bandW * i}
            y={PAD.top}
            width={bandW}
            height={plotH}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>
    </figure>
  );
}

export function AreaHistoryChart({
  points,
  rentsAreHistorical,
  rentFrom,
  rentTo,
}: {
  points: HistoryPoint[];
  rentsAreHistorical: boolean;
  rentFrom: string | null;
  rentTo: string | null;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const priced = useMemo(() => points.filter((p) => p.median_price_sqm != null), [points]);
  const active = hover != null ? points[hover] : null;

  if (priced.length < 2) {
    return (
      <p className="text-sm" style={{ color: MUTED }}>
        Not enough transaction history in this area to plot a trend.
      </p>
    );
  }

  const first = priced[0];
  const lastFull = [...points].reverse().find((p) => !p.is_partial && p.median_price_sqm != null);
  const growth =
    first.median_price_sqm && lastFull?.median_price_sqm
      ? lastFull.median_price_sqm / first.median_price_sqm
      : null;

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-gray-900">Sales history</h2>
        {growth && lastFull && (
          <p className="text-xs text-gray-500">
            Median price per m² {growth >= 1 ? "rose" : "fell"}{" "}
            <span className="font-semibold text-gray-900">{growth.toFixed(1)}×</span> from{" "}
            {first.period} to {lastFull.period}
          </p>
        )}
      </div>

      <div
        className="relative space-y-5"
        role="group"
        onMouseLeave={() => setHover(null)}
      >
        <Plot
          points={points}
          value={(p) => p.median_price_sqm}
          kind="line"
          title="Median price per m²"
          unit="AED / m²"
          hover={hover}
          setHover={setHover}
        />
        <Plot
          points={points}
          value={(p) => p.sale_count}
          kind="bar"
          title="Transactions"
          unit="count"
          hover={hover}
          setHover={setHover}
        />

        {active && (
          // Flip to the side the cursor is NOT on. Pinned to one corner it sat on
          // top of the line's most recent years -- the part people actually read.
          <div
            className={`pointer-events-none absolute top-7 rounded-lg border border-gray-200 bg-white/95 px-3 py-2 text-xs shadow-sm backdrop-blur ${
              hover! > points.length / 2 ? "left-14" : "right-0"
            }`}
          >
            <p className="font-semibold text-gray-900">
              {active.period}
              {active.is_partial && (
                <span className="ml-1 font-normal text-gray-500">· partial year</span>
              )}
            </p>
            <p className="mt-1 text-gray-600" style={{ fontVariantNumeric: "tabular-nums" }}>
              {active.median_price_sqm
                ? `AED ${Math.round(active.median_price_sqm).toLocaleString()} / m²`
                : "no price data"}
            </p>
            <p className="text-gray-600" style={{ fontVariantNumeric: "tabular-nums" }}>
              {active.sale_count.toLocaleString()} transactions
            </p>
          </div>
        )}
      </div>

      <div className="mt-4 space-y-1 border-t border-gray-100 pt-3 text-xs text-gray-500">
        <p>
          Median, not mean — one area carries a single AED 6.75 bn transaction, and a yearly
          mean would chart the outliers. The dashed segment and pale bar are an incomplete
          year, not a decline.
        </p>
        {!rentsAreHistorical && rentFrom && (
          <p>
            <span className="font-medium text-gray-600">Rents are not plotted.</span> Every
            contract in this export was registered between {rentFrom} and {rentTo} — it is a
            snapshot of active contracts, not a history, so a trend through it would be
            an artefact of what the export contains.
          </p>
        )}
      </div>
    </div>
  );
}
