import Link from "next/link";

interface Stats {
  transactions: number;
  rents: number;
  valuations: number;
  uploads: number;
}

async function getStats(): Promise<Stats | null> {
  try {
    const res = await fetch(
      `${process.env.INTERNAL_API_URL || "http://localhost:8000"}/stats`,
      { cache: "no-store" }
    );
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function Home() {
  const stats = await getStats();

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
