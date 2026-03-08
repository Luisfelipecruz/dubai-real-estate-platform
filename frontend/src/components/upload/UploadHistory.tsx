"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { UploadLogEntry } from "@/lib/types";

interface UploadHistoryProps {
  refreshKey: number;
}

const DATASET_LABELS: Record<string, string> = {
  transactions: "Transactions",
  rents: "Rent Contracts",
  valuations: "Valuations",
};

export default function UploadHistory({ refreshKey }: UploadHistoryProps) {
  const [uploads, setUploads] = useState<UploadLogEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    apiFetch<UploadLogEntry[]>("/uploads?limit=20")
      .then(setUploads)
      .catch(() => setUploads([]))
      .finally(() => setLoading(false));
  }, [refreshKey]);

  if (loading) {
    return (
      <div className="mt-8 text-center text-sm text-gray-500">
        Loading upload history...
      </div>
    );
  }

  if (uploads.length === 0) {
    return (
      <div className="mt-8 rounded-xl border border-gray-200 bg-white p-8 text-center">
        <p className="text-sm text-gray-500">No uploads yet</p>
      </div>
    );
  }

  return (
    <div className="mt-8">
      <h2 className="text-lg font-semibold text-gray-900">Upload History</h2>
      <div className="mt-3 overflow-x-auto rounded-xl border border-gray-200 bg-white">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
              <th className="px-4 py-3">Dataset</th>
              <th className="px-4 py-3">Filename</th>
              <th className="px-4 py-3">Date</th>
              <th className="px-4 py-3 text-right">Received</th>
              <th className="px-4 py-3 text-right">Inserted</th>
              <th className="px-4 py-3 text-right">Duplicates</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {uploads.map((u) => (
              <tr key={u.id} className="hover:bg-gray-50">
                <td className="whitespace-nowrap px-4 py-3 font-medium">
                  {DATASET_LABELS[u.dataset_type] || u.dataset_type}
                </td>
                <td className="max-w-[200px] truncate px-4 py-3 text-gray-600">
                  {u.filename}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-gray-500">
                  {u.uploaded_at
                    ? new Date(u.uploaded_at).toLocaleDateString("en-US", {
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })
                    : "—"}
                </td>
                <td className="px-4 py-3 text-right tabular-nums">
                  {u.rows_received?.toLocaleString() ?? "—"}
                </td>
                <td className="px-4 py-3 text-right tabular-nums font-medium text-green-700">
                  {u.rows_inserted?.toLocaleString() ?? "—"}
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-gray-500">
                  {u.rows_duplicate?.toLocaleString() ?? "—"}
                </td>
                <td className="whitespace-nowrap px-4 py-3">
                  <StatusBadge status={u.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string | null }) {
  const styles =
    status === "success"
      ? "bg-green-100 text-green-800"
      : status === "failed"
        ? "bg-red-100 text-red-800"
        : "bg-yellow-100 text-yellow-800";

  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${styles}`}
    >
      {status || "unknown"}
    </span>
  );
}
