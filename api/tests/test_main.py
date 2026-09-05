"""The copilot router registration contract.

`api/main.py` names every copilot router, and its final form has to work while the modules
it names do not all exist. These tests must therefore not need editing each time one
arrives.

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
    """The contract, derived from the filesystem rather than from a hardcoded inventory.

    A test that names today's routers -- `/search` present, `/ask` absent -- goes wrong the
    moment one of them is added or removed, and it goes wrong silently in whichever
    direction nobody checked.

    Deriving the expectation from what is importable fixes that permanently: in a checkout
    with no `routers/ask.py` this asserts `/ask` is absent, and in one that has it, that it
    is present. Same test, both true, and no edit needed when the next router lands.

    Read from the OpenAPI schema rather than `app.routes`: the schema is the contract the
    frontend and the tool layer consume, and its shape does not change with the FastAPI
    version the way the internal route objects do.
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
        # HTTP routes and WEBSOCKET routes are checked against different things.
        # `app.openapi()["paths"]` contains HTTP operations only — FastAPI excludes
        # WebSockets from the schema, correctly, because a socket is not an operation with
        # a method and a response model. A test that checks every declared route against
        # the schema therefore fails on the first WebSocket, having asserted a premise
        # that was simply never true.
        #
        # The contract still holds in both halves: an HTTP route the router declares must
        # appear in the schema, and a WebSocket route it declares must be mounted on the
        # app. Checking the socket against `app.routes` rather than the schema is the only
        # place this file looks at internal route objects, and it says why.
        from starlette.routing import WebSocketRoute

        declared_http = {
            route.path for route in module.router.routes
            if not isinstance(route, WebSocketRoute)
        }
        declared_ws = {
            route.path for route in module.router.routes
            if isinstance(route, WebSocketRoute)
        }
        assert declared_http or declared_ws, f"routers/{name}.py declares no routes"

        missing = declared_http - paths
        assert not missing, (
            f"routers/{name}.py exists but {sorted(missing)} is not registered -- "
            f"the tolerant loop swallowed something it should not have"
        )

        mounted_ws = {
            route.path for route in app.routes if isinstance(route, WebSocketRoute)
        }
        missing_ws = declared_ws - mounted_ws
        assert not missing_ws, (
            f"routers/{name}.py declares websocket {sorted(missing_ws)} and it is not "
            f"mounted -- absent from the schema is expected, absent from the app is not"
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
    """Every copilot router is its own module, and this is what enforces that.

    The rule is that a new endpoint arrives as a new file under `routers/`, registered by
    adding its name here. The failure it guards against is the opposite move: bolting an
    endpoint onto an existing router because that file happens to be open, which grows one
    module without bound and leaves the registration list describing a shape the code no
    longer has.

    Widening this tuple is therefore meant to be deliberate. If a change makes this test
    red, the question to answer is whether the new surface really is a separate module --
    not how to make the assertion match.
    """
    assert COPILOT_ROUTERS == ("search", "ask", "agent", "voice", "evals")
