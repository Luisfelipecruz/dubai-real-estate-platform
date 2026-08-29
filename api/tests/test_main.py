"""The copilot router registration contract.

`CLAUDE.md` rule 3.2 requires a file touched by several PRs to be added whole in the
first one. `api/main.py` is touched by m13 (search), m14 (ask), m15 (agent) and m17
(voice), so its final form has to work while the modules it names do not all exist. Two
of the four are still unbuilt as of m14, and these tests must not have to be edited when
the third and fourth arrive.

The tolerant loop that resolves it is not a workaround dressed as design -- it is how
the feature has to behave anyway. `LLM_PROVIDER=none` on a machine with 8 GB of RAM
must still serve the map. These tests hold both halves of that contract in place.
"""

from importlib import import_module

import pytest
from fastapi import FastAPI

from main import COPILOT_ROUTERS, app, register_copilot_routers


async def test_health_is_unaffected_by_missing_copilot_modules(client):
    """Copilot routers are still missing -- agent and voice -- and the platform serves
    anyway. That is the whole contract: a missing module is a configuration state."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_every_copilot_router_that_exists_is_registered_and_no_other():
    """The contract, derived from the filesystem rather than from a milestone number.

    This test used to hardcode the inventory -- `/search` present, `/ask`, `/agent/query`
    and `/voice/stream` absent -- and m14 broke it the moment routers/ask.py appeared.
    That is a real problem under this repository's deferred-commit workflow and not just
    an annoyance: commits are held back across several milestones, so the file's content
    at `git add` time is what the EARLIER commit ships. A test that names today's routers
    is therefore wrong in one direction or the other no matter which version gets staged.

    Deriving the expectation from what is importable fixes that permanently. In a clean
    checkout of m13 there is no routers/ask.py, so this asserts /ask is absent; in the
    m14 working tree there is one, so it asserts /ask is present. Same file, both true,
    and m15 and m17 will not have to touch it either.

    Read from the OpenAPI schema rather than app.routes: the schema is the contract the
    frontend and the m15 tool layer consume, and its shape does not change with the
    FastAPI version the way the internal route objects do.
    """
    paths = set(app.openapi()["paths"])
    assert "/stats" in paths, "core operations must survive the copilot loop"

    for name in COPILOT_ROUTERS:
        try:
            module = import_module(f"routers.{name}")
        except ModuleNotFoundError as exc:
            if exc.name != f"routers.{name}":
                raise
            # Not built yet. Nothing it would have registered may be present, and the
            # only way to know what that is, is to know it is nothing.
            continue
        declared = {route.path for route in module.router.routes}
        assert declared, f"routers/{name}.py declares no routes"
        missing = declared - paths
        assert not missing, (
            f"routers/{name}.py exists but {sorted(missing)} is not registered -- "
            f"the tolerant loop swallowed something it should not have"
        )


def test_absent_router_module_is_skipped():
    def importer(name):
        raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    registered = register_copilot_routers(FastAPI(), names=("ask",), importer=importer)
    assert registered == []


def test_router_that_exists_but_fails_to_import_is_not_swallowed():
    """The narrow `exc.name` check earns its place here.

    A blanket `except ModuleNotFoundError` would also swallow routers/search.py failing
    because httpx is missing. The endpoint would then be absent with no explanation in
    any log -- a far worse failure than a crash at startup, because nothing points at
    the cause.
    """

    def importer(name):
        raise ModuleNotFoundError("No module named 'httpx'", name="httpx")

    with pytest.raises(ModuleNotFoundError, match="httpx"):
        register_copilot_routers(FastAPI(), names=("search",), importer=importer)


def test_registration_list_is_the_full_planned_set():
    """Guards the rule-3.2 decision itself: if a later PR adds its router by editing
    main.py instead of adding a module, this test is the thing that notices."""
    assert COPILOT_ROUTERS == ("search", "ask", "agent", "voice")
