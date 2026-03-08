"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { PaginatedResponse, Valuation } from "@/lib/types";
import DataTable from "@/components/data/DataTable";

export default function ValuationsPage() {
  const [data, setData] = useState<PaginatedResponse<Valuation> | null>(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [areaFilter, setAreaFilter] = useState("");
  const [yearFilter, setYearFilter] = useState("");
  const limit = 20;

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (areaFilter) params.set("area_name", areaFilter);
    if (yearFilter) params.set("procedure_year", yearFilter);

    apiFetch<PaginatedResponse<Valuation>>(`/valuations?${params}`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [offset, areaFilter, yearFilter]);

  function handleFilter() {
    setOffset(0);
  }

  const columns = [
    {
      key: "instance_date",
      label: "Date",
      render: (row: Valuation) =>
        row.instance_date ? row.instance_date.split("T")[0] : "—",
    },
    { key: "procedure_name_en", label: "Procedure" },
    { key: "property_type_en", label: "Type" },
    { key: "area_name_en", label: "Area" },
    { key: "procedure_year", label: "Year" },
    {
      key: "actual_worth",
      label: "Worth (AED)",
      align: "right" as const,
      render: (row: Valuation) =>
        row.actual_worth != null
          ? row.actual_worth.toLocaleString("en-US", { maximumFractionDigits: 0 })
          : "—",
    },
    {
      key: "property_total_value",
      label: "Total Value (AED)",
      align: "right" as const,
      render: (row: Valuation) =>
        row.property_total_value != null
          ? row.property_total_value.toLocaleString("en-US", { maximumFractionDigits: 0 })
          : "—",
    },
    { key: "row_status_code", label: "Status" },
  ];

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-bold tracking-tight">Valuations</h1>

      <div className="mt-4 flex flex-wrap gap-3">
        <input
          type="text"
          placeholder="Filter by area..."
          value={areaFilter}
          onChange={(e) => { setAreaFilter(e.target.value); handleFilter(); }}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
        <input
          type="number"
          placeholder="Year (e.g. 2026)"
          value={yearFilter}
          onChange={(e) => { setYearFilter(e.target.value); handleFilter(); }}
          className="w-36 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
      </div>

      <div className="mt-4">
        {loading ? (
          <p className="text-sm text-gray-500">Loading...</p>
        ) : data ? (
          <DataTable
            columns={columns}
            data={data.data}
            total={data.total}
            limit={data.limit}
            offset={data.offset}
            onPageChange={setOffset}
          />
        ) : (
          <p className="text-sm text-red-600">Failed to load data</p>
        )}
      </div>
    </div>
  );
}
