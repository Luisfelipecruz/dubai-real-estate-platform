"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => React.ReactNode;
  align?: "left" | "right";
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  total: number;
  limit: number;
  offset: number;
  onPageChange: (offset: number) => void;
}

export default function DataTable<T extends Record<string, unknown>>({
  columns,
  data,
  total,
  limit,
  offset,
  onPageChange,
}: DataTableProps<T>) {
  const page = Math.floor(offset / limit) + 1;
  const totalPages = Math.ceil(total / limit);

  return (
    <div className="space-y-3">
      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-[--border] bg-[--muted]/50 text-left">
                {columns.map((col) => (
                  <th
                    key={col.key}
                    className={`whitespace-nowrap px-4 py-3 text-xs font-semibold uppercase tracking-wider text-[--muted-foreground] ${
                      col.align === "right" ? "text-right" : ""
                    }`}
                  >
                    {col.label}
                  </th>
                ))}
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

      <div className="flex items-center justify-between text-sm text-[--muted-foreground]">
        <span>
          {total.toLocaleString()} total &middot; Page {page} of {totalPages}
        </span>
        <div className="flex gap-2">
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
  );
}
