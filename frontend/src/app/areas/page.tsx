"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api";
import type { AreaOverview } from "@/lib/types";

export default function AreasPage() {
  const [areas, setAreas] = useState<AreaOverview[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    apiFetch<AreaOverview[]>("/areas")
      .then(setAreas)
      .catch(() => setAreas([]))
      .finally(() => setLoading(false));
  }, []);

  const filtered = search
    ? areas.filter((a) =>
        a.area_name_en.toLowerCase().includes(search.toLowerCase())
      )
    : areas;

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-bold tracking-tight">Areas</h1>
      <p className="mt-1 text-sm text-gray-600">
        Cross-dataset overview of all Dubai areas
      </p>

      <div className="mt-4">
        <input
          type="text"
          placeholder="Search areas..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
      </div>

      {loading ? (
        <p className="mt-6 text-sm text-gray-500">Loading...</p>
      ) : (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((area) => (
            <Link
              key={area.area_name_en}
              href={`/areas/${encodeURIComponent(area.area_name_en)}`}
              className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md"
            >
              <h3 className="font-semibold text-gray-900">
                {area.area_name_en}
              </h3>
              <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                <div>
                  <p className="text-lg font-semibold text-gray-900">
                    {area.transaction_count}
                  </p>
                  <p className="text-gray-500">Transactions</p>
                </div>
                <div>
                  <p className="text-lg font-semibold text-gray-900">
                    {area.rent_count}
                  </p>
                  <p className="text-gray-500">Rents</p>
                </div>
                <div>
                  <p className="text-lg font-semibold text-gray-900">
                    {area.valuation_count}
                  </p>
                  <p className="text-gray-500">Valuations</p>
                </div>
              </div>
              {area.avg_transaction_price != null && (
                <p className="mt-3 text-xs text-gray-500">
                  Avg transaction:{" "}
                  <span className="font-medium text-gray-700">
                    {area.avg_transaction_price.toLocaleString("en-US", {
                      maximumFractionDigits: 0,
                    })}{" "}
                    AED
                  </span>
                </p>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
