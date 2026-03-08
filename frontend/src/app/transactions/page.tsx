"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { PaginatedResponse, Transaction } from "@/lib/types";
import DataTable from "@/components/data/DataTable";
import { Skeleton } from "@/components/ui/skeleton";

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
    <div className="px-4 py-8 md:px-8 max-w-6xl mx-auto space-y-6">
      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <input
          type="text"
          placeholder="Filter by area..."
          value={areaFilter}
          onChange={(e) => { setAreaFilter(e.target.value); handleFilter(); }}
          className="rounded-lg border border-[--border] bg-[--background] px-3 py-2 text-sm text-[--foreground] placeholder:text-[--muted-foreground] focus:border-[--ring] focus:outline-none focus:ring-2 focus:ring-[--ring]/30"
        />
        <select
          value={groupFilter}
          onChange={(e) => { setGroupFilter(e.target.value); handleFilter(); }}
          className="rounded-lg border border-[--border] bg-[--background] px-3 py-2 text-sm text-[--foreground] focus:border-[--ring] focus:outline-none focus:ring-2 focus:ring-[--ring]/30"
        >
          <option value="">All groups</option>
          <option value="Sales">Sales</option>
          <option value="Mortgages">Mortgages</option>
          <option value="Gifts">Gifts</option>
        </select>
      </div>

      {/* Table */}
      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-10 w-full" />
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
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
        <p className="text-sm text-[--destructive]">Failed to load transaction data.</p>
      )}
    </div>
  );
}
