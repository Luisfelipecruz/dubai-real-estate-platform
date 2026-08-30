import os
import sys

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Ensure the api directory is on sys.path so imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# `main` and `database` are imported INSIDE the fixture, not at module scope.
#
# m16 claims that its grader tests need no database, no model and no network, and
# `.github/workflows/eval.yml` runs them on a bare runner with five packages installed to
# prove it. That claim was false at the import level and the workflow failed before a
# single test ran: conftest is loaded for every collection, `from main import app` pulls
# in the whole FastAPI application, and the job died on `No module named 'fastapi'`.
#
# Deferring the import makes the property real rather than asserted. A test that needs the
# app still gets it — the fixture is what needs it — and a test that does not can now run
# without installing it. Found by running the workflow's own commands in a bare container
# instead of trusting that they would work.


@pytest_asyncio.fixture
async def client():
    from database import engine
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()
