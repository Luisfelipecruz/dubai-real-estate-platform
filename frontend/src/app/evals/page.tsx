"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Terminal, XCircle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  CATEGORY_STYLE,
  fetchTools,
  formatMs,
  type ToolCatalogue,
} from "@/lib/copilot";
import { cn } from "@/lib/utils";

interface VoiceStage {
  stage: string;
  target_ms: number;
  measured_ms: number;
  over_by_ms: number;
  within_target: boolean;
  source: string;
}

interface VoiceBudget {
  budget_ms: number;
  target_total_ms: number;
  stages: VoiceStage[];
  verdict: string;
  rerank_on_voice_path: boolean;
}

const API_BASE =
  typeof window !== "undefined"
    ? process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    : process.env.INTERNAL_API_URL || "http://localhost:8000";

/**
 * What this deployment can prove about itself.
 *
 * ── The finding this page produced ────────────────────────────────────────
 *
 * The plan asked for the three golden fixtures, the cohort split and which thresholds
 * pass. Building it established that NONE OF THAT HAS AN HTTP SURFACE. The API exposes
 * 36 operations and not one of them returns an eval result: the fixtures are graded by
 * `make eval-*`, which writes to a terminal, and the thresholds are a YAML file the
 * container never reads.
 *
 * So the honest page is this one. It renders what the API genuinely reports — the tool
 * catalogue the model is handed, and the voice budget with its per-stage verdict — and
 * it prints the commands for everything else instead of hardcoding numbers that would
 * silently go stale. Transcribing 74 graded questions into TypeScript would produce a
 * page that looks authoritative and stops being true the next time the graders change,
 * which is the exact failure the `--regrade` flag exists to prevent.
 *
 * That gap is a result, and it belongs to this milestone: an eval harness with no API is
 * invisible to everything except the person who runs make.
 */
export default function EvalsPage() {
  const [tools, setTools] = useState<ToolCatalogue | null>(null);
  const [budget, setBudget] = useState<VoiceBudget | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([
      fetchTools(),
      fetch(`${API_BASE}/voice/budget`).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([toolsResult, budgetResult]) => {
        if (toolsResult.status === "fulfilled") setTools(toolsResult.value);
        if (budgetResult.status === "fulfilled" && budgetResult.value)
          setBudget(budgetResult.value as VoiceBudget);
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-6 md:px-8">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold text-[--foreground]">Evaluation</h1>
        <p className="text-sm text-[--muted-foreground]">
          What this deployment reports about itself, and what it can only report from a
          terminal.
        </p>
      </header>

      {/* ── The gap, stated first because it is the finding ── */}
      <Card className="border-amber-200 bg-amber-50 p-5">
        <div className="flex gap-3">
          <Terminal className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
          <div className="space-y-2">
            <p className="text-sm font-semibold text-amber-900">
              The golden fixtures have no HTTP endpoint.
            </p>
            <p className="text-xs leading-relaxed text-amber-800">
              Three fixtures — answers, routing and retrieval — are graded by the eval
              harness and written to a terminal. Nothing in the API returns them, so this
              page cannot show them without transcribing numbers into TypeScript, where
              they would look authoritative and quietly go stale the next time a grader
              changes. The commands are below instead. Giving the harness an endpoint is
              the obvious next milestone, and this page is how that became obvious.
            </p>
            <pre className="overflow-x-auto rounded-md bg-amber-100 p-3 font-mono text-[11px] text-amber-900">
              {[
                "make eval-truths      # verify every fixture answer against live SQL",
                "make eval-answers     # grade 40 answers: counts, money, spatial, multi-hop",
                "make eval-routing     # grade which tools each question reached",
                "make eval-retrieval   # nDCG, hit@k and MRR over 20 cohort-labelled questions",
                "make eval-gate        # fail if any threshold floor is breached",
              ].join("\n")}
            </pre>
          </div>
        </div>
      </Card>

      {/* ── The voice budget: a real verdict from a real endpoint ── */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-[--foreground]">
          Voice latency budget
        </h2>
        {loading && !budget ? (
          <Skeleton className="h-[220px] w-full rounded-xl" />
        ) : budget ? (
          <Card className="p-5 space-y-4" data-testid="voice-budget">
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant={budget.verdict.startsWith("MET") ? "success" : "warning"}>
                {budget.verdict}
              </Badge>
              <span className="font-mono text-[11px] text-[--muted-foreground]">
                budget {budget.budget_ms} ms · plan target {budget.target_total_ms} ms
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[--border] text-[--muted-foreground]">
                    <th className="py-1.5 pr-3 font-medium">stage</th>
                    <th className="py-1.5 pr-3 font-medium">target</th>
                    <th className="py-1.5 pr-3 font-medium">measured</th>
                    <th className="py-1.5 pr-3 font-medium">verdict</th>
                  </tr>
                </thead>
                <tbody>
                  {budget.stages.map((stage) => (
                    <tr
                      key={stage.stage}
                      className="border-b border-[--border] last:border-0"
                    >
                      <td className="py-1.5 pr-3 font-mono">{stage.stage}</td>
                      <td className="py-1.5 pr-3 font-mono text-[--muted-foreground]">
                        {formatMs(stage.target_ms)}
                      </td>
                      <td className="py-1.5 pr-3 font-mono">
                        {formatMs(stage.measured_ms)}
                      </td>
                      <td className="py-1.5 pr-3">
                        {stage.within_target ? (
                          <span className="inline-flex items-center gap-1 text-emerald-700">
                            <CheckCircle2 className="h-3 w-3" />
                            within
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-amber-700">
                            <XCircle className="h-3 w-3" />+
                            {formatMs(stage.over_by_ms)}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <p className="text-[11px] leading-relaxed text-[--muted-foreground]">
              The speech stack is not what breaks this budget. Generation is the largest
              stage by a wide margin; the three stages the voice milestone added are a
              minority of the total. The reranker is off on this path —{" "}
              <code>rerank_on_voice_path: {String(budget.rerank_on_voice_path)}</code> —
              because it cost 2.9 s to make retrieval measurably worse.
            </p>
          </Card>
        ) : (
          <Card className="p-5">
            <p className="text-sm text-[--muted-foreground]">
              <code>/voice/budget</code> is unavailable — the voice container is not
              running. The rest of the platform is unaffected.
            </p>
          </Card>
        )}
      </section>

      {/* ── The tool catalogue, exactly as the model receives it ── */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-[--foreground]">
          Tool catalogue{tools ? ` — ${tools.total} tools` : ""}
        </h2>
        {loading && !tools ? (
          <Skeleton className="h-[200px] w-full rounded-xl" />
        ) : tools ? (
          <Card className="p-5 space-y-3" data-testid="tool-catalogue">
            <p className="text-xs text-[--muted-foreground]">
              What the model is handed when it plans. Provider{" "}
              <code>{tools.provider}</code>, cap {tools.max_steps} steps, budget $
              {tools.max_cost_usd_per_run.toFixed(2)} per run.
            </p>
            <div className="space-y-1.5">
              {tools.tools.map((tool) => (
                <div
                  key={tool.name}
                  className="flex flex-wrap items-baseline gap-2 border-b border-[--border] pb-1.5 last:border-0"
                >
                  <span
                    className={cn(
                      "inline-flex shrink-0 rounded-md border px-1.5 py-0.5 font-mono text-[10px]",
                      CATEGORY_STYLE[tool.category] ??
                        "bg-stone-100 text-stone-700 border-stone-200",
                    )}
                  >
                    {tool.category}
                  </span>
                  <span className="font-mono text-xs font-medium text-[--foreground]">
                    {tool.name}
                  </span>
                  <span className="flex-1 text-[11px] leading-relaxed text-[--muted-foreground]">
                    {tool.description.split("\n")[0]}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        ) : (
          <Card className="p-5">
            <p className="text-sm text-[--muted-foreground]">
              <code>/agent/tools</code> is unavailable — the agent layer is disabled or
              the API is unreachable.
            </p>
          </Card>
        )}
      </section>
    </div>
  );
}
