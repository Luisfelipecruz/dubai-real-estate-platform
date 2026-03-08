"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import type { AreaSummary, AreaDatasetStats } from "@/lib/types";

export default function AreaDetailPage() {
  const params = useParams();
  const areaName = decodeURIComponent(params.name as string);
  const [summary, setSummary] = useState<AreaSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch<AreaSummary>(`/areas/${encodeURIComponent(areaName)}/summary`)
      .then(setSummary)
      .catch(() => setSummary(null))
      .finally(() => setLoading(false));
  }, [areaName]);

  if (loading) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8">
        <p className="text-sm text-gray-500">Loading...</p>
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8">
        <p className="text-sm text-red-600">Failed to load area data</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <Link
        href="/areas"
        className="text-sm text-blue-600 hover:text-blue-800"
      >
        &larr; All areas
      </Link>

      <h1 className="mt-3 text-2xl font-bold tracking-tight">{areaName}</h1>
      <p className="mt-1 text-sm text-gray-600">
        Cross-dataset summary
      </p>

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <StatsCard title="Transactions" stats={summary.transactions} />
        <StatsCard title="Rent Contracts" stats={summary.rents} />
        <StatsCard title="Valuations" stats={summary.valuations} />
      </div>

      <div className="mt-6 flex gap-3">
        <Link
          href={`/transactions?area_name=${encodeURIComponent(areaName)}`}
          className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium hover:bg-gray-50"
        >
          View Transactions
        </Link>
        <Link
          href={`/rents?area_name=${encodeURIComponent(areaName)}`}
          className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium hover:bg-gray-50"
        >
          View Rents
        </Link>
      </div>
    </div>
  );
}

function StatsCard({
  title,
  stats,
}: {
  title: string;
  stats: AreaDatasetStats;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5">
      <h3 className="text-sm font-medium text-gray-500">{title}</h3>
      <p className="mt-1 text-2xl font-semibold">{stats.count.toLocaleString()}</p>
      <p className="text-xs text-gray-500">records</p>

      {stats.count > 0 && (
        <div className="mt-4 space-y-2 text-sm">
          <StatRow
            label="Avg price"
            value={stats.avg_price}
            suffix=" AED"
          />
          <StatRow
            label="Min"
            value={stats.min_price}
            suffix=" AED"
          />
          <StatRow
            label="Max"
            value={stats.max_price}
            suffix=" AED"
          />
          <StatRow
            label="Avg area"
            value={stats.avg_area_sqm}
            suffix=" sqm"
          />
        </div>
      )}
    </div>
  );
}

function StatRow({
  label,
  value,
  suffix,
}: {
  label: string;
  value: number | null;
  suffix: string;
}) {
  return (
    <div className="flex justify-between">
      <span className="text-gray-500">{label}</span>
      <span className="font-medium text-gray-900">
        {value != null
          ? value.toLocaleString("en-US", { maximumFractionDigits: 0 }) + suffix
          : "—"}
      </span>
    </div>
  );
}
