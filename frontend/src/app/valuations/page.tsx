"use client";

import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "@/lib/api";
import type { PaginatedResponse, Valuation } from "@/lib/types";
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
    placeholder: "e.g. Business Bay",
  },
  {
    key: "property_type",
    label: "Property Type",
    type: "select",
    options: [
      { value: "", label: "All" },
      { value: "Unit", label: "Unit" },
      { value: "Land", label: "Land" },
      { value: "Building", label: "Building" },
    ],
  },
  {
    key: "procedure_year",
    label: "Year",
    type: "number",
    placeholder: "e.g. 2026",
  },
  {
    key: "min_worth",
    label: "Min Worth (AED)",
    type: "number",
    placeholder: "0",
    min: 0,
  },
  {
    key: "max_worth",
    label: "Max Worth (AED)",
    type: "number",
    placeholder: "Any",
    min: 0,
  },
];

const INITIAL_FILTERS: Record<string, string> = {
  area_name: "",
  property_type: "",
  procedure_year: "",
  min_worth: "",
  max_worth: "",
};

export default function ValuationsPage() {
  const [data, setData] = useState<PaginatedResponse<Valuation> | null>(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [limit, setLimit] = useState(20);
  const [filters, setFilters] = useState(INITIAL_FILTERS);
  const [sortBy, setSortBy] = useState("instance_date");
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

    apiFetch<PaginatedResponse<Valuation>>(`/valuations?${params}`)
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

  const columns: Column<Valuation>[] = [
    {
      key: "instance_date",
      label: "Date",
      sortable: true,
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
      align: "right",
      sortable: true,
      render: (row: Valuation) =>
        row.actual_worth != null
          ? row.actual_worth.toLocaleString("en-US", { maximumFractionDigits: 0 })
          : "—",
    },
    {
      key: "property_total_value",
      label: "Total Value (AED)",
      align: "right",
      sortable: true,
      render: (row: Valuation) =>
        row.property_total_value != null
          ? row.property_total_value.toLocaleString("en-US", { maximumFractionDigits: 0 })
          : "—",
    },
    { key: "row_status_code", label: "Status" },
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
            Failed to load valuation data. Please check the API connection.
          </p>
        </div>
      )}
    </div>
  );
}
