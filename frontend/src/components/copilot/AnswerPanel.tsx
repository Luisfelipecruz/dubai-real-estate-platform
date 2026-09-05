"use client";

import { AlertTriangle, Ban, FileWarning, Info } from "lucide-react";
import { Card } from "@/components/ui/card";
import { OutcomeBadge } from "./OutcomeBadge";
import { CategoryChips } from "./CategoryChips";
import { RichText } from "./RichText";
import type { AgentOutcome } from "@/lib/copilot";

/**
 * The answer, and the three cases that are not an answer.
 *
 * Two rules, both about refusing to let a correct-but-unhappy result look like a bug:
 *
 *   1. A REFUSAL MUST LOOK LIKE A SUCCESS. It is a 200, and on the golden set it is the
 *      right result for the questions the data genuinely cannot answer. A red error box
 *      would say the opposite of what the system just did well.
 *
 *   2. THE EMPTY ANSWER MUST BE VISIBLE. A small share of runs return
 *      `outcome: answered` with an empty body, always the longest ones. Rendering that as
 *      a blank card is indistinguishable from a loading state, which would hide the one
 *      defect worth surfacing.
 *
 *      "An empty body" is `answer: null` in practice, not `answer: ""`. Hence
 *      `(answer ?? "").trim()` below rather than `answer.trim()`, which would throw on
 *      the exact case this branch exists for.
 */
export function AnswerPanel({
  outcome,
  answer,
  categories,
  warnings = [],
  unanswerableReason,
}: {
  outcome: AgentOutcome;
  answer: string | null;
  categories?: string | string[] | null;
  warnings?: string[];
  unanswerableReason?: string | null;
}) {
  const body = (answer ?? "").trim();
  const isEmpty = body.length === 0;

  return (
    <Card className="p-5 space-y-4" data-testid="answer-panel">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <OutcomeBadge outcome={outcome} />
        <CategoryChips categories={categories} />
      </div>

      {/* THE KNOWN DEFECT, named on screen. */}
      {outcome === "answered" && isEmpty && (
        <div
          data-testid="empty-answer-defect"
          className="flex gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4"
        >
          <FileWarning className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
          <div className="space-y-1">
            <p className="text-sm font-semibold text-amber-900">
              The run reported success and returned an empty answer.
            </p>
            <p className="text-xs leading-relaxed text-amber-800">
              This is a known defect, not a rendering fault: roughly 2–3 of 40 agent runs
              finish with <code>outcome: answered</code> and no prose, and it is always
              one of the longest runs. The tool trace below did execute — the findings are
              real, the summary is what went missing.
            </p>
          </div>
        </div>
      )}

      {/* A refusal. Neutral, explained, and NOT an error. */}
      {outcome === "refused" && (
        <div
          data-testid="refusal-notice"
          className="flex gap-3 rounded-lg border border-[--border] bg-[--muted] p-4"
        >
          <Ban className="mt-0.5 h-4 w-4 shrink-0 text-[--muted-foreground]" />
          <div className="space-y-1">
            <p className="text-sm font-medium text-[--foreground]">
              The system declined to answer.
            </p>
            <p className="text-xs leading-relaxed text-[--muted-foreground]">
              {unanswerableReason ||
                "Either the model declined, or every route reported that the available data cannot answer this question. Abstaining beats inventing a number, and this is a successful response — HTTP 200, not an error."}
            </p>
          </div>
        </div>
      )}

      {/* The cap fired. The findings below are partial and say so. */}
      {outcome === "max_steps" && (
        <div
          data-testid="cap-notice"
          className="flex gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
          <p className="text-xs leading-relaxed text-amber-800">
            The step cap fired before the model finished. Everything below is{" "}
            <strong>partial</strong> — the steps that ran are real, the conclusion is
            missing.
          </p>
        </div>
      )}

      {!isEmpty && (
        <div
          data-testid="answer-body"
          className="whitespace-pre-wrap text-sm leading-relaxed text-[--foreground]"
        >
          <RichText text={body} />
        </div>
      )}

      {/* Grounding warnings: SHOWN, never suppressed. */}
      {warnings.length > 0 && (
        <div
          data-testid="grounding-warnings"
          className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-4"
        >
          <div className="flex items-center gap-2">
            <Info className="h-4 w-4 text-amber-700" />
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-900">
              Grounding warnings ({warnings.length})
            </p>
          </div>
          <ul className="list-disc space-y-1 pl-5">
            {warnings.map((warning, i) => (
              <li key={i} className="text-xs leading-relaxed text-amber-800">
                {warning}
              </li>
            ))}
          </ul>
          <p className="text-[11px] italic text-amber-700">
            These are shown rather than hidden on purpose. Suppressing them to make the
            answer look clean would delete the feature in order to flatter the demo.
          </p>
        </div>
      )}
    </Card>
  );
}
