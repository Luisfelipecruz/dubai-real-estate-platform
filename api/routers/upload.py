from fastapi import APIRouter, UploadFile, HTTPException
from sqlalchemy import text

from database import engine
from models.upload import UploadResponse, UploadLogEntry
from services.ingestion_service import ingest_csv

router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload_csv(file: UploadFile):
    """Upload a DLD CSV file. Auto-detects dataset type and deduplicates."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=422, detail="File must be a CSV")

    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=422, detail="File is empty")

    result = await ingest_csv(contents, file.filename)

    if result["status"] == "failed":
        raise HTTPException(status_code=422, detail=result.get("error", "Ingestion failed"))

    return UploadResponse(**result)


@router.get("/uploads", response_model=list[UploadLogEntry])
async def list_uploads(limit: int = 50, offset: int = 0):
    """Return upload history from upload_log table."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, dataset_type, filename, uploaded_at, "
                "rows_received, rows_inserted, rows_duplicate, rows_rejected, status "
                "FROM upload_log ORDER BY id DESC LIMIT :limit OFFSET :offset"
            ),
            {"limit": limit, "offset": offset},
        )
        rows = result.fetchall()

    return [
        UploadLogEntry(
            id=r[0],
            dataset_type=r[1],
            filename=r[2],
            uploaded_at=r[3],
            rows_received=r[4],
            rows_inserted=r[5],
            rows_duplicate=r[6],
            rows_rejected=r[7],
            status=r[8],
        )
        for r in rows
    ]
