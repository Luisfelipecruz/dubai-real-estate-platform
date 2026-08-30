"use client";

import { useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, Repeat, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { CATEGORY_STYLE, formatCost, formatMs, type AgentStep } from "@/lib/copilot";

/**
 * The per-step tool trace: what was called, with what, what came back, how long, and
 * what it cost.
 *
 * This is the differentiator. Every RAG demo renders a paragraph; this renders the
 * evidence that produced it, which is the thing a reviewer actually wants and the thing
 * m15 built the executor to record. A failed tool call is shown with the same weight as
 * a successful one — the run captured while building this page called
 * `resolve_area_name` twice and the second attempt errored, and a trace that hid that
 * would be describing a cleaner run than the one that happened.
 */
export function EvidenceTrace({ steps }: { steps: AgentStep[] }) {
  if (steps.length === 0) {
    return (
      <Card className="p-5">
        <p className="text-sm text-[--muted-foreground]">
          No steps recorded — the model answered without calling a tool.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-2" data-testid="evidence-trace">
      {steps.map((step) => (
        <StepCard key={step.step} step={step} />
      ))}
    </div>
  );
}

function StepCard({ step }: { step: AgentStep }) {
  const [open, setOpen] = useState(false);
  const hasDetail = step.tool_calls.length > 0 || Boolean(step.text);

  return (
    <Card className="overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={!hasDetail}
        aria-expanded={open}
        className={cn(
          "flex w-full items-center gap-3 px-4 py-3 text-left transition-colors",
          hasDetail && "hover:bg-[--muted]",
        )}
      >
        {hasDetail ? (
          open ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-[--muted-foreground]" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-[--muted-foreground]" />
          )
        ) : (
          <span className="w-4" />
        )}

        <span className="font-mono text-xs text-[--muted-foreground]">
          step {step.step}
        </span>

        <span className="flex flex-1 flex-wrap items-center gap-1.5">
          {step.tool_calls.length === 0 ? (
            <span className="text-xs italic text-[--muted-foreground]">
              reasoning only
            </span>
          ) : (
            step.tool_calls.map((call, i) => (
              <span
                key={i}
                className={cn(
                  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[11px]",
                  CATEGORY_STYLE[call.category] ??
                    "bg-stone-100 text-stone-700 border-stone-200",
                )}
              >
                {call.ok ? (
                  <CheckCircle2 className="h-3 w-3" />
                ) : (
                  <XCircle className="h-3 w-3 text-[--destructive]" />
                )}
                {call.name}
                {call.repeated && <Repeat className="h-3 w-3" />}
              </span>
            ))
          )}
        </span>

        <span className="shrink-0 font-mono text-[11px] text-[--muted-foreground]">
          {formatMs(step.latency_ms)}
          {" · "}
          {/* cost_usd is null for an unpriced model. `formatCost` renders that as an em
              dash rather than as $0.00, because unknown is not zero. */}
          {formatCost(step.cost_usd)}
        </span>
      </button>

      {open && hasDetail && (
        <div className="space-y-3 border-t border-[--border] bg-[--muted]/40 px-4 py-3">
          {step.text && (
            <div>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[--muted-foreground]">
                Model text
              </p>
              <p className="whitespace-pre-wrap text-xs leading-relaxed text-[--foreground]">
                {step.text}
              </p>
            </div>
          )}

          {step.tool_calls.map((call, i) => (
            <div key={i} className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs font-semibold text-[--foreground]">
                  {call.name}
                </span>
                <span className="font-mono text-[11px] text-[--muted-foreground]">
                  {call.category} · {formatMs(call.duration_ms)}
                </span>
                {!call.ok && (
                  <span className="rounded bg-red-100 px-1.5 py-0.5 text-[11px] font-medium text-red-800">
                    tool error
                  </span>
                )}
                {call.repeated && (
                  <span className="rounded bg-stone-200 px-1.5 py-0.5 text-[11px] text-stone-700">
                    repeated call — served from cache
                  </span>
                )}
              </div>

              <pre className="overflow-x-auto rounded-md bg-[--background] p-2 font-mono text-[11px] text-[--muted-foreground]">
                {JSON.stringify(call.arguments, null, 2)}
              </pre>
              <pre className="max-h-48 overflow-auto rounded-md bg-[--background] p-2 font-mono text-[11px] text-[--foreground]">
                {call.result}
              </pre>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
