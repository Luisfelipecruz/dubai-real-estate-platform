"use client";

import { AlertTriangle, CheckCircle2, Repeat, XCircle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import {
  CATEGORY_STYLE,
  formatMs,
  type RunDetail,
  type ToolStep,
} from "@/lib/copilot";

/**
 * One recorded run, broken down into the calls that produced it.
 *
 * WHAT THIS ANSWERS THAT THE ROW ABOVE IT CANNOT
 * ----------------------------------------------
 * The list reports `6 tool calls (2 failed)`. Those are two integers on `agent_runs`, and
 * across 213 runs the database could state a 10.3% tool error rate while being unable to
 * say whether it was one broken tool or nine flaky ones. The names live in
 * `agent_tool_calls`; this is what reads them back.
 *
 * A FAILED CALL IS DRAWN WITH THE SAME WEIGHT AS A SUCCESSFUL ONE, and it carries the
 * message the MODEL was shown rather than a generic one — `resolve_area_name` declining
 * "Atlantis Tower" and listing the names that do exist is the reason the run refused, and
 * a panel that hid it would describe a cleaner run than the one that happened.
 *
 * AN EMPTY LIST IS NEVER RENDERED AS "no tools were called". A run from before migration
 * 0005 and a run that genuinely called nothing both arrive as `tool_steps: []` and are
 * opposite facts. `tool_steps_note` is the API's sentence for whichever state this is, and
 * it is printed verbatim rather than re-derived here.
 */
export function RunDetailPanel({ detail }: { detail: RunDetail }) {
  const { run } = detail;

  return (
    <div className="space-y-3" data-testid="run-detail">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-[--muted-foreground]">
        <span data-testid="run-detail-counts">
          {detail.tool_step_count} tool call
          {detail.tool_step_count === 1 ? "" : "s"} recorded ·{" "}
          {detail.model_turn_count} model turn
          {detail.model_turn_count === 1 ? "" : "s"}
        </span>
        <span>
          {formatMs(run.tool_ms)} in tools of {formatMs(run.latency_ms)} total
        </span>
        {run.unverified_numbers > 0 && (
          <span className="text-amber-700">
            {run.unverified_numbers} unverified figure
            {run.unverified_numbers === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {/* The two counts are different measurements and the page says so once, here, rather
          than leaving a reader to assume a six-call run took six turns. */}
      {detail.tool_steps_note && (
        <p
          className="flex gap-2 rounded-md border border-[--border] bg-[--muted] p-3 text-[11px] leading-relaxed text-[--muted-foreground]"
          data-testid="tool-steps-note"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {detail.tool_steps_note}
        </p>
      )}

      {detail.tool_steps.map((step) => (
        <StepRow key={step.id} step={step} />
      ))}
    </div>
  );
}

function StepRow({ step }: { step: ToolStep }) {
  return (
    <Card
      className={cn("p-3", !step.ok && "border-red-200 bg-red-50/40")}
      data-testid="tool-step"
      data-tool={step.tool_name}
      data-ok={String(step.ok)}
    >
      <div className="flex flex-wrap items-center gap-2">
        {step.ok ? (
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
        ) : (
          <XCircle className="h-3.5 w-3.5 shrink-0 text-red-600" />
        )}
        <span className="font-mono text-[11px] text-[--muted-foreground]">
          {step.step}
        </span>
        <span className="font-mono text-xs font-semibold text-[--foreground]">
          {step.tool_name}
        </span>
        <span
          className={cn(
            "rounded border px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
            CATEGORY_STYLE[step.category] ?? CATEGORY_STYLE.meta,
          )}
        >
          {step.category}
        </span>
        {step.repeated && (
          /* A repeat is a ROUTING problem, not a tool problem. It is marked separately so
             it never gets summed into the tool error rate. */
          <span
            className="inline-flex items-center gap-1 text-[10px] text-amber-700"
            data-testid="repeated-call"
          >
            <Repeat className="h-3 w-3" />
            repeat
          </span>
        )}
        <span className="ml-auto font-mono text-[11px] text-[--muted-foreground]">
          {formatMs(step.duration_ms)}
        </span>
      </div>

      <pre className="mt-2 overflow-x-auto rounded bg-[--muted] p-2 font-mono text-[10px] leading-relaxed text-[--muted-foreground]">
        {JSON.stringify(step.arguments)}
      </pre>

      {step.error && (
        /* The message the model read, not a summary of it. "resolve_area_name failed on
           which name?" is the first question after "which tool failed". */
        <p
          className="mt-2 whitespace-pre-wrap text-[11px] leading-relaxed text-red-800"
          data-testid="tool-step-error"
        >
          {step.error}
        </p>
      )}
    </Card>
  );
}
