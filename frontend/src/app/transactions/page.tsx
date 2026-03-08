"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { PaginatedResponse, Transaction } from "@/lib/types";
import DataTable from "@/components/data/DataTable";

export default function TransactionsPage() {
  const [data, setData] = useState<PaginatedResponse<Transaction> | null>(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [areaFilter, setAreaFilter] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const limit = 20;

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (areaFilter) params.set("area_name", areaFilter);
    if (groupFilter) params.set("trans_group", groupFilter);

    apiFetch<PaginatedResponse<Transaction>>(`/transactions?${params}`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [offset, areaFilter, groupFilter]);

  function handleFilter() {
    setOffset(0);
  }

  const columns = [
    { key: "instance_date", label: "Date" },
    { key: "trans_group_en", label: "Group" },
    { key: "property_type_en", label: "Type" },
    { key: "area_name_en", label: "Area" },
    { key: "rooms_en", label: "Rooms" },
    {
      key: "actual_worth",
      label: "Amount (AED)",
      align: "right" as const,
      render: (row: Transaction) =>
        row.actual_worth != null
          ? row.actual_worth.toLocaleString("en-US", { maximumFractionDigits: 0 })
          : "—",
    },
    {
      key: "procedure_area",
      label: "Area (sqm)",
      align: "right" as const,
      render: (row: Transaction) =>
        row.procedure_area != null ? row.procedure_area.toLocaleString() : "—",
    },
    { key: "reg_type_en", label: "Reg Type" },
  ];

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-bold tracking-tight">Transactions</h1>

      <div className="mt-4 flex flex-wrap gap-3">
        <input
          type="text"
          placeholder="Filter by area..."
          value={areaFilter}
          onChange={(e) => { setAreaFilter(e.target.value); handleFilter(); }}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
        <select
          value={groupFilter}
          onChange={(e) => { setGroupFilter(e.target.value); handleFilter(); }}
          className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        >
          <option value="">All groups</option>
          <option value="Sales">Sales</option>
          <option value="Mortgages">Mortgages</option>
          <option value="Gifts">Gifts</option>
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
