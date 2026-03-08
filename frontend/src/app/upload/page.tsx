"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, Loader2 } from "lucide-react";
import FileDropzone from "@/components/upload/FileDropzone";
import UploadResult from "@/components/upload/UploadResult";
import UploadHistory from "@/components/upload/UploadHistory";
import { apiUpload } from "@/lib/api";
import type { UploadResponse } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

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
    <div className="px-4 py-8 md:px-8 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" asChild>
          <Link href="/">
            <ArrowLeft className="h-4 w-4" />
            Dashboard
          </Link>
        </Button>
      </div>

      <div>
        <p className="text-sm text-[--muted-foreground]">
          Upload a DLD CSV file. The system auto-detects the dataset type and deduplicates records.
        </p>
      </div>

      {/* Dropzone */}
      <Card>
        <CardContent className="p-6">
          <FileDropzone onFileSelected={handleFile} disabled={uploading} />
        </CardContent>
      </Card>

      {/* Upload state */}
      {uploading && (
        <div className="flex items-center gap-2 text-sm text-[--muted-foreground]">
          <Loader2 className="h-4 w-4 animate-spin" />
          Processing file...
        </div>
      )}

      {error && (
        <Card className="border-[--destructive]/40 bg-[--destructive]/5">
          <CardContent className="flex items-start gap-3 py-4">
            <Badge variant="destructive" className="shrink-0 mt-0.5">Error</Badge>
            <p className="text-sm text-[--destructive]">{error}</p>
          </CardContent>
        </Card>
      )}

      {result && (
        <UploadResult result={result} onDismiss={() => setResult(null)} />
      )}

      <UploadHistory refreshKey={refreshKey} />
    </div>
  );
}
