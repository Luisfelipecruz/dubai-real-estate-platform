"use client";

import { useState } from "react";
import Link from "next/link";
import FileDropzone from "@/components/upload/FileDropzone";
import UploadResult from "@/components/upload/UploadResult";
import UploadHistory from "@/components/upload/UploadHistory";
import { apiUpload } from "@/lib/api";
import type { UploadResponse } from "@/lib/types";

export default function UploadPage() {
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  async function handleFile(file: File) {
    setUploading(true);
    setResult(null);
    setError(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const data = await apiUpload<UploadResponse>("/upload", formData);
      setResult(data);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-12">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Upload CSV</h1>
          <p className="mt-1 text-sm text-gray-600">
            Upload a DLD CSV file. The system auto-detects the dataset type and
            deduplicates records.
          </p>
        </div>
        <Link
          href="/"
          className="text-sm text-blue-600 hover:text-blue-800"
        >
          Back to dashboard
        </Link>
      </div>

      <div className="mt-6">
        <FileDropzone onFileSelected={handleFile} disabled={uploading} />
      </div>

      {uploading && (
        <div className="mt-4 flex items-center gap-2 text-sm text-gray-600">
          <svg
            className="h-4 w-4 animate-spin"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
          Processing...
        </div>
      )}

      {error && (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-4">
          <UploadResult result={result} onDismiss={() => setResult(null)} />
        </div>
      )}

      <UploadHistory refreshKey={refreshKey} />
    </main>
  );
}
