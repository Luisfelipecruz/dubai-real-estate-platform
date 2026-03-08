"""Quality check results endpoint."""

from fastapi import APIRouter
from sqlalchemy import text

from database import engine

router = APIRouter()


@router.get("/quality")
async def get_quality_results():
    """Return the latest quality check results grouped by run."""
    async with engine.connect() as conn:
        # Get the latest run_id
        result = await conn.execute(text(
            "SELECT run_id FROM quality_checks ORDER BY checked_at DESC LIMIT 1"
        ))
        row = result.first()
        if not row:
            return {"run_id": None, "checks": [], "summary": {"pass": 0, "fail": 0, "warn": 0}}

        run_id = row[0]

        # Get all checks for that run
        result = await conn.execute(text(
            """SELECT check_name, category, dataset, status, message, value, threshold, checked_at
               FROM quality_checks
               WHERE run_id = :run_id
               ORDER BY category, check_name"""
        ), {"run_id": run_id})

        checks = []
        summary = {"pass": 0, "fail": 0, "warn": 0}
        for r in result:
            status = r[3]
            summary[status] = summary.get(status, 0) + 1
            checks.append({
                "check_name": r[0],
                "category": r[1],
                "dataset": r[2],
                "status": status,
                "message": r[4],
                "value": float(r[5]) if r[5] is not None else None,
                "threshold": float(r[6]) if r[6] is not None else None,
                "checked_at": r[7].isoformat() if r[7] else None,
            })

        return {"run_id": run_id, "checks": checks, "summary": summary}
