"use client";

import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "@/lib/api";
import type { PaginatedResponse, RentContract } from "@/lib/types";
import DataTable from "@/components/data/DataTable";
import type { Column } from "@/components/data/DataTable";
import FilterPanel from "@/components/data/FilterPanel";
import type { FilterField } from "@/components/data/FilterPanel";
import { Skeleton } from "@/components/ui/skeleton";

const FILTER_FIELDS: FilterField[] = [
  {
    key: "area_name",
    label: "Area",
    type: "text",
    placeholder: "e.g. Al Thanyah Fifth",
  },
  {
    key: "contract_reg_type",
    label: "Contract Type",
    type: "select",
    options: [
      { value: "", label: "All" },
      { value: "New", label: "New" },
      { value: "Renew", label: "Renew" },
    ],
  },
  {
    key: "property_type",
    label: "Property Type",
    type: "select",
    options: [
      { value: "", label: "All" },
      { value: "Flat", label: "Flat" },
      { value: "Villa", label: "Villa" },
      { value: "Office", label: "Office" },
      { value: "Warehouse", label: "Warehouse" },
      { value: "Labor Camps", label: "Labor Camps" },
    ],
  },
  { key: "date_from", label: "Date From", type: "date" },
  { key: "date_to", label: "Date To", type: "date" },
  {
    key: "min_amount",
    label: "Min Annual (AED)",
    type: "number",
    placeholder: "0",
    min: 0,
  },
  {
    key: "max_amount",
    label: "Max Annual (AED)",
    type: "number",
    placeholder: "Any",
    min: 0,
  },
];

const INITIAL_FILTERS: Record<string, string> = {
  area_name: "",
  contract_reg_type: "",
  property_type: "",
  date_from: "",
  date_to: "",
  min_amount: "",
  max_amount: "",
};

export default function RentsPage() {
  const [data, setData] = useState<PaginatedResponse<RentContract> | null>(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(20);
  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [sortBy, setSortBy] = useState("contract_start_date");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  const fetchData = useCallback(() => {
    setLoading(true);
    const params = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
      sort_by: sortBy,
      sort_order: sortOrder,
    });
    for (const [k, v] of Object.entries(filters)) {
      if (v) params.set(k, v);
    }

    apiFetch<PaginatedResponse<RentContract>>(`/rents?${params}`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [offset, limit, filters, sortBy, sortOrder]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  function handleFilterChange(key: string, value: string) {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setOffset(0);
  }

  function handleFilterReset() {
    setFilters(INITIAL_FILTERS);
    setOffset(0);
  }

  function handleSort(key: string) {
    if (sortBy === key) {
      setSortOrder((o) => (o === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(key);
      setSortOrder("desc");
    }
    setOffset(0);
  }

  function handleLimitChange(newLimit: number) {
    setLimit(newLimit);
    setOffset(0);
  }

  const columns: Column<RentContract>[] = [
    { key: "contract_start_date", label: "Start Date", sortable: true },
    { key: "contract_reg_type_en", label: "Type" },
    { key: "ejari_property_type_en", label: "Property" },
    { key: "area_name_en", label: "Area" },
    { key: "property_usage_en", label: "Usage" },
    {
      key: "annual_amount",
      label: "Annual (AED)",
      align: "right",
      sortable: true,
      render: (row: RentContract) =>
        row.annual_amount != null
          ? row.annual_amount.toLocaleString("en-US", { maximumFractionDigits: 0 })
          : "—",
    },
    {
      key: "actual_area",
      label: "Area (sqm)",
      align: "right",
      render: (row: RentContract) =>
        row.actual_area != null ? row.actual_area.toLocaleString() : "—",
    },
    { key: "tenant_type_en", label: "Tenant" },
  ];

  return (
    <div className="px-4 py-6 md:px-8 max-w-6xl mx-auto space-y-4">
      <FilterPanel
        fields={FILTER_FIELDS}
        values={filters}
        onChange={handleFilterChange}
        onReset={handleFilterReset}
      />

      {loading ? (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-11 w-full" />
          ))}
        </div>
      ) : data ? (
        <DataTable
          columns={columns}
          data={data.data}
          total={data.total}
          limit={limit}
          offset={data.offset}
          onPageChange={setOffset}
          sortBy={sortBy}
          sortOrder={sortOrder}
          onSort={handleSort}
          onLimitChange={handleLimitChange}
        />
      ) : (
        <div className="rounded-lg border border-[--border] bg-[--background] px-4 py-10 text-center">
          <p className="text-sm text-[--muted-foreground]">
            Failed to load rent contract data. Please check the API connection.
          </p>
        </div>
      )}
    </div>
  );
}
