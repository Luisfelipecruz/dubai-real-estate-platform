"use client";

import type { UploadResponse } from "@/lib/types";

interface UploadResultProps {
  result: UploadResponse;
  onDismiss: () => void;
}

const DATASET_LABELS: Record<string, string> = {
  transactions: "Transactions",
  rents: "Rent Contracts",
  valuations: "Valuations",
};

export default function UploadResult({ result, onDismiss }: UploadResultProps) {
  const isSuccess = result.status === "success";

  return (
    <div
      className={`rounded-xl border p-6 ${
        isSuccess
          ? "border-green-200 bg-green-50"
          : "border-yellow-200 bg-yellow-50"
      }`}
    >
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-semibold text-gray-900">
            {isSuccess ? "Upload successful" : "Upload completed with issues"}
          </h3>
          <p className="mt-1 text-sm text-gray-600">
            Detected:{" "}
            <span className="font-medium">
              {DATASET_LABELS[result.dataset_type] || result.dataset_type}
            </span>
          </p>
        </div>
        <button
          onClick={onDismiss}
          className="text-gray-400 hover:text-gray-600"
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatItem label="Received" value={result.rows_received} />
        <StatItem label="Inserted" value={result.rows_inserted} highlight />
        <StatItem label="Duplicates" value={result.rows_duplicate} />
        <StatItem label="Rejected" value={result.rows_rejected} />
      </div>

      <p className="mt-3 text-xs text-gray-500">
        File: {result.filename}
      </p>
    </div>
  );
}

function StatItem({
  label,
  value,
  highlight,
}: {
  label: string;
  value: number;
  highlight?: boolean;
}) {
  return (
    <div className="rounded-lg bg-white/70 p-3">
      <p className="text-xs text-gray-500">{label}</p>
      <p
        className={`text-lg font-semibold ${
          highlight ? "text-green-700" : "text-gray-900"
        }`}
      >
        {value.toLocaleString()}
      </p>
    </div>
  );
}
