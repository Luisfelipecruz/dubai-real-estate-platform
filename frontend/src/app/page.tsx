import Link from "next/link";
import { ArrowRight, Upload } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

interface Stats {
  transactions: number;
  rents: number;
  valuations: number;
  uploads: number;
}

interface QualityCheck {
  check_name: string;
  category: string;
  dataset: string | null;
  status: "pass" | "fail" | "warn";
  message: string;
  value: number | null;
  threshold: number | null;
  checked_at: string | null;
}

interface QualityResult {
  run_id: string | null;
  checks: QualityCheck[];
  summary: { pass: number; fail: number; warn: number };
}

const API_URL = process.env.INTERNAL_API_URL || "http://localhost:8000";

async function getStats(): Promise<Stats | null> {
  try {
    const res = await fetch(`${API_URL}/stats`, { cache: "no-store" });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

async function getQuality(): Promise<QualityResult | null> {
  try {
    const res = await fetch(`${API_URL}/quality`, { cache: "no-store" });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function Home() {
  const stats = await getStats();
  const quality = await getQuality();

  return (
    <div className="px-4 py-8 md:px-8 max-w-6xl mx-auto space-y-8">
      {/* Stat cards */}
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-[--muted-foreground] mb-4">
          Dataset Overview
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Transactions" value={stats?.transactions} href="/transactions" />
          <StatCard label="Rent Contracts" value={stats?.rents} href="/rents" />
          <StatCard label="Valuations" value={stats?.valuations} href="/valuations" />
          <StatCard label="Uploads" value={stats?.uploads} href="/upload" />
        </div>
      </section>

      {/* Quick actions */}
      <section className="flex flex-wrap gap-3">
        <Button asChild>
          <Link href="/upload">
            <Upload className="h-4 w-4" />
            Upload CSV
          </Link>
        </Button>
        <Button variant="outline" asChild>
          <Link href="/areas">
            Browse Areas
            <ArrowRight className="h-4 w-4" />
          </Link>
        </Button>
      </section>

      {/* Quality Status Panel */}
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-wider text-[--muted-foreground] mb-4">
          Data Quality
        </h2>

        {quality && quality.run_id ? (
          <Card>
            <CardHeader className="pb-4">
              <div className="flex items-center justify-between flex-wrap gap-3">
                <CardTitle className="text-base">Quality Check Results</CardTitle>
                <div className="flex gap-2">
                  <Badge variant="success">{quality.summary.pass} Pass</Badge>
                  {quality.summary.fail > 0 && (
                    <Badge variant="destructive">{quality.summary.fail} Fail</Badge>
                  )}
                  {quality.summary.warn > 0 && (
                    <Badge variant="warning">{quality.summary.warn} Warn</Badge>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-t border-[--border] bg-[--muted]/50 text-left">
                      <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-[--muted-foreground]">Check</th>
                      <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-[--muted-foreground]">Category</th>
                      <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-[--muted-foreground]">Dataset</th>
                      <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-[--muted-foreground]">Status</th>
                      <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider text-[--muted-foreground]">Details</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[--border]">
                    {quality.checks.map((c) => (
                      <tr key={c.check_name} className="hover:bg-[--muted]/30 transition-colors">
                        <td className="px-4 py-3 font-mono text-xs text-[--foreground]">{c.check_name}</td>
                        <td className="px-4 py-3 text-[--foreground]">{c.category}</td>
                        <td className="px-4 py-3 text-[--muted-foreground]">{c.dataset || "—"}</td>
                        <td className="px-4 py-3">
                          <StatusBadge status={c.status} />
                        </td>
                        <td className="px-4 py-3 text-[--muted-foreground] max-w-xs truncate">{c.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="py-8 text-center">
              {/* Skeleton placeholder to illustrate loading state */}
              <div className="mx-auto max-w-sm space-y-3 hidden">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4 mx-auto" />
                <Skeleton className="h-4 w-1/2 mx-auto" />
              </div>
              <p className="text-sm text-[--muted-foreground]">
                No quality checks have been run yet.
              </p>
              <p className="text-xs text-[--muted-foreground] mt-1">
                Trigger the <code className="font-mono bg-[--muted] px-1.5 py-0.5 rounded text-[--foreground]">quality_checks</code> DAG in Airflow.
              </p>
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  );
}

function StatCard({
  label,
  value,
  href,
}: {
  label: string;
  value: number | undefined;
  href: string;
}) {
  return (
    <Link href={href} className="group block">
      <Card className="transition-shadow hover:shadow-md">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs font-medium uppercase tracking-wider text-[--muted-foreground]">
            {label}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-3xl font-bold text-[--foreground] tabular-nums">
            {value !== undefined ? value.toLocaleString() : (
              <Skeleton className="h-9 w-24 inline-block" />
            )}
          </p>
          <p className="mt-1.5 text-xs text-[--primary] font-medium group-hover:underline">
            View all &rarr;
          </p>
        </CardContent>
      </Card>
    </Link>
  );
}

function StatusBadge({ status }: { status: "pass" | "fail" | "warn" }) {
  const variant =
    status === "pass" ? "success" : status === "fail" ? "destructive" : "warning";
  return <Badge variant={variant}>{status}</Badge>;
}
