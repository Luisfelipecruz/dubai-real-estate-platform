"use client";

import { BadgeCheck, ShieldAlert, ShieldX } from "lucide-react";
import { Card } from "@/components/ui/card";
import type { ResolvedCitation } from "@/lib/copilot";

/**
 * Citations after checking, not as the model claimed them.
 *
 * The two flags fail for different reasons and mean different things, so they get
 * different badges rather than one "verified" boolean:
 *
 *   resolved: false   — the chunk_id was never retrieved. A FABRICATED SOURCE.
 *   quote_found: false — the chunk is real, the quote is not in it. A PARAPHRASE
 *                        PRESENTED AS A QUOTATION, which is far more common, far easier
 *                        to miss, and the reason the quote is checked at all.
 *
 * m14 found both in real answers: an elision that was honest, and a quote that reversed
 * a measurement along with the conclusion drawn from it. Collapsing them into one badge
 * would throw away the distinction that made those findings legible.
 */
export function CitationList({ citations }: { citations: ResolvedCitation[] }) {
  if (citations.length === 0) {
    return (
      <Card className="p-5">
        <p className="text-sm text-[--muted-foreground]">
          No citations. That is correct for a refusal — there is nothing to cite when the
          system declined to answer.
        </p>
      </Card>
    );
  }

  const verified = citations.filter((c) => c.resolved && c.quote_found).length;

  return (
    <div className="space-y-2" data-testid="citation-list">
      <p className="text-xs text-[--muted-foreground]">
        {verified} of {citations.length} citations verified against the retrieved chunks.
      </p>

      {citations.map((citation, i) => {
        const fabricated = !citation.resolved;
        const paraphrased = citation.resolved && !citation.quote_found;
        const ok = citation.resolved && citation.quote_found;

        return (
          <Card
            key={i}
            data-testid="citation"
            className={
              fabricated
                ? "border-red-300 bg-red-50 p-4"
                : paraphrased
                  ? "border-amber-300 bg-amber-50 p-4"
                  : "p-4"
            }
          >
            <div className="mb-2 flex flex-wrap items-center gap-2">
              {ok && (
                <span
                  data-testid="citation-verified"
                  className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800"
                >
                  <BadgeCheck className="h-3 w-3" />
                  verified
                </span>
              )}
              {paraphrased && (
                <span
                  data-testid="citation-unverified"
                  className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800"
                >
                  <ShieldAlert className="h-3 w-3" />
                  quote not found in the chunk
                </span>
              )}
              {fabricated && (
                <span
                  data-testid="citation-unverified"
                  className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-800"
                >
                  <ShieldX className="h-3 w-3" />
                  source not retrieved
                </span>
              )}
              <span className="font-mono text-[11px] text-[--muted-foreground]">
                chunk {citation.chunk_id}
                {citation.source_id ? ` · ${citation.source_id}` : ""}
              </span>
            </div>

            <blockquote className="border-l-2 border-[--border] pl-3 text-xs italic leading-relaxed text-[--foreground]">
              “{citation.quote}”
            </blockquote>

            {citation.heading_path && (
              <p className="mt-2 font-mono text-[11px] text-[--muted-foreground]">
                {citation.heading_path}
              </p>
            )}

            {paraphrased && (
              <p className="mt-2 text-[11px] leading-relaxed text-amber-800">
                The chunk is real and was retrieved, but these words are not in it. That
                is a paraphrase presented as a quotation — the failure mode this check
                exists for.
              </p>
            )}
            {fabricated && (
              <p className="mt-2 text-[11px] leading-relaxed text-red-800">
                This chunk id was never retrieved for this question. The source is
                invented.
              </p>
            )}
          </Card>
        );
      })}
    </div>
  );
}
