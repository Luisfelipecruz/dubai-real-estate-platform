"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Send } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AnswerPanel } from "@/components/copilot/AnswerPanel";
import { CitationList } from "@/components/copilot/CitationList";
import { EvidenceTrace } from "@/components/copilot/EvidenceTrace";
import { RunMeta } from "@/components/copilot/RunMeta";
import { RunProgress } from "@/components/copilot/RunProgress";
import { probeStreaming } from "@/lib/stream";
import {
  CopilotError,
  runAgent,
  runAsk,
  type AgentResponse,
  type AskResponse,
} from "@/lib/copilot";
import { cn } from "@/lib/utils";

type Route = "agent" | "ask";

/**
 * The copilot page.
 *
 * Two routes, because they answer different questions and the difference is the whole
 * point of having built both:
 *
 *   /ask           what do the documents say, with citations that were CHECKED
 *   /agent/query   work it out, using whichever tools are needed
 *
 * The evidence below the answer is what this page is for. An answer alone is what every
 * RAG demo shows; the trace, the verified citations and the routing categories are what
 * make this one auditable by the person reading it.
 */
export default function CopilotPage() {
  const [question, setQuestion] = useState("");
  const [route, setRoute] = useState<Route>("agent");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; status?: number } | null>(null);
  const [agentResult, setAgentResult] = useState<AgentResponse | null>(null);
  const [askResult, setAskResult] = useState<AskResponse | null>(null);
  const [canStream, setCanStream] = useState(false);

  useEffect(() => {
    // Asks the LIVE API whether it can stream, rather than assuming. Today this is false
    // everywhere; when the endpoint ships, this page starts streaming untouched.
    probeStreaming().then(setCanStream);
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const q = question.trim();
    if (q.length < 2 || busy) return;

    setBusy(true);
    setError(null);
    setAgentResult(null);
    setAskResult(null);

    try {
      if (route === "agent") setAgentResult(await runAgent(q));
      else setAskResult(await runAsk(q));
    } catch (err) {
      // A 503 means the LLM layer is off or unreachable and the remedy is a config
      // change; a 502 means the provider answered with something unusable and the remedy
      // is to try again. The stack is expected to run with LLM_PROVIDER=none, so this
      // path is a supported state, not an exception.
      setError({
        message: err instanceof Error ? err.message : String(err),
        status: err instanceof CopilotError ? err.status : undefined,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-5 px-4 py-6 md:px-8">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold text-[--foreground]">
          Market Intelligence Copilot
        </h1>
        <p className="text-sm text-[--muted-foreground]">
          Ask a question about the Dubai transaction, rent and valuation data. The answer
          comes with the evidence that produced it.
        </p>
      </header>

      <Card className="p-4">
        <form onSubmit={submit} className="space-y-3">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Of the areas bordering Business Bay, which had the highest transaction count in 2024?"
            rows={3}
            aria-label="Question"
            className="w-full resize-y rounded-lg border border-[--border] bg-[--background] px-3 py-2 text-sm text-[--foreground] placeholder:text-[--muted-foreground] focus:border-[--ring] focus:outline-none focus:ring-2 focus:ring-[--ring]/30"
          />

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div
              role="radiogroup"
              aria-label="Route"
              className="inline-flex rounded-lg border border-[--border] p-0.5"
            >
              {(
                [
                  ["agent", "agent — plans over tools"],
                  ["ask", "ask — grounded in documents"],
                ] as const
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={route === value}
                  onClick={() => setRoute(value)}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    route === value
                      ? "bg-[--primary] text-[--primary-foreground]"
                      : "text-[--muted-foreground] hover:bg-[--muted]",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>

            <Button type="submit" disabled={busy || question.trim().length < 2}>
              <Send className="mr-2 h-4 w-4" />
              {busy ? "Running…" : "Ask"}
            </Button>
          </div>
        </form>
      </Card>

      {busy && (
        <RunProgress
          streaming={canStream}
          stepsSoFar={agentResult?.steps.length ?? 0}
        />
      )}

      {error && (
        <Card
          data-testid="run-error"
          className="flex gap-3 border-red-300 bg-red-50 p-4"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-700" />
          <div className="space-y-1">
            <p className="text-sm font-semibold text-red-900">
              The request failed{error.status ? ` (HTTP ${error.status})` : ""}.
            </p>
            <p className="text-xs leading-relaxed text-red-800">{error.message}</p>
            {error.status === 503 && (
              <p className="text-xs leading-relaxed text-red-800">
                The LLM layer is disabled or unreachable. Check{" "}
                <code>LLM_PROVIDER</code> and that the model host is running — this is a
                configuration state, and the rest of the platform keeps working without
                it.
              </p>
            )}
          </div>
        </Card>
      )}

      {agentResult && (
        <div className="space-y-4">
          <AnswerPanel
            outcome={agentResult.outcome}
            answer={agentResult.answer}
            categories={agentResult.categories}
            warnings={agentResult.grounding_warnings}
          />
          <RunMeta
            provider={agentResult.provider}
            model={agentResult.model}
            cost={agentResult.usage.cost_usd}
            costPriced={agentResult.usage.cost_priced}
            timings={[
              { label: "total", ms: agentResult.timings_ms.total },
              { label: "generate", ms: agentResult.timings_ms.generate },
              { label: "tools", ms: agentResult.timings_ms.tools },
            ]}
            extra={[
              { label: "steps", value: String(agentResult.usage.steps) },
              {
                label: "tool calls",
                value: `${agentResult.usage.tool_calls} (${agentResult.usage.tool_errors} failed)`,
              },
            ]}
          />
          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-[--foreground]">
              Tool trace — {agentResult.steps.length} step
              {agentResult.steps.length === 1 ? "" : "s"}
            </h2>
            <EvidenceTrace steps={agentResult.steps} />
          </section>
        </div>
      )}

      {askResult && (
        <div className="space-y-4">
          <AnswerPanel
            outcome={askResult.answered ? "answered" : "refused"}
            answer={askResult.answer}
            warnings={askResult.grounding_warnings}
            unanswerableReason={askResult.unanswerable_reason}
          />
          <RunMeta
            provider={askResult.provider}
            model={askResult.model}
            cost={askResult.usage.cost_usd}
            costPriced={askResult.usage.cost_priced}
            timings={[
              { label: "total", ms: askResult.timings_ms.total },
              { label: "retrieve", ms: askResult.timings_ms.retrieve },
              { label: "generate", ms: askResult.timings_ms.generate },
            ]}
            extra={[
              { label: "confidence", value: askResult.confidence },
              {
                label: "retrieval",
                value: `${askResult.retrieval.mode}${askResult.retrieval.reranked ? " + rerank" : ""} k=${askResult.retrieval.k}`,
              },
            ]}
          />
          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-[--foreground]">Citations</h2>
            <CitationList citations={askResult.citations} />
          </section>
        </div>
      )}
    </div>
  );
}
