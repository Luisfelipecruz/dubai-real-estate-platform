"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface FilterField {
  key: string;
  label: string;
  type: "text" | "select" | "date" | "number";
  placeholder?: string;
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
}

interface FilterPanelProps {
  fields: FilterField[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
  onReset: () => void;
}

export default function FilterPanel({
  fields,
  values,
  onChange,
  onReset,
}: FilterPanelProps) {
  const [expanded, setExpanded] = useState(false);

  const activeCount = Object.values(values).filter((v) => v !== "").length;

  const inputClass =
    "h-9 w-full rounded-lg border border-[--border] bg-[--background] px-3 text-sm text-[--foreground] placeholder:text-[--muted-foreground] focus:border-[--ring] focus:outline-none focus:ring-2 focus:ring-[--ring]/30";

  const selectClass =
    "h-9 w-full rounded-lg border border-[--border] bg-[--background] px-3 text-sm text-[--foreground] focus:border-[--ring] focus:outline-none focus:ring-2 focus:ring-[--ring]/30";

  return (
    <div
      className="rounded-lg border"
      style={{ borderColor: "var(--border)", backgroundColor: "var(--background)" }}
    >
      <button
        onClick={() => setExpanded((e) => !e)}
        className="flex w-full items-center justify-between px-4 py-2.5 text-sm font-medium transition-colors hover:bg-[--muted]/30"
        style={{ color: "var(--foreground)" }}
      >
        <span className="flex items-center gap-2">
          Filters
          {activeCount > 0 && (
            <span
              className="inline-flex items-center justify-center rounded-full px-1.5 py-0.5 text-[10px] font-bold leading-none"
              style={{
                backgroundColor: "var(--primary)",
                color: "var(--primary-foreground)",
              }}
            >
              {activeCount}
            </span>
          )}
        </span>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-[--muted-foreground]" />
        ) : (
          <ChevronDown className="h-4 w-4 text-[--muted-foreground]" />
        )}
      </button>

      {expanded && (
        <div
          className="border-t px-4 pb-4 pt-3"
          style={{ borderColor: "var(--border)" }}
        >
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {fields.map((field) => (
              <div key={field.key}>
                <label
                  className="mb-1 block text-xs font-medium"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  {field.label}
                </label>
                {field.type === "select" ? (
                  <select
                    value={values[field.key] ?? ""}
                    onChange={(e) => onChange(field.key, e.target.value)}
                    className={selectClass}
                  >
                    {field.options?.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={field.type}
                    placeholder={field.placeholder}
                    value={values[field.key] ?? ""}
                    onChange={(e) => onChange(field.key, e.target.value)}
                    min={field.min}
                    max={field.max}
                    className={inputClass}
                  />
                )}
              </div>
            ))}
          </div>

          {activeCount > 0 && (
            <div className="mt-3 flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                onClick={onReset}
                className="text-xs"
              >
                <RotateCcw className="mr-1 h-3 w-3" />
                Clear filters
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
