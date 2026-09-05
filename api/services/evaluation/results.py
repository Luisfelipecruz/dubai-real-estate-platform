"""Storing an evaluation result, and reading it back as a claim with an expiry date.

WHAT THIS MODULE IS FOR
-----------------------
`eval/thresholds.yaml` is a set of floors, each carrying the argument for its number.
`scripts/run_eval.py` produces the measurements those floors are compared against. This
joins the two, and adds the part a terminal cannot have: WHEN the measurement was made and
WHAT IT WAS MADE AGAINST.

WHY STALENESS IS COMPUTED FROM THE TOOL REGISTRY AND NOT FROM A CLOCK
---------------------------------------------------------------------
A score with an age attached is not yet an honest number. Two hours old and one commit
behind is worse than two weeks old and unchanged, and reporting only the age invites the
reader to apply the wrong rule.

What actually invalidates a score is the system underneath it changing. The sharpest case
is a tool being added: a new tool can answer questions the agent previously declined, so
every rate derived from those questions moves -- while the recorded score, and its
timestamp, say nothing at all.

So the registry is fingerprinted into every stored result and compared with the live one
on every read. `added_since` and `removed_since` name the tools, because "stale" is a
verdict and the names are the evidence for it.

THREE STATES, NOT TWO
---------------------
A run may not measure every metric a floor names: an agent-only run produces nothing under
`retrieval.`. Rendering that as a failure is wrong and rendering it as a pass is worse, so
`assess` returns `ok`, `fail` or `not_measured` per floor. The middle state is the one that
gets silently absorbed into whichever neighbour is more convenient, which is exactly why it
is represented explicitly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

__all__ = [
    "EvalResultsUnavailable",
    "assess",
    "latest",
    "load_thresholds",
    "record",
    "thresholds_path",
]

MIGRATION_REMEDY = (
    "eval_results does not exist -- run `docker compose exec api alembic upgrade head` "
    "(migration 0006)."
)


class EvalResultsUnavailable(RuntimeError):
    """The table is not there. Carries the command that creates it."""

    def __init__(self, remedy: str = MIGRATION_REMEDY):
        super().__init__(remedy)
        self.remedy = remedy


def thresholds_path() -> Path | None:
    """`/app/eval` in the container, `<repo>/eval` from a checkout -- or neither.

    Returns None when the file is absent, rather than raising. An endpoint with no
    thresholds file is a deployment where `eval/` was not mounted, which is a legitimate
    configuration -- the copilot routers are optional feature modules -- so it reports the
    absence instead of failing the request.

    Note that the test suite makes the opposite choice for the same lookup and refuses to
    skip when a fixture is missing: a test with no fixture is a test that cannot fail.
    """
    here = Path(__file__).resolve()
    for parents in (2, 3):
        candidate = here.parents[parents] / "eval" / "thresholds.yaml"
        if candidate.is_file():
            return candidate
    return None


def load_thresholds() -> dict[str, Any]:
    """The floors and targets, or empty dicts when `eval/` is not mounted."""
    path = thresholds_path()
    if path is None:
        return {"floors": {}, "targets": {}, "recorded": None, "available": False}
    parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "floors": parsed.get("floors") or {},
        "targets": parsed.get("targets") or {},
        "recorded": parsed.get("recorded"),
        "measured_against": parsed.get("measured_against"),
        "available": True,
    }


async def record(
    conn: Any,
    *,
    recorded_at: datetime,
    suite: str,
    provider: str | None,
    duration_s: int,
    gate_applied: bool,
    gate_passed: bool | None,
    metrics: dict[str, Any],
    context: dict[str, Any],
) -> int:
    """Insert one run's result. Returns its id.

    Takes an open connection and does not commit: the caller owns the transaction, so a
    caller can write this row alongside whatever else it is doing in the same one.
    """
    result = await conn.execute(
        text(
            """
            INSERT INTO eval_results (
                recorded_at, suite, provider, duration_s,
                gate_applied, gate_passed, metrics, context
            ) VALUES (
                :recorded_at, :suite, :provider, :duration_s,
                :gate_applied, :gate_passed, CAST(:metrics AS jsonb),
                CAST(:context AS jsonb)
            )
            RETURNING id
            """
        ),
        {
            "recorded_at": recorded_at,
            "suite": suite,
            "provider": provider,
            "duration_s": duration_s,
            "gate_applied": gate_applied,
            "gate_passed": gate_passed,
            "metrics": json.dumps(metrics, default=str),
            "context": json.dumps(context, default=str),
        },
    )
    return int(result.scalar_one())


async def latest(conn: Any, suite: str | None = None) -> dict[str, Any] | None:
    """The most recent stored result, or None when nothing has been recorded.

    None is a legitimate answer and not an error: a deployment that has never run the
    suite is the normal state of a fresh checkout, and it must not be reported as a
    failure of the endpoint.
    """
    clause = "WHERE suite = :suite" if suite else ""
    try:
        row = (
            await conn.execute(
                text(
                    f"""
                    SELECT id, recorded_at, suite, provider, duration_s,
                           gate_applied, gate_passed, metrics, context
                    FROM eval_results
                    {clause}
                    ORDER BY recorded_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {"suite": suite} if suite else {},
            )
        ).mappings().first()
    except SQLAlchemyError as exc:  # pragma: no cover - exercised by the router test
        raise EvalResultsUnavailable() from exc
    return dict(row) if row else None


def _flatten(metrics: dict[str, Any]) -> dict[str, float]:
    """{"agent": {"route_accuracy": 0.9}} -> {"agent.route_accuracy": 0.9}.

    The key shape the floors are written in, partitioned on the first dot. Values that
    are not numbers are skipped rather than coerced -- a run summary can carry lists and
    strings alongside its rates, and none of those has any business being compared against
    a floor. Booleans are excluded too, since `True >= 0.77` is true in Python and a floor
    satisfied by a type is not a floor.
    """
    flat: dict[str, float] = {}
    for section, values in (metrics or {}).items():
        if not isinstance(values, dict):
            continue
        for metric, value in values.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                flat[f"{section}.{metric}"] = float(value)
    return flat


def _staleness(recorded_tools: list[str] | None, live_tools: list[str] | None) -> dict:
    """What changed in the tool registry since the score was measured.

    `unknown` when either side is missing, and unknown is NOT the same as fresh. A result
    recorded before this fingerprint existed cannot support a claim about drift in either
    direction, and saying so is the only correct output.
    """
    if recorded_tools is None or live_tools is None:
        return {
            "known": False,
            "stale": None,
            "measured_against": recorded_tools,
            "registered_now": live_tools,
            "added_since": [],
            "removed_since": [],
        }
    was, now = set(recorded_tools), set(live_tools)
    added, removed = sorted(now - was), sorted(was - now)
    return {
        "known": True,
        "stale": bool(added or removed),
        "measured_against": sorted(was),
        "registered_now": sorted(now),
        "added_since": added,
        "removed_since": removed,
    }


def assess(
    row: dict[str, Any] | None,
    thresholds: dict[str, Any],
    live_tools: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Join a stored result to the floors, and say what it can and cannot support.

    Pure: no database, and no clock unless one is passed. Every number the endpoint
    returns is computed here rather than in the client, so each one can be asserted
    directly in a test.
    """
    floors = thresholds.get("floors") or {}
    targets = thresholds.get("targets") or {}

    if row is None:
        return {
            "available": False,
            "reason": (
                "No eval run has been recorded. Run `make eval`, which grades the three "
                "golden fixtures and records the result."
            ),
            "thresholds_available": bool(thresholds.get("available")),
            "floors": [
                {"key": key, "floor": floor, "actual": None, "state": "not_measured"}
                for key, floor in sorted(floors.items())
            ],
            "targets": targets,
        }

    measured = _flatten(row.get("metrics") or {})
    context = row.get("context") or {}

    checks = []
    for key, floor in sorted(floors.items()):
        actual = measured.get(key)
        if actual is None:
            checks.append(
                {"key": key, "floor": floor, "actual": None, "state": "not_measured"}
            )
            continue
        checks.append(
            {
                "key": key,
                "floor": floor,
                "actual": actual,
                "margin": round(actual - float(floor), 6),
                "state": "ok" if actual >= float(floor) else "fail",
            }
        )

    recorded_at = row["recorded_at"]
    reference = now or datetime.now(UTC)
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=UTC)

    failing = [c for c in checks if c["state"] == "fail"]
    unmeasured = [c for c in checks if c["state"] == "not_measured"]

    return {
        "available": True,
        "id": row["id"],
        "recorded_at": recorded_at,
        "age_seconds": int((reference - recorded_at).total_seconds()),
        "suite": row["suite"],
        "provider": row.get("provider"),
        "duration_s": row.get("duration_s"),
        "gate_applied": row.get("gate_applied"),
        "gate_passed": row.get("gate_passed"),
        "thresholds_available": bool(thresholds.get("available")),
        "thresholds_recorded": thresholds.get("recorded"),
        "floors": checks,
        "targets": targets,
        "summary": {
            "checked": len(checks),
            "ok": len(checks) - len(failing) - len(unmeasured),
            "failing": len(failing),
            "not_measured": len(unmeasured),
        },
        "metrics": measured,
        "fixtures": context.get("fixtures"),
        "counts": context.get("counts"),
        "registry": _staleness(context.get("tools"), live_tools),
        "caveat": context.get("caveat"),
    }
