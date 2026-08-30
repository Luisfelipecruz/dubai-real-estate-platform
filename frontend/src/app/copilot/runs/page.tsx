"use client";

import { useEffect, useState } from "react";
import { AlertCircle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CategoryChips } from "@/components/copilot/CategoryChips";
import { OutcomeBadge } from "@/components/copilot/OutcomeBadge";
import {
  CopilotError,
  fetchRuns,
  formatCost,
  formatMs,
  formatPercent,
  type AgentOutcome,
  type RunsResponse,
} from "@/lib/copilot";
import { cn } from "@/lib/utils";

const FILTERS: (AgentOutcome | "all")[] = [
  "all",
  "answered",
  "refused",
  "max_steps",
  "failed",
];

/**
 * Every agent run this deployment has made, and what they add up to.
 *
 * This is the page that makes the milestone's claims checkable rather than asserted. The
 * refusal rate, the cap rate, the tool error rate and p50/p95 are one GROUP BY over
 * `agent_runs` — the same shape `/ask/costs` uses over `llm_calls`, and for the same
 * reason: a system that reports its own reliability from a table beats one that reports
 * it from a README.
 *
 * Every number here comes from the API. There is no arithmetic on this page.
 */
export default function RunsPage() {
  const [data, setData] = useState<RunsResponse | null>(null);
  const [filter, setFilter] = useState<AgentOutcome | "all">("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ message: string; status?: number } | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchRuns(50, filter === "all" ? undefined : filter)
      .then(setData)
      .catch((err) =>
        setError({
          message: err instanceof Error ? err.message : String(err),
          status: err instanceof CopilotError ? err.status : undefined,
        }),
      )
      .finally(() => setLoading(false));
  }, [filter]);

  const summary = data?.summary;

  return (
    <div className="mx-auto max-w-6xl space-y-5 px-4 py-6 md:px-8">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold text-[--foreground]">Agent runs</h1>
        <p className="text-sm text-[--muted-foreground]">
          Aggregates over every run this deployment has recorded. A refusal is a success
          here, not a fault — the refusal rate is a measurement, not an error budget.
        </p>
      </header>

      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setFilter(value)}
            aria-pressed={filter === value}
            className={cn(
              "rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors",
              filter === value
                ? "border-[--primary] bg-[--primary] text-[--primary-foreground]"
                : "border-[--border] text-[--muted-foreground] hover:bg-[--muted]",
            )}
          >
            {value}
          </button>
        ))}
      </div>

      {error && (
        <Card data-testid="runs-error" className="flex gap-3 border-red-300 bg-red-50 p-4">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-700" />
          <div className="space-y-1">
            <p className="text-sm font-semibold text-red-900">
              Could not load runs{error.status ? ` (HTTP ${error.status})` : ""}.
            </p>
            <p className="text-xs leading-relaxed text-red-800">{error.message}</p>
            {error.status === 503 && (
              <p className="text-xs leading-relaxed text-red-800">
                The <code>agent_runs</code> table does not exist yet. Run{" "}
                <code>docker compose exec api alembic upgrade head</code> (migration
                0003).
              </p>
            )}
          </div>
        </Card>
      )}

      {loading && !data ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-[88px] w-full rounded-xl" />
          ))}
        </div>
      ) : summary ? (
        <>
          <div
            data-testid="runs-summary"
            className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
          >
            <Stat label="runs" value={String(summary.runs)} />
            <Stat
              label="refusal rate"
              value={formatPercent(summary.refusal_rate)}
              note={`${summary.refused} of ${summary.runs} declined — the correct outcome when the data cannot answer.`}
            />
            <Stat
              label="cap rate"
              value={formatPercent(summary.cap_rate)}
              note={`${summary.hit_cap} run(s) hit the step cap and returned partial findings.`}
            />
            <Stat
              label="tool error rate"
              value={formatPercent(summary.tool_error_rate)}
              note={`${summary.tool_errors} of ${summary.tool_calls} tool calls failed.`}
            />
            <Stat label="p50 latency" value={formatMs(summary.p50_ms)} />
            <Stat label="p95 latency" value={formatMs(summary.p95_ms)} />
            <Stat
              label="unverified numbers"
              value={String(summary.unverified_numbers)}
              note="Figures that reached an answer without appearing in any tool result."
            />
            <Stat
              label="total cost"
              value={formatCost(summary.total_cost_usd)}
              note="Zero is a real measurement for a locally hosted model, not a missing value."
            />
          </div>

          <p className="text-[11px] leading-relaxed text-[--muted-foreground]">
            Latencies are from one developer laptop running a local model; host load alone
            moves the same call by 3–4×. They describe this machine, not the software.
          </p>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-[--foreground]">
              Recent runs ({data?.recent.length ?? 0})
            </h2>
            <div className="space-y-2">
              {data?.recent.map((run) => (
                <Card key={run.id} className="p-4" data-testid="run-row">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <p className="flex-1 text-sm text-[--foreground]">{run.question}</p>
                    <OutcomeBadge outcome={run.outcome} showNote={false} />
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-3">
                    <CategoryChips categories={run.categories} />
                    <span className="font-mono text-[11px] text-[--muted-foreground]">
                      {run.steps} step{run.steps === 1 ? "" : "s"} ·{" "}
                      {run.tool_calls} tool call{run.tool_calls === 1 ? "" : "s"}
                      {run.tool_errors > 0 ? ` (${run.tool_errors} failed)` : ""} ·{" "}
                      {formatMs(run.latency_ms)} ·{" "}
                      {formatCost(run.total_cost_usd, run.cost_priced)} ·{" "}
                      {run.provider}/{run.model}
                    </span>
                  </div>
                </Card>
              ))}
              {data?.recent.length === 0 && (
                <Card className="p-6 text-center">
                  <p className="text-sm text-[--muted-foreground]">
                    No runs match this filter.
                  </p>
                </Card>
              )}
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function Stat({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <Card className="p-4">
      <p className="text-[11px] uppercase tracking-wide text-[--muted-foreground]">
        {label}
      </p>
      <p className="mt-1 font-mono text-xl text-[--foreground]">{value}</p>
      {note && (
        <p className="mt-1.5 text-[11px] leading-relaxed text-[--muted-foreground]">
          {note}
        </p>
      )}
    </Card>
  );
}
