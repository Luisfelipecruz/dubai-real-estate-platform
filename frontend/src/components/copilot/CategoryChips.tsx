"use client";

import { cn } from "@/lib/utils";
import { CATEGORY_STYLE, parseCategories } from "@/lib/copilot";

/**
 * Which tool categories the run actually used, in first-use order.
 *
 * This is the routing evidence, and it is the m14 prompt-injection mitigation made
 * visible. A question about transaction volume that reaches `rag` alone got the right
 * SHAPE of answer from the wrong place — that is precisely the failure m14 found and
 * could not fix by verification, because the answer was faithful to a corpus that was
 * wrong. Routing it to `COUNT(*)` is the fix, and these chips are how a reader checks
 * that it happened without opening a log.
 */
export function CategoryChips({
  categories,
  className,
}: {
  categories: string | string[] | null | undefined;
  className?: string;
}) {
  const parsed = parseCategories(categories);

  if (parsed.length === 0) {
    // A run that called no tools. The refused run in this session's captures is exactly
    // this: one turn, zero tools, a correct decline. An empty space would read as
    // missing data rather than as the fact it is.
    return (
      <span className={cn("text-xs text-[--muted-foreground]", className)}>
        no tools called
      </span>
    );
  }

  return (
    <div className={cn("flex flex-wrap gap-1.5", className)}>
      {parsed.map((category) => (
        <span
          key={category}
          data-testid="category-chip"
          className={cn(
            "inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-[11px] font-medium",
            CATEGORY_STYLE[category] ?? "bg-stone-100 text-stone-700 border-stone-200",
          )}
        >
          {category}
        </span>
      ))}
    </div>
  );
}
