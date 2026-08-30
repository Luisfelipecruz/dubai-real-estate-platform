"use client";

import { useEffect, useState } from "react";
import { Loader2, Radio, RadioTower } from "lucide-react";
import { Card } from "@/components/ui/card";

/**
 * What the page shows while a run is in flight.
 *
 * A spinner in front of a 58-second run is not a demo, it is a bug report — and the run
 * captured while building this page took 66.0 seconds, which is longer than any run in
 * the recorded range. So this counts UP, out loud, and says what it is waiting for.
 *
 * ── On the notice below ───────────────────────────────────────────────────
 *
 * `GET /agent/stream` is specified in the plan and is not built: its endpoint lives in
 * `api/routers/agent.py` and the per-step hook it needs lives in
 * `api/services/agent/executor.py`, and both belong to an earlier milestone that is
 * committed but not yet merged. Until then a run returns in ONE response at the end.
 *
 * The temptation here is a typewriter animation over that single response. This page
 * does not do that, and the refusal is the point rather than fastidiousness: a project
 * whose entire thesis is honest measurement cannot ship an animation that lies about
 * latency on its own front page. Saying "no trace until it finishes, because streaming
 * is not built yet" is worth more than a fake that looks better.
 */
export function RunProgress({
  streaming,
  stepsSoFar,
  now = Date.now,
}: {
  streaming: boolean;
  stepsSoFar: number;
  /** Injectable so a test can assert the elapsed counter without waiting in real time. */
  now?: () => number;
}) {
  const [started] = useState(() => now());
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setElapsed(now() - started), 200);
    return () => clearInterval(id);
  }, [started, now]);

  const seconds = (elapsed / 1000).toFixed(1);

  return (
    <Card className="p-5 space-y-3" data-testid="run-progress">
      <div className="flex items-center gap-3">
        <Loader2 className="h-4 w-4 animate-spin text-[--primary]" />
        <span className="text-sm font-medium text-[--foreground]">
          Running — <span className="font-mono">{seconds}s</span> elapsed
        </span>
      </div>

      {streaming ? (
        <p className="flex items-start gap-2 text-xs leading-relaxed text-[--muted-foreground]">
          <RadioTower className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
          <span>
            Streaming live. {stepsSoFar} step{stepsSoFar === 1 ? "" : "s"} so far — each
            one appears as the tool returns.
          </span>
        </p>
      ) : (
        <p
          data-testid="no-streaming-notice"
          className="flex items-start gap-2 text-xs leading-relaxed text-[--muted-foreground]"
        >
          <Radio className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            <strong>No live trace:</strong> this API build has no{" "}
            <code>/agent/stream</code>, so the whole run arrives in one response when it
            finishes. Agent runs on this machine have taken between 1.4 and 66.0 seconds.
            Nothing below is hidden — there is genuinely nothing to show yet, and an
            animation pretending otherwise would misreport the latency this project
            exists to measure.
          </span>
        </p>
      )}
    </Card>
  );
}
