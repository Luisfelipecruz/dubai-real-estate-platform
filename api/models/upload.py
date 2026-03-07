from pydantic import BaseModel
from datetime import datetime


class UploadResponse(BaseModel):
    dataset_type: str
    filename: str
    rows_received: int
    rows_inserted: int
    rows_duplicate: int
    rows_rejected: int
    status: str
    error: str | None = None


class UploadLogEntry(BaseModel):
    id: int
    dataset_type: str
    filename: str | None
    uploaded_at: datetime | None
    rows_received: int | None
    rows_inserted: int | None
    rows_duplicate: int | None
    rows_rejected: int | None
    status: str | None
