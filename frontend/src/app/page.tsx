import Link from "next/link";

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
    <main className="mx-auto max-w-5xl px-4 py-12">
      <h1 className="text-3xl font-bold tracking-tight">
        Dubai Real Estate Market Intelligence
      </h1>
      <p className="mt-2 text-gray-600">
        Upload, explore, and analyze Dubai Land Department data.
      </p>

      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Transactions"
          value={stats?.transactions}
          href="/transactions"
        />
        <StatCard
          label="Rent Contracts"
          value={stats?.rents}
          href="/rents"
        />
        <StatCard
          label="Valuations"
          value={stats?.valuations}
          href="/valuations"
        />
        <StatCard
          label="Uploads"
          value={stats?.uploads}
          href="/upload"
        />
      </div>

      <div className="mt-8 flex gap-4">
        <Link
          href="/upload"
          className="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          Upload CSV
        </Link>
        <Link
          href="/areas"
          className="rounded-lg border border-gray-300 bg-white px-5 py-2.5 text-sm font-medium hover:bg-gray-50"
        >
          Browse Areas
        </Link>
      </div>

      {/* Quality Status Panel */}
      <div className="mt-10">
        <h2 className="text-xl font-semibold">Data Quality</h2>
        {quality && quality.run_id ? (
          <>
            <div className="mt-3 flex gap-3">
              <QualityBadge label="Pass" count={quality.summary.pass} color="green" />
              <QualityBadge label="Fail" count={quality.summary.fail} color="red" />
              <QualityBadge label="Warn" count={quality.summary.warn} color="yellow" />
            </div>
            <div className="mt-4 overflow-x-auto rounded-lg border border-gray-200">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left text-gray-600">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Check</th>
                    <th className="px-4 py-2.5 font-medium">Category</th>
                    <th className="px-4 py-2.5 font-medium">Dataset</th>
                    <th className="px-4 py-2.5 font-medium">Status</th>
                    <th className="px-4 py-2.5 font-medium">Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {quality.checks.map((c) => (
                    <tr key={c.check_name} className="hover:bg-gray-50">
                      <td className="px-4 py-2 font-mono text-xs">{c.check_name}</td>
                      <td className="px-4 py-2">{c.category}</td>
                      <td className="px-4 py-2">{c.dataset || "—"}</td>
                      <td className="px-4 py-2">
                        <StatusPill status={c.status} />
                      </td>
                      <td className="px-4 py-2 text-gray-600">{c.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="mt-3 text-sm text-gray-500">
            No quality checks have been run yet. Trigger the quality_checks DAG in Airflow.
          </p>
        )}
      </div>
    </main>
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
    <Link
      href={href}
      className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm hover:shadow-md transition-shadow"
    >
      <p className="text-sm text-gray-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold">
        {value !== undefined ? value.toLocaleString() : "—"}
      </p>
    </Link>
  );
}

function QualityBadge({
  label,
  count,
  color,
}: {
  label: string;
  count: number;
  color: "green" | "red" | "yellow";
}) {
  const colors = {
    green: "bg-green-100 text-green-800",
    red: "bg-red-100 text-red-800",
    yellow: "bg-yellow-100 text-yellow-800",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium ${colors[color]}`}>
      {count} {label}
    </span>
  );
}

function StatusPill({ status }: { status: "pass" | "fail" | "warn" }) {
  const styles = {
    pass: "bg-green-100 text-green-700",
    fail: "bg-red-100 text-red-700",
    warn: "bg-yellow-100 text-yellow-700",
  };
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[status]}`}>
      {status}
    </span>
  );
}
