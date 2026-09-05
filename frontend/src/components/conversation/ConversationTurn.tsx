"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { EvidenceTrace } from "@/components/copilot/EvidenceTrace";
import { RichText } from "@/components/copilot/RichText";
import type { AgentStep } from "@/lib/copilot";
import type { ProgressState } from "@/lib/progress";
import { StatusLine } from "./StatusLine";

/**
 * One question and its answer, for someone who came here to ask about Dubai property.
 *
 * ── The contradiction this component resolves ─────────────────────────────
 *
 * Two audiences want opposite things. A reviewer wants the tool trace — it is the
 * evidence, and the most interesting part of the system. Someone asking about Dubai
 * property wants an answer without the machinery in front of it. Both are right, and the
 * resolution is PROGRESSIVE DISCLOSURE, NOT DELETION.
 *
 * So: the default view is an answer. One button reveals the complete, unchanged
 * `EvidenceTrace` — the same per-step costs, the same raw payloads, and failed calls
 * shown at the same weight as successful ones. Nothing is summarised on the way out and
 * nothing is filtered.
 *
 * THE LINE THAT MUST NOT BE CROSSED: if the evidence is not reachable in one click from
 * every answer, this component has failed even if the page looks better. The toggle is
 * therefore rendered for every outcome — including refusals and empty answers, which are
 * exactly the cases where a reader most needs to see what actually ran.
 *
 * ── What is NOT collapsible ───────────────────────────────────────────────
 *
 * Grounding warnings. They stay on screen at full strength in the default view. They are
 * not evidence a curious reader might want; they are a caveat attached to the answer
 * itself, and hiding one behind a click would be suppressing it. `AnswerPanel` makes the
 * same call for the same reason.
 */
/**
 * What the button says, counted from THE SAME ARRAY THE PANEL RENDERS.
 *
 * It used to count progress lines with a step number, which is one per TOOL step --
 * progress.ts gives a line belonging to the run as a whole step 0, and "Wrote the answer"
 * is one of those. The panel below renders every executor step including the synthesis
 * turn that only reasoned, so the button read "2 steps" over a list ending at step 3.
 *
 * `steps` is present whenever this button is: the `done` frame carries it and the /ask
 * route has no toggle. The line count remains the fallback so a run that arrives without
 * steps still says something true rather than zero.
 *
 * A failure is counted as a STEP that contains one, not as a failed call, because
 * "3 steps, 1 failed" is read as one failed step -- and a single step can make several
 * calls.
 */
function countSteps(steps: AgentStep[], state: ProgressState) {
  if (steps.length > 0) {
    return {
      stepCount: steps.length,
      failedSteps: steps.filter((s) => s.tool_calls.some((c) => !c.ok)).length,
    };
  }
  return {
    stepCount: state.lines.filter((l) => l.step > 0).length,
    failedSteps: state.failures,
  };
}

export function ConversationTurn({
  question,
  state,
  steps,
  warnings = [],
  streamingAvailable = false,
}: {
  question: string;
  state: ProgressState;
  /** The full trace, shown behind the toggle. Empty until the run returns. */
  steps: AgentStep[];
  warnings?: string[];
  /**
   * Whether `GET /agent/stream` exists on the API this page is talking to. Comes from
   * `probeStreaming()`, not from a flag — and it changes what the waiting state can
   * honestly claim, so it is passed in rather than assumed.
   */
  streamingAvailable?: boolean;
}) {
  const [showEvidence, setShowEvidence] = useState(false);
  const { stepCount, failedSteps } = countSteps(steps, state);

  const running = state.status === "working" || state.status === "idle";
  const body = (state.answer ?? state.streamedText).trim();

  return (
    <div className="space-y-4" data-testid="conversation-turn">
      <p className="text-sm font-medium text-[--foreground]" data-testid="turn-question">
        {question}
      </p>

      {running ? (
        <Card className="p-5 space-y-3">
          <StatusLine state={state} />
          {/* The honesty note about the non-streaming path. Without `/agent/stream` the
              whole run arrives in one response at the end, so these lines all appear at
              once when it does — they are not a live feed and this says so. Replaying
              them on a timer to look live is the one thing this surface must never do. */}
          {!streamingAvailable && (
            <p
              data-testid="not-live-notice"
              className="text-xs leading-relaxed text-[--muted-foreground]"
            >
              This API build has no live stream, so nothing appears until the run
              finishes — and then all of it appears at once. Agent runs on this machine
              have taken between 1.4 and 66.0 seconds.
            </p>
          )}
        </Card>
      ) : (
        <Card className="p-5 space-y-4" data-testid="turn-answer">
          {/* The four ways a run can end, in plain language. None of them is a blank
              card, and none of them is an error box. */}
          {state.emptyAnswer && (
            <Outcome
              testId="turn-empty"
              tone="warn"
              title="I gathered the data but could not write the summary."
              // Hiding the machinery is exactly what turns this run
              // into a blank screen after 66 seconds. The findings are real and the
              // button below reaches them.
              body="This is a known defect in the agent, not a problem with your question. The steps below did run and their results are real — the final write-up is what went missing. Open the working to read what was found."
            />
          )}

          {state.outcome === "refused" && (
            <Outcome
              testId="turn-refused"
              tone="neutral"
              title="I can't answer that from the data I have."
              body="Either the question falls outside what this dataset records, or answering it would mean guessing. Abstaining is the intended behaviour here rather than a failure — a made-up number would be worse than no number."
            />
          )}

          {state.outcome === "max_steps" && (
            <Outcome
              testId="turn-capped"
              tone="warn"
              title="I ran out of steps before finishing."
              body="What follows is partial. The steps that ran are real; the conclusion is missing. Asking a narrower question usually finishes inside the budget."
            />
          )}

          {state.status === "incomplete" && (
            <Outcome
              testId="turn-incomplete"
              tone="warn"
              title="The run stopped before it finished."
              body={state.error ?? "The connection ended early."}
            />
          )}

          {body.length > 0 && (
            <div
              data-testid="turn-body"
              className="whitespace-pre-wrap text-sm leading-relaxed text-[--foreground]"
            >
              <RichText text={body} />
            </div>
          )}

          {/* NOT collapsible. See the header. */}
          {warnings.length > 0 && (
            <div
              data-testid="turn-warnings"
              className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-4"
            >
              <div className="flex items-center gap-2">
                <Info className="h-4 w-4 text-amber-700" />
                <p className="text-xs font-semibold text-amber-900">
                  Worth knowing about this answer
                </p>
              </div>
              <ul className="list-disc space-y-1 pl-5">
                {warnings.map((w, i) => (
                  <li key={i} className="text-xs leading-relaxed text-amber-800">
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* ONE CLICK. On every outcome, always. */}
          <div className="border-t border-[--border] pt-3">
            <button
              type="button"
              data-testid="evidence-toggle"
              aria-expanded={showEvidence}
              onClick={() => setShowEvidence((o) => !o)}
              className={cn(
                "flex items-center gap-2 text-xs font-medium",
                "text-[--muted-foreground] transition-colors hover:text-[--foreground]",
              )}
            >
              {showEvidence ? (
                <ChevronDown className="h-3.5 w-3.5" />
              ) : (
                <ChevronRight className="h-3.5 w-3.5" />
              )}
              {showEvidence ? "Hide the working" : "Show the working"}
              <span className="font-normal">
                ({stepCount} step{stepCount === 1 ? "" : "s"}
                {failedSteps > 0 && `, ${failedSteps} failed`})
              </span>
            </button>

            {showEvidence && (
              <div className="space-y-4 pt-4" data-testid="evidence-panel">
                {/* The plain-language account of what ran, and then the complete,
                    unmodified evidence trace underneath it. */}
                <StatusLine state={state} />
                <EvidenceTrace steps={steps} />
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  );
}

function Outcome({
  testId,
  tone,
  title,
  body,
}: {
  testId: string;
  tone: "warn" | "neutral";
  title: string;
  body: string;
}) {
  return (
    <div
      data-testid={testId}
      className={cn(
        "space-y-1 rounded-lg border p-4",
        tone === "warn"
          ? "border-amber-200 bg-amber-50"
          : "border-[--border] bg-[--muted]",
      )}
    >
      <p
        className={cn(
          "text-sm font-medium",
          tone === "warn" ? "text-amber-900" : "text-[--foreground]",
        )}
      >
        {title}
      </p>
      <p
        className={cn(
          "text-xs leading-relaxed",
          tone === "warn" ? "text-amber-800" : "text-[--muted-foreground]",
        )}
      >
        {body}
      </p>
    </div>
  );
}
