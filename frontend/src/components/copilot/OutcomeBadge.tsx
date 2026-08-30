"use client";

import { Badge } from "@/components/ui/badge";
import { OUTCOME_STYLE, type AgentOutcome } from "@/lib/copilot";

/**
 * How a run ended, and what that means.
 *
 * The note is not decoration. `/agent/query` returns HTTP 200 for all four outcomes and
 * two of them are successes, so the status code tells a reader nothing and the word
 * alone is ambiguous — "refused" reads as a fault to anyone who has not read
 * `docs/llm-app-layer.md` §3.1. Saying what it means, next to it, is what turns a
 * correct abstention from something that looks broken into the feature it is.
 */
export function OutcomeBadge({
  outcome,
  showNote = true,
}: {
  outcome: AgentOutcome;
  showNote?: boolean;
}) {
  const style = OUTCOME_STYLE[outcome];
  if (!style) return null;

  return (
    <div className="flex flex-col gap-1.5">
      <Badge variant={style.variant} data-testid="outcome-badge">
        {style.label}
      </Badge>
      {showNote && (
        <p className="text-xs leading-relaxed text-[--muted-foreground]">{style.note}</p>
      )}
    </div>
  );
}
