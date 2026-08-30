"""Area endpoints. The SQL moved to `services/market.py` in m15; the HTTP did not.

These routes used to hold their queries inline, which was correct while a route was the
only caller. The agent tool layer is a second caller, and two callers running two copies
of "how many transactions are in this area" is how a platform ends up stating two
different exact numbers for one question. `services/market.py` explains the split.

The response bodies are unchanged. This is a refactor, and a refactor that alters a
number is not a refactor.
"""

from fastapi import APIRouter, HTTPException, Query

from database import engine
from models.area import AreaHistory, AreaOverview, AreaSummary
from services import market

router = APIRouter()


@router.get("/areas", response_model=list[AreaOverview])
async def list_areas():
    """Unique areas across all datasets with counts and averages.

    One row per area NAME, not per `(area_id, area_name_en)` pair -- `Mushrif` exists
    under two `area_id`s and emitted duplicate rows that React rejected as a duplicate
    key. See `services.market.list_areas` for the full reasoning.
    """
    async with engine.connect() as conn:
        return await market.list_areas(conn)


@router.get("/areas/{area_name}/history", response_model=AreaHistory)
async def area_history(area_name: str, from_year: int = Query(2008, ge=1990, le=2100)):
    """Yearly sale and rent history for one area.

    Medians rather than means, rent divided by `no_of_prop`, and partial periods flagged
    rather than hidden. Each of those is a measured decision; `services.market.area_history`
    records why.
    """
    async with engine.connect() as conn:
        return await market.area_history(conn, area_name, from_year)


@router.get("/areas/{area_name}/summary", response_model=AreaSummary)
async def area_summary(area_name: str):
    """Cross-dataset stats for a single area.

    Case- and whitespace-insensitive: the transaction CSV has `Al Manara` where the
    community polygons have `AL MANARA`, and an exact match returned 200 with every count
    zero -- indistinguishable from an area with no data.

    Still cannot tell "area exists, no data" from "no such area". `GET /areas/resolve`
    is what closes that gap.
    """
    async with engine.connect() as conn:
        return await market.area_summary(conn, area_name)


@router.get("/areas/resolve")
async def resolve_area(
    name: str = Query(..., min_length=1, max_length=200, description="Name to resolve."),
):
    """Turn a name a human would use into the name the DLD data actually contains.

    Added in m15 because the agent needed it and the API was missing it. The single most
    likely question this platform will ever be asked is about **Dubai Marina**, which
    does not exist in the transaction data -- the DLD files it as `Marsa Dubai`. Before
    this endpoint the honest answer to "how many transactions in Dubai Marina" was a
    confident zero.

    Three strategies in order -- exact, master-project alias, then fuzzy -- and fuzzy is
    last because it is measurably poor at this: `Marsa Dubai` scores 0.37 for "Dubai
    Marina" while a wrong answer scores 0.34. Below the floor, `resolved` is null and the
    candidates are returned rather than a guess.
    """
    async with engine.connect() as conn:
        match = await market.resolve_area_name(conn, name)
    return {
        "requested": match.requested,
        "resolved": match.resolved,
        "method": match.method,
        "confidence": match.confidence,
        "candidates": match.candidates,
    }


@router.get("/areas/{area_name}/neighbors")
async def area_neighbors(
    area_name: str,
    predicate: str = Query("touches", pattern="^(touches|intersects|overlaps)$"),
):
    """Which communities border this area, keyed by NAME rather than by polygon id.

    `GET /communities/{id}/neighbors` is the same query keyed by the polygon's integer
    id, which is right for a REST resource and unusable as a tool signature. Only 106 of
    the 222 community polygons match a transaction area name, so a 404 here is a real and
    frequent outcome rather than an error.
    """
    async with engine.connect() as conn:
        result, candidates = await market.community_neighbors_by_name(
            conn, area_name, predicate
        )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"no boundary polygon is named {area_name!r}. Only 106 of "
                f"the 222 polygons match a transaction area name, and the boundary "
                f"table uses its own vocabulary -- Palm Jumeirah is 'NAKHLAT JUMEIRA'.",
                "candidates": candidates,
            },
        )
    return result
