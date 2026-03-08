"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { PaginatedResponse, RentContract } from "@/lib/types";
import DataTable from "@/components/data/DataTable";

export default function RentsPage() {
  const [data, setData] = useState<PaginatedResponse<RentContract> | null>(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [areaFilter, setAreaFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const limit = 20;

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (areaFilter) params.set("area_name", areaFilter);
    if (typeFilter) params.set("contract_reg_type", typeFilter);

    apiFetch<PaginatedResponse<RentContract>>(`/rents?${params}`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [offset, areaFilter, typeFilter]);

  function handleFilter() {
    setOffset(0);
  }

  const columns = [
    { key: "contract_start_date", label: "Start Date" },
    { key: "contract_reg_type_en", label: "Type" },
    { key: "ejari_property_type_en", label: "Property" },
    { key: "area_name_en", label: "Area" },
    { key: "property_usage_en", label: "Usage" },
    {
      key: "annual_amount",
      label: "Annual (AED)",
      align: "right" as const,
      render: (row: RentContract) =>
        row.annual_amount != null
          ? row.annual_amount.toLocaleString("en-US", { maximumFractionDigits: 0 })
          : "—",
    },
    {
      key: "actual_area",
      label: "Area (sqm)",
      align: "right" as const,
      render: (row: RentContract) =>
        row.actual_area != null ? row.actual_area.toLocaleString() : "—",
    },
    { key: "tenant_type_en", label: "Tenant" },
  ];

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-bold tracking-tight">Rent Contracts</h1>

      <div className="mt-4 flex flex-wrap gap-3">
        <input
          type="text"
          placeholder="Filter by area..."
          value={areaFilter}
          onChange={(e) => { setAreaFilter(e.target.value); handleFilter(); }}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
        <select
          value={typeFilter}
          onChange={(e) => { setTypeFilter(e.target.value); handleFilter(); }}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        >
          <option value="">All types</option>
          <option value="New">New</option>
          <option value="Renew">Renew</option>
        </select>
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
