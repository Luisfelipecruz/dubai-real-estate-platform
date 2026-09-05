"use client";

import { AlertCircle, Check, Loader2, Minus, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatMs } from "@/lib/copilot";
import type { LineTone, ProgressState } from "@/lib/progress";

/**
 * What the system is doing, in its own words.
 *
 * This is the answer to the request behind m19 — "the user doesn't see the use of the
 * tools" — and it is a pure renderer of `ProgressState`. It holds no clock and no
 * interval, which is the point: it can only display sentences the reducer produced from
 * events that actually arrived. There is nothing here that could animate on its own.
 *
 * ── What it deliberately does not render ──────────────────────────────────
 *
 * Tool names, arguments, payloads, step numbers, categories and costs. All of them are
 * still on the state — `ProgressLine.tool` carries the real name — and all of them are
 * one click away in `EvidenceTrace`. §12.1: collapsed is not deleted. Deleting the
 * evidence to make the page look cleaner is the move this repository has refused four
 * times, and a status line is not a licence to make the fifth.
 *
 * ── Why a failure looks like a failure ────────────────────────────────────
 *
 * M-62 measured a 10.3% tool error rate. If one call in ten fails and every line renders
 * as a tick, the surface is claiming a reliability the system does not have — and doing
 * it more convincingly than the raw trace ever could, because a friendly sentence is
 * easier to believe than a JSON blob. A failed line gets a cross and the sentence that
 * says so.
 */
export function StatusLine({
  state,
  className,
}: {
  state: ProgressState;
  className?: string;
}) {
  // Nothing has happened yet, so there is nothing to say. Not "starting…", which would
  // be a sentence about an event that has not arrived.
  if (state.status === "idle") return null;

  const past = state.lines.filter((l) => l.key !== state.current?.key);

  return (
    <div
      data-testid="status-line"
      className={cn("space-y-1.5", className)}
      // The status changes while the user is looking elsewhere; a screen reader should
      // be told, and `polite` rather than `assertive` because none of this is urgent.
      aria-live="polite"
      aria-busy={state.status === "working"}
    >
      {past.map((line) => (
        <Row key={line.key} tone={line.tone} text={line.text} tookMs={line.tookMs} />
      ))}

      {state.current && (
        <Row
          key={state.current.key}
          tone="working"
          text={state.current.text}
          tookMs={null}
          current
        />
      )}

      {state.status === "incomplete" && state.error && (
        <p
          data-testid="status-error"
          className="flex items-start gap-2 pt-1 text-xs leading-relaxed text-red-700"
        >
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{state.error}</span>
        </p>
      )}
    </div>
  );
}

function Row({
  tone,
  text,
  tookMs,
  current = false,
}: {
  tone: LineTone;
  text: string;
  tookMs: number | null;
  current?: boolean;
}) {
  return (
    <div
      data-testid="status-row"
      data-tone={tone}
      className={cn(
        "flex items-center gap-2.5 text-sm",
        current ? "text-[--foreground]" : "text-[--muted-foreground]",
      )}
    >
      <Icon tone={tone} current={current} />
      <span className={cn(current && "font-medium")}>{text}</span>
      {/* Measured, from the event. There is no estimate here and no projected total —
          §12.5 is explicit that inventing a latency figure is the one lever m19 must
          not add. */}
      {tookMs !== null && (
        <span className="font-mono text-[11px] tabular-nums text-[--muted-foreground]">
          {formatMs(tookMs)}
        </span>
      )}
    </div>
  );
}

function Icon({ tone, current }: { tone: LineTone; current: boolean }) {
  if (current || tone === "working")
    return <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-[--primary]" />;
  if (tone === "failed")
    return <X data-testid="icon-failed" className="h-3.5 w-3.5 shrink-0 text-red-600" />;
  if (tone === "note")
    return <Minus className="h-3.5 w-3.5 shrink-0 text-[--muted-foreground]" />;
  return (
    <Check data-testid="icon-done" className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
  );
}
