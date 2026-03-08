from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from database import engine
from routers.upload import router as upload_router
from routers.transactions import router as transactions_router
from routers.rents import router as rents_router
from routers.valuations import router as valuations_router
from routers.areas import router as areas_router
from routers.quality import router as quality_router

app = FastAPI(
    title="Dubai Real Estate Market Intelligence",
    description="API for querying Dubai Land Department transactions, rent contracts, and valuations.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload_router)
app.include_router(transactions_router)
app.include_router(rents_router)
app.include_router(valuations_router)
app.include_router(areas_router)
app.include_router(quality_router)


@app.get("/health")
async def health():
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/stats")
async def stats():
    """Return row counts for all datasets."""
    queries = {
        "transactions": "SELECT COUNT(*) FROM raw_transactions",
        "rents": "SELECT COUNT(*) FROM raw_rent_contracts",
        "valuations": "SELECT COUNT(*) FROM raw_valuations",
        "uploads": "SELECT COUNT(*) FROM upload_log",
    }
    result = {}
    async with engine.connect() as conn:
        for key, query in queries.items():
            row = await conn.execute(text(query))
            result[key] = row.scalar()
    return result
