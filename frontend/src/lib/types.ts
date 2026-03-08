export interface UploadResponse {
  dataset_type: string;
  filename: string;
  rows_received: number;
  rows_inserted: number;
  rows_duplicate: number;
  rows_rejected: number;
  status: string;
  error?: string;
}

export interface UploadLogEntry {
  id: number;
  dataset_type: string;
  filename: string | null;
  uploaded_at: string | null;
  rows_received: number | null;
  rows_inserted: number | null;
  rows_duplicate: number | null;
  rows_rejected: number | null;
  status: string | null;
}
