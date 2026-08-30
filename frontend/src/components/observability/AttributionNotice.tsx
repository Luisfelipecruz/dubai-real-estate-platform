import { AlertTriangle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { formatLatency, formatRate, type ToolAttribution } from "@/lib/observability";

/**
 * The tool error rate, and — when the platform cannot name the failing tool — why not.
 *
 * The failure this component exists to prevent: a per-tool bar chart fed by a table that
 * never received per-tool rows renders as a chart with no bars, which is the same pixels
 * as a system where nothing fails. 31 of 301 tool calls did fail. The chart would be
 * reporting the opposite of the truth, confidently, with no error anywhere.
 *
 * So the unattributable state is a written sentence with a remedy attached, not an empty
 * chart. The rate is still shown, because the rate is real; what is missing is the
 * breakdown, and the missing thing is what gets named.
 */
export function AttributionNotice({ attribution }: { attribution: ToolAttribution }) {
  const { tool_calls, tool_errors, tool_error_rate, attributable, by_tool } = attribution;

  return (
    <Card className="p-5" data-testid="attribution" data-attributable={attributable}>
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-[--muted-foreground]">
            Tool errors
          </p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">
            {formatRate(tool_error_rate)}
          </p>
        </div>
        <p className="text-xs tabular-nums text-[--muted-foreground]">
          {tool_errors} of {tool_calls} calls
        </p>
      </div>

      {attributable ? (
        <table className="mt-4 w-full text-sm" data-testid="attribution-table">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-[--muted-foreground]">
              <th className="pb-2 font-medium">Tool</th>
              <th className="pb-2 text-right font-medium">Calls</th>
              <th className="pb-2 text-right font-medium">Errors</th>
              <th className="pb-2 text-right font-medium">Rate</th>
              <th className="pb-2 text-right font-medium">p50</th>
            </tr>
          </thead>
          <tbody>
            {by_tool.map((tool) => (
              <tr
                key={tool.tool_name}
                className="border-t border-[--border]"
                data-testid="attribution-row"
                data-tool={tool.tool_name}
              >
                <td className="py-2 font-mono text-xs">{tool.tool_name}</td>
                <td className="py-2 text-right tabular-nums">{tool.calls}</td>
                <td className="py-2 text-right tabular-nums">{tool.errors}</td>
                <td className="py-2 text-right tabular-nums">
                  {formatRate(tool.error_rate)}
                </td>
                <td className="py-2 text-right tabular-nums">
                  {formatLatency(tool.p50_ms)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div
          className="mt-4 flex gap-3 rounded-lg border border-[--border] bg-[--muted] p-4"
          data-testid="attribution-unavailable"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <div className="space-y-2 text-sm">
            <p className="font-medium">These errors cannot be traced to a tool.</p>
            {attribution.reason && (
              <p className="text-[--muted-foreground]" data-testid="attribution-reason">
                {attribution.reason}
              </p>
            )}
            {attribution.remedy && (
              <p className="text-[--muted-foreground]" data-testid="attribution-remedy">
                {attribution.remedy}
              </p>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
