"""Where the expected answer comes from, and why it is a query rather than a number.

THE R-05 PROBLEM, STATED PROPERLY
----------------------------------
On 2026-08-29 the agent answered "AED 550,010" for a typical Dubai Marina apartment rent.
It routed perfectly — resolved the name, called SQL, never touched the corpus — and the
routing eval passed it, correctly, because route grading cannot see a value. The true
per-property median is AED 120,000. `area_summary` had exposed `AVG(annual_amount)`, the
CONTRACT total, on an area where one contract covers up to 232 properties.

The obvious fix is to write 120000 into a fixture. That fix is wrong twice over.

It goes stale. The number is a property of 358,008 rows that a reload changes. A fixture
full of literals is a fixture that fails for the wrong reason six months from now, and
the standard repair — re-baseline it to whatever the system currently says — is the m13a
G-03 mistake, which this repository has already paid for once.

And it is circular if the literal was ever produced by the code under test. The whole
claim of the routing work is that SQL is EXACT. An eval whose expected value came from
calling the tool proves only that the tool is consistent with itself.

So a fixture records a **hand-written query against the raw tables**, and the harness
runs it at grade time. `services/market.py` is deliberately not imported here: it is the
thing being graded, and an independent check that shares an implementation with its
subject is not independent. If the two disagree, that disagreement is the finding.

READ-ONLY, ENFORCED TWICE
--------------------------
The fixture is trusted — it is a file in this repository, reviewed like any other — but
it is also *data that this module executes*, and the honest way to hold that is to make
the trust explicit and cheap rather than implicit and total. Every statement is checked
to be a single SELECT or WITH, and it runs inside `SET TRANSACTION READ ONLY`, so a
mistake in a fixture cannot write to the database that the rest of the suite depends on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["GroundTruth", "check_sql_is_readonly", "resolve_scalar", "resolve_set"]

# A statement may end with one optional semicolon and contain none inside it. This is a
# guard against a fixture typo, not a defence against a hostile fixture: anyone who can
# edit eval/golden/ can edit this file. It costs one regex and it means a stray
# `; DELETE FROM raw_transactions` in a YAML block is a loud error instead of 200,001
# missing rows.
_LEADING = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_TRAILING_SEMICOLON = re.compile(r";\s*$")


class UnsafeFixtureSQL(ValueError):
    """A ground-truth query that is not a single read-only statement."""


def check_sql_is_readonly(sql: str) -> str:
    """Return `sql` stripped of a trailing semicolon, or raise.

    Raising is right rather than skipping. A fixture whose query cannot run is a fixture
    that grades nothing, and a harness that quietly drops it reports a smaller denominator
    and a healthier-looking pass rate — the exact shape of the m15 refusal-detector bug,
    where a broken check read as a clean result.
    """
    if not sql or not sql.strip():
        raise UnsafeFixtureSQL("empty ground-truth SQL")
    body = _TRAILING_SEMICOLON.sub("", sql.strip())
    if ";" in body:
        raise UnsafeFixtureSQL(
            "ground-truth SQL must be a single statement; found an inner ';'"
        )
    if not _LEADING.match(body):
        raise UnsafeFixtureSQL(
            f"ground-truth SQL must begin with SELECT or WITH, got {body.split()[0]!r}"
        )
    return body


@dataclass(frozen=True)
class GroundTruth:
    """One expected value, and the query that produced it.

    `sql` travels with `value` on purpose. Every number this harness prints can be
    re-derived by pasting one line into psql, which is the difference between a result
    and an assertion.
    """

    value: Decimal | None
    sql: str
    rows: int


async def resolve_scalar(session: AsyncSession, sql: str) -> GroundTruth:
    """Run a fixture query expected to return exactly one value."""
    body = check_sql_is_readonly(sql)
    await session.execute(text("SET TRANSACTION READ ONLY"))
    result = await session.execute(text(body))
    rows = result.fetchall()
    if not rows:
        return GroundTruth(None, body, 0)
    if len(rows) > 1 or len(rows[0]) > 1:
        raise UnsafeFixtureSQL(
            f"expected one value, got {len(rows)} row(s) x {len(rows[0])} column(s). "
            f"Use expect_set for a question whose answer is a list."
        )
    raw = rows[0][0]
    return GroundTruth(None if raw is None else Decimal(str(raw)), body, 1)


async def resolve_set(session: AsyncSession, sql: str) -> tuple[list[str], str]:
    """Run a fixture query expected to return one column of names.

    Used by the spatial questions, where the answer is a set of communities rather than a
    quantity. An empty set is a legitimate result and is returned as one — Palm Jumeirah
    is an artificial island and borders nothing, and m15 spent two fixes learning that a
    zero-length list is an answer rather than a failure.
    """
    body = check_sql_is_readonly(sql)
    await session.execute(text("SET TRANSACTION READ ONLY"))
    result = await session.execute(text(body))
    rows = result.fetchall()
    if rows and len(rows[0]) > 1:
        raise UnsafeFixtureSQL(
            f"expect_set queries must return ONE column, got {len(rows[0])}"
        )
    return [str(row[0]) for row in rows if row[0] is not None], body
