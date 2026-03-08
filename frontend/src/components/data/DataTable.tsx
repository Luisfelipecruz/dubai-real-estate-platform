"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => React.ReactNode;
  align?: "left" | "right";
  sortable?: boolean;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  total: number;
  limit: number;
  offset: number;
  onPageChange: (offset: number) => void;
  sortBy?: string;
  sortOrder?: "asc" | "desc";
  onSort?: (key: string) => void;
  onLimitChange?: (limit: number) => void;
}

const PAGE_SIZES = [20, 50, 100];

export default function DataTable<T extends Record<string, any>>({
  columns,
  data,
  total,
  limit,
  offset,
  onPageChange,
  sortBy,
  sortOrder,
  onSort,
  onLimitChange,
}: DataTableProps<T>) {
  const page = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const showingFrom = total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + limit, total);

  function SortIcon({ colKey }: { colKey: string }) {
    if (sortBy !== colKey) {
      return <ArrowUpDown className="ml-1 inline h-3 w-3 opacity-40" />;
    }
    return sortOrder === "asc" ? (
      <ArrowUp className="ml-1 inline h-3 w-3" />
    ) : (
      <ArrowDown className="ml-1 inline h-3 w-3" />
    );
  }

  return (
    <div className="space-y-3">
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-[--border] bg-[--muted]/50 text-left">
                {columns.map((col) => {
                  const isSortable = col.sortable && onSort;
                  return (
                    <th
                      key={col.key}
                      className={`whitespace-nowrap px-4 py-3 text-xs font-semibold uppercase tracking-wider text-[--muted-foreground] ${
                        col.align === "right" ? "text-right" : ""
                      } ${isSortable ? "cursor-pointer select-none hover:text-[--foreground] transition-colors" : ""}`}
                      onClick={isSortable ? () => onSort(col.key) : undefined}
                    >
                      {col.label}
                      {isSortable && <SortIcon colKey={col.key} />}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className="divide-y divide-[--border]">
              {data.length === 0 ? (
                <tr>
                  <td
                    colSpan={columns.length}
                    className="px-4 py-10 text-center text-sm text-[--muted-foreground]"
                  >
                    No records found
                  </td>
                </tr>
              ) : (
                data.map((row, i) => (
                  <tr key={i} className="hover:bg-[--muted]/30 transition-colors">
                    {columns.map((col) => (
                      <td
                        key={col.key}
                        className={`whitespace-nowrap px-4 py-3 text-[--foreground] ${
                          col.align === "right" ? "text-right tabular-nums" : ""
                        }`}
                      >
                        {col.render
                          ? col.render(row)
                          : String(row[col.key] ?? "—")}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-[--muted-foreground]">
        <span>
          Showing {showingFrom}–{showingTo} of {total.toLocaleString()}
        </span>

        <div className="flex items-center gap-3">
          {onLimitChange && (
            <div className="flex items-center gap-1.5">
              <span className="text-xs">Rows:</span>
              <select
                value={limit}
                onChange={(e) => onLimitChange(Number(e.target.value))}
                className="h-8 rounded-md border border-[--border] bg-[--background] px-2 text-xs text-[--foreground] focus:outline-none focus:ring-1 focus:ring-[--ring]"
              >
                {PAGE_SIZES.map((size) => (
                  <option key={size} value={size}>
                    {size}
                  </option>
                ))}
              </select>
            </div>
          )}

          <span className="text-xs">
            Page {page} of {totalPages}
          </span>

          <div className="flex gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onPageChange(Math.max(0, offset - limit))}
              disabled={offset === 0}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => onPageChange(offset + limit)}
              disabled={offset + limit >= total}
            >
              Next
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
