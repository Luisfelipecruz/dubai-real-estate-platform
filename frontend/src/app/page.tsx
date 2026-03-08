import Link from "next/link";
import {
  ArrowLeftRight,
  FileText,
  Calculator,
  Upload,
  CheckCircle2,
  TrendingUp,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import QualityChecksPanel from "@/components/dashboard/QualityChecksPanel";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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

interface UploadRecord {
  id: string | number;
  dataset_type: string;
  filename: string;
  uploaded_at: string;
  rows_received: number;
  rows_inserted: number;
  rows_duplicate: number;
  rows_rejected: number;
  status: string;
}

interface Area {
  area_name_en: string;
  transaction_count: number;
  rent_count: number;
  valuation_count: number;
  avg_transaction_price: number | null;
  avg_rent_amount: number | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_URL = process.env.INTERNAL_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Data fetchers
// ---------------------------------------------------------------------------

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

async function getUploads(): Promise<UploadRecord[]> {
  try {
    const res = await fetch(`${API_URL}/uploads`, { cache: "no-store" });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

async function getAreas(): Promise<Area[]> {
  try {
    const res = await fetch(`${API_URL}/areas?limit=5`, { cache: "no-store" });
    if (!res.ok) return [];
    const data: Area[] = await res.json();
    return data.slice(0, 5);
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

function formatCurrency(amount: number): string {
  if (amount >= 1_000_000) {
    const val = amount / 1_000_000;
    return `AED ${val % 1 === 0 ? val.toFixed(0) : val.toFixed(1)}M`;
  }
  if (amount >= 1_000) {
    const val = amount / 1_000;
    return `AED ${val % 1 === 0 ? val.toFixed(0) : val.toFixed(1)}K`;
  }
  return `AED ${amount.toLocaleString()}`;
}

function formatTimeAgo(dateStr: string): string {
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return dateStr;

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  if (diffSec < 60) return "Just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;

  return date.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function formatNumber(n: number): string {
  return n.toLocaleString("en-US");
}

// ---------------------------------------------------------------------------
// Sub-components (server, no "use client" needed)
// ---------------------------------------------------------------------------

function KpiCard({
  label,
  value,
  href,
  icon,
}: {
  label: string;
  value: number | undefined;
  href: string;
  icon: React.ReactNode;
}) {
  return (
    <Link href={href} className="group block">
      <Card className="h-full transition-all hover:shadow-md hover:border-[--primary]/40">
        <CardContent className="p-5">
          <div className="flex items-start justify-between mb-3">
            <div
              className="p-2 rounded-lg"
              style={{ backgroundColor: "var(--muted)" }}
            >
              {icon}
            </div>
          </div>
          <p
            className="text-xs font-medium uppercase tracking-wider mb-1"
            style={{ color: "var(--muted-foreground)" }}
          >
            {label}
          </p>
          <p
            className="text-3xl font-bold tabular-nums"
            style={{ color: "var(--foreground)" }}
          >
            {value !== undefined ? formatNumber(value) : "—"}
          </p>
          <p
            className="mt-2 text-xs font-medium group-hover:underline"
            style={{ color: "var(--primary)" }}
          >
            View all &rarr;
          </p>
        </CardContent>
      </Card>
    </Link>
  );
}

function DatasetBadge({ type }: { type: string }) {
  const normalized = type.toLowerCase();

  if (normalized.includes("transaction")) {
    return (
      <span
        className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold"
        style={{ backgroundColor: "#dbeafe", color: "#1e40af" }}
      >
        Transactions
      </span>
    );
  }
  if (normalized.includes("rent")) {
    return (
      <span
        className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold"
        style={{ backgroundColor: "#fef3c7", color: "#92400e" }}
      >
        Rents
      </span>
    );
  }
  if (normalized.includes("valuation")) {
    return (
      <span
        className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold"
        style={{ backgroundColor: "#ede9fe", color: "#5b21b6" }}
      >
        Valuations
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold"
      style={{ backgroundColor: "var(--muted)", color: "var(--muted-foreground)" }}
    >
      {type}
    </span>
  );
}

function UploadStatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  if (normalized === "success" || normalized === "completed") {
    return <Badge variant="success">Success</Badge>;
  }
  if (normalized === "failed" || normalized === "error") {
    return <Badge variant="destructive">Failed</Badge>;
  }
  return <Badge variant="secondary">{status}</Badge>;
}


// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default async function Home() {
  const [stats, quality, uploads, areas] = await Promise.all([
    getStats(),
    getQuality(),
    getUploads(),
    getAreas(),
  ]);

  const recentUploads = uploads.slice(0, 5);

  return (
    <div className="px-4 py-8 md:px-8 max-w-6xl mx-auto space-y-8">

      {/* ------------------------------------------------------------------ */}
      {/* KPI Cards                                                           */}
      {/* ------------------------------------------------------------------ */}
      <section>
        <h2
          className="text-xs font-semibold uppercase tracking-wider mb-4"
          style={{ color: "var(--muted-foreground)" }}
        >
          Dataset Overview
        </h2>
        <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
          <KpiCard
            label="Transactions"
            value={stats?.transactions}
            href="/transactions"
            icon={
              <ArrowLeftRight
                className="h-5 w-5"
                style={{ color: "var(--primary)" }}
              />
            }
          />
          <KpiCard
            label="Rent Contracts"
            value={stats?.rents}
            href="/rents"
            icon={
              <FileText
                className="h-5 w-5"
                style={{ color: "var(--primary)" }}
              />
            }
          />
          <KpiCard
            label="Valuations"
            value={stats?.valuations}
            href="/valuations"
            icon={
              <Calculator
                className="h-5 w-5"
                style={{ color: "var(--primary)" }}
              />
            }
          />
          <KpiCard
            label="Data Uploads"
            value={stats?.uploads}
            href="/upload"
            icon={
              <Upload
                className="h-5 w-5"
                style={{ color: "var(--primary)" }}
              />
            }
          />
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Two-column section: Top Areas + Recent Uploads                      */}
      {/* ------------------------------------------------------------------ */}
      <section className="grid gap-6 md:grid-cols-5">

        {/* Top Areas — wider column */}
        <div className="md:col-span-3">
          <Card className="h-full">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <TrendingUp
                    className="h-4 w-4"
                    style={{ color: "var(--primary)" }}
                  />
                  <CardTitle className="text-sm font-semibold">
                    Top Areas by Activity
                  </CardTitle>
                </div>
                <Link
                  href="/areas"
                  className="text-xs font-medium hover:underline"
                  style={{ color: "var(--primary)" }}
                >
                  View all &rarr;
                </Link>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {areas.length === 0 ? (
                <div className="px-6 pb-6">
                  <p
                    className="text-sm text-center py-8"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    No area data available.
                  </p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr
                        className="border-t text-left"
                        style={{
                          borderColor: "var(--border)",
                          backgroundColor: "color-mix(in srgb, var(--muted) 50%, transparent)",
                        }}
                      >
                        <th
                          className="px-5 py-2.5 text-xs font-semibold uppercase tracking-wider"
                          style={{ color: "var(--muted-foreground)" }}
                        >
                          Area
                        </th>
                        <th
                          className="px-5 py-2.5 text-xs font-semibold uppercase tracking-wider text-right"
                          style={{ color: "var(--muted-foreground)" }}
                        >
                          Transactions
                        </th>
                        <th
                          className="px-5 py-2.5 text-xs font-semibold uppercase tracking-wider text-right"
                          style={{ color: "var(--muted-foreground)" }}
                        >
                          Avg Price
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {areas.map((area, idx) => (
                        <tr
                          key={area.area_name_en}
                          className="border-t transition-colors hover:bg-[--muted]/30"
                          style={{ borderColor: "var(--border)" }}
                        >
                          <td className="px-5 py-3">
                            <Link
                              href={`/areas/${encodeURIComponent(area.area_name_en)}`}
                              className="font-medium hover:underline flex items-center gap-2"
                              style={{ color: "var(--foreground)" }}
                            >
                              <span
                                className="inline-flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold shrink-0"
                                style={{
                                  backgroundColor: "var(--muted)",
                                  color: "var(--muted-foreground)",
                                }}
                              >
                                {idx + 1}
                              </span>
                              {area.area_name_en}
                            </Link>
                          </td>
                          <td
                            className="px-5 py-3 text-right tabular-nums"
                            style={{ color: "var(--foreground)" }}
                          >
                            {formatNumber(area.transaction_count)}
                          </td>
                          <td
                            className="px-5 py-3 text-right tabular-nums text-xs"
                            style={{ color: "var(--muted-foreground)" }}
                          >
                            {area.avg_transaction_price != null
                              ? formatCurrency(area.avg_transaction_price)
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Recent Uploads — narrower column */}
        <div className="md:col-span-2">
          <Card className="h-full">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Upload
                    className="h-4 w-4"
                    style={{ color: "var(--primary)" }}
                  />
                  <CardTitle className="text-sm font-semibold">
                    Recent Uploads
                  </CardTitle>
                </div>
                <Link
                  href="/upload"
                  className="text-xs font-medium hover:underline"
                  style={{ color: "var(--primary)" }}
                >
                  Upload &rarr;
                </Link>
              </div>
            </CardHeader>
            <CardContent className="px-5 pb-5 pt-0">
              {recentUploads.length === 0 ? (
                <p
                  className="text-sm text-center py-8"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  No uploads yet.
                </p>
              ) : (
                <div className="space-y-3">
                  {recentUploads.map((upload, idx) => (
                    <div
                      key={upload.id ?? idx}
                      className="flex flex-col gap-1.5 pb-3 border-b last:border-0 last:pb-0"
                      style={{ borderColor: "var(--border)" }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <DatasetBadge type={upload.dataset_type} />
                        <UploadStatusBadge status={upload.status} />
                      </div>
                      <p
                        className="text-xs font-mono truncate"
                        style={{ color: "var(--foreground)" }}
                        title={upload.filename}
                      >
                        {upload.filename}
                      </p>
                      <div
                        className="flex items-center justify-between text-xs"
                        style={{ color: "var(--muted-foreground)" }}
                      >
                        <span>{formatTimeAgo(upload.uploaded_at)}</span>
                        <span>{formatNumber(upload.rows_inserted)} rows</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Data Quality                                                         */}
      {/* ------------------------------------------------------------------ */}
      <section>
        <h2
          className="text-xs font-semibold uppercase tracking-wider mb-4"
          style={{ color: "var(--muted-foreground)" }}
        >
          Data Quality
        </h2>

        {quality && quality.run_id ? (
          <Card>
            <CardHeader className="pb-0">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-sm font-semibold">
                    Quality Check Results
                  </CardTitle>
                  <p
                    className="mt-0.5 text-xs"
                    style={{ color: "var(--muted-foreground)" }}
                  >
                    Run ID:{" "}
                    <span className="font-mono">{quality.run_id}</span>
                  </p>
                </div>
                <div className="flex gap-2 flex-wrap">
                  <Badge variant="success">
                    {quality.summary.pass} Pass
                  </Badge>
                  {quality.summary.fail > 0 && (
                    <Badge variant="destructive">
                      {quality.summary.fail} Fail
                    </Badge>
                  )}
                  {quality.summary.warn > 0 && (
                    <Badge variant="warning">
                      {quality.summary.warn} Warn
                    </Badge>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-0 mt-4">
              <QualityChecksPanel checks={quality.checks} />
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="py-10 text-center">
              <p
                className="text-sm"
                style={{ color: "var(--muted-foreground)" }}
              >
                No quality checks have been run yet.
              </p>
              <p
                className="text-xs mt-1"
                style={{ color: "var(--muted-foreground)" }}
              >
                Trigger the{" "}
                <code
                  className="font-mono rounded px-1.5 py-0.5"
                  style={{
                    backgroundColor: "var(--muted)",
                    color: "var(--foreground)",
                  }}
                >
                  quality_checks
                </code>{" "}
                DAG in Airflow.
              </p>
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  );
}
