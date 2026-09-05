import logging
from importlib import import_module

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
from routers.map_data import router as map_router
from routers.communities import router as communities_router
from routers.notes import router as notes_router

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
app.include_router(map_router)
app.include_router(communities_router)
app.include_router(notes_router)


# ── Copilot routers ────────────────────────────────────────────────────────
#
# Registered by name rather than by import, and tolerantly.
#
# Each copilot router is an optional feature module, and each depends on a service that
# may not be running: the embeddings container, a local LLM, the speech stack. A missing
# module here is a CONFIGURATION STATE, not an error -- `LLM_PROVIDER=none` on a machine
# with 8 GB of RAM must still serve the map, and the core operations above have no
# dependency on any of this.
#
# The ModuleNotFoundError is narrowed to the router module itself on purpose. A blanket
# except would also swallow `routers.search` failing because httpx is missing, and the
# endpoint would then be absent with no explanation anywhere in the logs -- which is a
# far worse failure than a crash at startup.
logger = logging.getLogger(__name__)

COPILOT_ROUTERS = ("search", "ask", "agent", "voice", "evals")


def register_copilot_routers(application, names=COPILOT_ROUTERS, importer=import_module):
    """Include each copilot router that is present. Returns the names registered.

    A function rather than an inline loop so the two behaviours that matter can be
    asserted directly in api/tests/test_main.py: an absent module is skipped, and a
    module that exists but fails to import is NOT.
    """
    registered = []
    for name in names:
        module_name = f"routers.{name}"
        try:
            application.include_router(importer(module_name).router)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise
            logger.info("copilot router %r not installed - skipping", name)
            continue
        registered.append(name)
    return registered


register_copilot_routers(app)


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
