"use client";

import { Cpu, Info } from "lucide-react";
import { Card } from "@/components/ui/card";
import { formatCost, formatMs } from "@/lib/copilot";

/**
 * What the run cost, how long it took, and on what.
 *
 * The caveat at the bottom is a requirement, not politeness (plan §11.4.3). M-21, M-35,
 * M-48 and M-55 all recorded the same thing independently, and M-55 measured a 3–4×
 * swing on host load ALONE — same text, same warm model. A latency figure published
 * without saying it came from one loaded laptop invites exactly the comparison those
 * four measurements forbid, and this page is the first surface where such a number is
 * put in front of somebody who has not read them.
 *
 * The model is named for the same reason. `local · gpt-oss:20b` is a more interesting
 * badge than a hidden one, and hiding which model answered is how a demo takes credit
 * for a frontier model it is not running.
 */
export function RunMeta({
  provider,
  model,
  timings,
  cost,
  costPriced = true,
  extra,
}: {
  provider: string;
  model: string;
  timings: { label: string; ms: number | null }[];
  cost?: number | null;
  costPriced?: boolean;
  extra?: { label: string; value: string }[];
}) {
  return (
    <Card className="p-4 space-y-3" data-testid="run-meta">
      <div className="flex flex-wrap items-center gap-2">
        <Cpu className="h-4 w-4 text-[--muted-foreground]" />
        <span
          data-testid="run-model"
          className="rounded-md bg-[--secondary] px-2 py-0.5 font-mono text-[11px] font-medium text-[--secondary-foreground]"
        >
          {provider} · {model}
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        {timings.map((timing) => (
          <div key={timing.label}>
            <dt className="text-[11px] uppercase tracking-wide text-[--muted-foreground]">
              {timing.label}
            </dt>
            <dd className="font-mono text-sm text-[--foreground]">
              {formatMs(timing.ms)}
            </dd>
          </div>
        ))}
        {cost !== undefined && (
          <div>
            <dt className="text-[11px] uppercase tracking-wide text-[--muted-foreground]">
              cost
            </dt>
            <dd className="font-mono text-sm text-[--foreground]">
              {formatCost(cost, costPriced)}
            </dd>
          </div>
        )}
        {extra?.map((item) => (
          <div key={item.label}>
            <dt className="text-[11px] uppercase tracking-wide text-[--muted-foreground]">
              {item.label}
            </dt>
            <dd className="font-mono text-sm text-[--foreground]">{item.value}</dd>
          </div>
        ))}
      </dl>

      <p
        data-testid="latency-caveat"
        className="flex items-start gap-1.5 border-t border-[--border] pt-2 text-[11px] leading-relaxed text-[--muted-foreground]"
      >
        <Info className="mt-0.5 h-3 w-3 shrink-0" />
        <span>
          Measured on one developer laptop against a locally hosted model. Host load
          alone moves the same call by 3–4×, so these timings describe this machine at
          this moment — they are not a benchmark and do not transfer.
        </span>
      </p>
    </Card>
  );
}
