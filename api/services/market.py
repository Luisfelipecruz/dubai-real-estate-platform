"""The tabular layer: every exact number this platform can state, in one place.

WHY THIS FILE EXISTS, AND WHY IT IS A REFACTOR RATHER THAN A NEW MODULE
-----------------------------------------------------------------------
Until m15 the SQL lived inline in `routers/areas.py` and `routers/communities.py`, which
was fine while a route was the only caller. m15 adds a second caller -- the agent tool
layer -- and the two must not be allowed to drift apart.

That is not a tidiness argument. The entire premise of the routing work is that a
question about transaction volume is a `COUNT(*)` over an indexed column and is therefore
EXACT, unlike the same question answered from retrieved prose. If the agent's
`area_summary` tool ran its own copy of that count and the copy diverged from
`GET /areas/{name}/summary` -- a different `UPPER(TRIM(...))`, a filter that drifted, a
median that quietly became a mean -- then the platform would state two different exact
numbers for one question and the claim would be worthless. One definition, two callers.

So the routers now delegate here and own only their HTTP concerns, and the tool handlers
in `services/agent/tools.py` call the same functions with the same connection.

WHAT DID NOT MOVE
-----------------
`routers/transactions.py` and `routers/rents.py` build their WHERE clause from a dozen
optional query parameters and return paginated ROWS. The agent has no use for a page of
raw rows -- it needs aggregates -- so wrapping them would produce a tool whose result is
too large to put in a context window and too unaggregated to reason about. They stay
where they are.

THE MEDIAN/MEAN SPLIT IS INHERITED, NOT INVENTED
------------------------------------------------
`area_history` uses `PERCENTILE_CONT(0.5)` because Dubai prices are heavily
right-skewed -- one area carries a single 6.75 bn transaction -- while `area_summary`
reports `AVG`. That inconsistency predates this file and is preserved deliberately:
changing what `GET /areas/{name}/summary` returns is an API change, not a refactor, and
a refactor that quietly alters a number is the worst kind. It is recorded in
docs/agent-orchestration.md as a known wart rather than silently fixed here.
"""

import difflib
import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from models.area import (
    AreaDatasetStats,
    AreaHistory,
    AreaHistoryPoint,
    AreaOverview,
    AreaSummary,
)
from models.community import CommunityNeighbor, CommunityNeighborsResponse

# DE-9IM predicates, measured on this dataset: 483 touching pairs, 131 overlapping,
# 614 intersecting -- and 483 + 131 = 614 exactly, because no pair here contains or
# equals another. Kept as a whitelist because the value is interpolated into SQL.
ADJACENCY_PREDICATES = {
    "touches": "ST_Touches",        # boundaries meet, interiors do NOT
    "intersects": "ST_Intersects",  # any shared point at all -- the loosest
    "overlaps": "ST_Overlaps",      # interiors intersect, neither contains the other
}


class UnknownArea(LookupError):
    """No area matched, and these are the closest names that exist.

    Carries the candidates rather than just failing. IMPLEMENTATION-PLAN.md §5.3 lists
    "unknown area name -> fuzzy-match, return candidates" as a recovery path, and a bare
    "not found" gives the agent nothing to recover WITH -- it will either invent a name
    or report zero as a fact.
    """

    def __init__(self, requested: str, candidates: list[str]):
        self.requested = requested
        self.candidates = candidates
        super().__init__(
            f"no area matches {requested!r}. Closest names in the data: "
            + (", ".join(candidates) if candidates else "(none)")
        )


@dataclass(frozen=True)
class AreaMatch:
    """How a caller's name was turned into a name the data actually contains."""

    requested: str
    resolved: str | None
    method: str          # exact | project_alias | fuzzy | none
    confidence: float    # 1.0 exact; the similarity score otherwise
    candidates: list[str]


_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm(value: str) -> str:
    return " ".join(_WORD_RE.findall(value.lower()))


def _similarity(query: str, candidate: str) -> float:
    """Token overlap blended with character similarity.

    Neither alone is enough. Pure character similarity ranks `Al Ttay` above nothing for
    "JLT"; pure token overlap cannot see a typo. The blend catches `Bussiness Bay` ->
    `Business Bay` at 0.58, which is the case fuzzy matching is actually good at.

    It is NOT good at the case that matters most here -- see `resolve_area_name`.
    """
    q, c = _norm(query), _norm(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.95
    q_tokens, c_tokens = set(q.split()), set(c.split())
    jaccard = len(q_tokens & c_tokens) / len(q_tokens | c_tokens)
    sequence = difflib.SequenceMatcher(None, q, c).ratio()
    return 0.6 * jaccard + 0.4 * sequence


# Below this, a "match" is noise. Calibrated against the measurement in the docstring of
# `resolve_area_name`: the correct answer for "Dubai Marina" scores 0.37 and the WRONG
# answer scores 0.34, so any threshold that accepts the right one also accepts the wrong
# one. 0.55 sits above both and below `Bussiness Bay` -> `Business Bay` at 0.58.
FUZZY_FLOOR = 0.55
MAX_CANDIDATES = 5


async def known_area_names(conn: AsyncConnection) -> list[str]:
    """Every area name present in the transaction data. 221 after case normalisation."""
    rows = await conn.execute(
        text("""
            SELECT MIN(area_name_en) AS name
              FROM raw_transactions
             WHERE area_name_en IS NOT NULL
             GROUP BY UPPER(TRIM(area_name_en))
             ORDER BY 1
        """)
    )
    return [r[0] for r in rows]


async def _project_alias(conn: AsyncConnection, name: str) -> tuple[str, int] | None:
    """Resolve a MARKETING name to the DLD area name, from the data itself.

    This is the interesting half of name resolution and it is not fuzzy matching.

    The public names for Dubai's best-known districts are not the names the Land
    Department records them under. `Dubai Marina` is filed as `Marsa Dubai`;
    `Jumeirah Lakes Towers` is `Al Thanyah Fifth`; `Downtown Dubai` is `Burj Khalifa`.
    A user asking about Dubai Marina -- the single most likely question this platform
    will ever be asked -- gets `area_name_en = 'Dubai Marina'` matching nothing, a count
    of zero, and an HTTP 200. Zero and "no such area" are indistinguishable in that
    response, which is the same trap `area_summary`'s docstring already records for case
    sensitivity.

    The mapping is DERIVED rather than hand-written, and that is the point. Every
    transaction carries `master_project_en` alongside `area_name_en`, so the alias table
    is a GROUP BY: the area where a given master project's transactions actually sit.
    A hand-maintained constant would be stale the first time the DLD renames something
    and would encode one developer's knowledge of Dubai geography as fact. This encodes
    the data's own answer, and it stays correct as the data changes.

    Returns (area_name, supporting_transaction_count) or None. The count is returned so
    the caller can say how strong the association was rather than presenting a majority
    vote as a certainty -- `DownTown Dubai` maps to `Burj Khalifa` with 8,185
    transactions but also appears in `Business Bay` with 280.
    """
    row = (
        await conn.execute(
            text("""
                SELECT area_name_en, COUNT(*) AS n
                  FROM raw_transactions
                 WHERE UPPER(TRIM(master_project_en)) = UPPER(TRIM(:name))
                   AND area_name_en IS NOT NULL
                 GROUP BY area_name_en
                 ORDER BY n DESC
                 LIMIT 1
            """),
            {"name": name},
        )
    ).first()
    return (row[0], int(row[1])) if row else None


async def resolve_area_name(conn: AsyncConnection, name: str) -> AreaMatch:
    """Turn a caller's area name into one the data contains. Three strategies, in order.

        exact          the name is already an area name, case- and space-insensitively
        project_alias  it is a MASTER PROJECT name -- see `_project_alias`
        fuzzy          closest area name above FUZZY_FLOOR, else candidates only

    THE ORDER IS LOAD-BEARING AND THE MEASUREMENT SAYS WHY. Fuzzy matching is tried LAST
    because on the case that matters most it is barely better than chance. Scored against
    all 221 area names, "Dubai Marina" ranks `Marsa Dubai` first at **0.37** -- and
    second is `Madinat Dubai Almelaheyah` at **0.34**. The correct answer wins by 0.03,
    on the strength of sharing the word "Dubai", which every third area in the emirate
    also contains. Accepting that would be reporting a coin flip as a resolution.

    "Downtown Dubai" is worse: fuzzy ranks `Marsa Dubai` first, which is wrong. The alias
    path gets it right, from 8,185 transactions that say so.

    So fuzzy is kept for what it is genuinely good at -- typos, `Bussiness Bay` ->
    `Business Bay` at 0.58 -- and everything below FUZZY_FLOOR returns candidates with
    `resolved=None` instead of a guess. A tool that guesses an area name produces a
    confident answer about the wrong place, which is worse than an admission that it does
    not know, because nothing downstream can detect it.
    """
    names = await known_area_names(conn)
    target = _norm(name)

    for candidate in names:
        if _norm(candidate) == target:
            return AreaMatch(name, candidate, "exact", 1.0, [])

    alias = await _project_alias(conn, name)
    if alias is not None:
        resolved, supporting = alias
        return AreaMatch(
            requested=name,
            resolved=resolved,
            method="project_alias",
            # Not 1.0. It is a majority vote over a real column, which is strong evidence
            # and not an identity, and the difference should survive into the response.
            confidence=0.9,
            candidates=[f"{resolved} ({supporting} transactions under this project)"],
        )

    scored = sorted(
        ((c, _similarity(name, c)) for c in names), key=lambda p: -p[1]
    )[:MAX_CANDIDATES]
    best, best_score = scored[0] if scored else (None, 0.0)
    if best is not None and best_score >= FUZZY_FLOOR:
        return AreaMatch(name, best, "fuzzy", round(best_score, 3), [c for c, _ in scored])
    return AreaMatch(name, None, "none", round(best_score, 3), [c for c, _ in scored])


async def require_area(conn: AsyncConnection, name: str) -> AreaMatch:
    """`resolve_area_name`, raising `UnknownArea` when nothing resolved."""
    match = await resolve_area_name(conn, name)
    if match.resolved is None:
        raise UnknownArea(name, match.candidates)
    return match


# ── aggregates ──────────────────────────────────────────────────────────────


async def list_areas(conn: AsyncConnection) -> list[AreaOverview]:
    """Every area with its cross-dataset counts and averages.

    ONE ROW PER AREA NAME, not per `(area_id, area_name_en)` pair. Two things forced it:
    `Mushrif` exists under two different `area_id`s in the DLD data (404 with 33
    transactions and 420 with 1), which emitted two rows with the same name that React
    rejected as a duplicate key and that both linked to the same detail page; and the
    `FULL OUTER JOIN`s match on name while the subqueries grouped by the pair, which is a
    latent fan-out that would become a cartesian product the moment a name carried two
    `area_id`s on both sides.

    Names are normalised with `UPPER(TRIM(...))` before joining because the source data
    is not internally consistent about case -- `Abu Hail`, `Al Baraha`, but `AL Athbah`.
    `area_id` is a representative (`MIN`) and is NOT unique for `Mushrif`; the name is the
    key the rest of the API uses.
    """
    rows = await conn.execute(
        text("""
            WITH t AS (
                SELECT UPPER(TRIM(area_name_en)) AS norm,
                       MIN(area_name_en) AS area_name_en,
                       MIN(area_id)      AS area_id,
                       COUNT(*)          AS cnt,
                       AVG(actual_worth) AS avg_price
                  FROM raw_transactions
                 WHERE area_name_en IS NOT NULL
                 GROUP BY 1
            ), r AS (
                SELECT UPPER(TRIM(area_name_en)) AS norm,
                       MIN(area_name_en)  AS area_name_en,
                       MIN(area_id)       AS area_id,
                       COUNT(*)           AS cnt,
                       AVG(annual_amount) AS avg_amount
                  FROM raw_rent_contracts
                 WHERE area_name_en IS NOT NULL
                 GROUP BY 1
            ), v AS (
                SELECT UPPER(TRIM(area_name_en)) AS norm,
                       MIN(area_name_en) AS area_name_en,
                       MIN(area_id)      AS area_id,
                       COUNT(*)          AS cnt
                  FROM raw_valuations
                 WHERE area_name_en IS NOT NULL
                 GROUP BY 1
            )
            SELECT
                COALESCE(t.area_id, r.area_id, v.area_id) AS area_id,
                COALESCE(t.area_name_en, r.area_name_en, v.area_name_en) AS area_name_en,
                COALESCE(t.cnt, 0) AS transaction_count,
                COALESCE(r.cnt, 0) AS rent_count,
                COALESCE(v.cnt, 0) AS valuation_count,
                t.avg_price AS avg_transaction_price,
                r.avg_amount AS avg_rent_amount
            FROM t
            FULL OUTER JOIN r ON t.norm = r.norm
            FULL OUTER JOIN v ON COALESCE(t.norm, r.norm) = v.norm
            ORDER BY (COALESCE(t.cnt, 0) + COALESCE(r.cnt, 0) + COALESCE(v.cnt, 0)) DESC
        """)
    )
    return [
        AreaOverview(
            area_id=r[0],
            area_name_en=r[1],
            transaction_count=r[2],
            rent_count=r[3],
            valuation_count=r[4],
            avg_transaction_price=round(r[5], 2) if r[5] else None,
            avg_rent_amount=round(r[6], 2) if r[6] else None,
        )
        for r in rows
    ]


async def area_history(
    conn: AsyncConnection, area_name: str, from_year: int = 2008
) -> AreaHistory:
    """Yearly sale and rent history for one area. Three deliberate choices.

    **Median, not mean.** `PERCENTILE_CONT(0.5)` throughout. Dubai property prices are
    heavily right-skewed -- one area carries a single 6.75 bn transaction -- and a mean
    per year would be a chart of outliers.

    **Rent divided by `no_of_prop`.** `annual_amount` is the CONTRACT total, and one
    contract can cover hundreds of properties, each getting its own row carrying the full
    portfolio amount. Charting the raw column shows a market where rent exceeds sale price.

    **Partial periods flagged, not hidden.** The current year is incomplete -- data ends
    mid-February -- so its counts sit far below a full year and read as a market collapse.
    Rather than silently dropping it (which hides the most recent data) or plotting it
    unmarked (which lies), `is_partial` compares the period end against the last date
    actually present.
    """
    rows = await conn.execute(
        text("""
            WITH bounds AS (
                SELECT MAX(instance_date)::date AS last_sale,
                       (SELECT MAX(contract_start_date) FROM raw_rent_contracts) AS last_rent
                  FROM raw_transactions
            ), sales AS (
                SELECT EXTRACT(YEAR FROM instance_date)::int AS yr,
                       COUNT(*) AS n,
                       PERCENTILE_CONT(0.5) WITHIN GROUP (
                           ORDER BY meter_sale_price) FILTER (WHERE meter_sale_price > 0
                       ) AS med_sqm,
                       PERCENTILE_CONT(0.5) WITHIN GROUP (
                           ORDER BY actual_worth) FILTER (WHERE actual_worth > 0
                       ) AS med_price
                  FROM raw_transactions
                 WHERE UPPER(TRIM(area_name_en)) = UPPER(TRIM(:area))
                   AND instance_date IS NOT NULL
                 GROUP BY 1
            ), rents AS (
                SELECT EXTRACT(YEAR FROM contract_start_date)::int AS yr,
                       COUNT(*) AS n,
                       -- per PROPERTY, not per contract; see the docstring
                       PERCENTILE_CONT(0.5) WITHIN GROUP (
                           ORDER BY annual_amount / NULLIF(no_of_prop, 0)
                       ) FILTER (WHERE annual_amount > 0) AS med_rent
                  FROM raw_rent_contracts
                 WHERE UPPER(TRIM(area_name_en)) = UPPER(TRIM(:area))
                   AND contract_start_date IS NOT NULL
                 GROUP BY 1
            )
            SELECT y.yr,
                   COALESCE(s.n, 0), s.med_sqm, s.med_price,
                   COALESCE(r.n, 0), r.med_rent,
                   (make_date(y.yr, 12, 31) > b.last_sale
                    AND make_date(y.yr, 1, 1) <= b.last_sale) AS partial
              FROM (SELECT generate_series(
                        LEAST((SELECT MIN(yr) FROM sales), (SELECT MIN(yr) FROM rents)),
                        (SELECT EXTRACT(YEAR FROM last_sale)::int FROM bounds)
                    ) AS yr) y
              CROSS JOIN bounds b
              LEFT JOIN sales s ON s.yr = y.yr
              LEFT JOIN rents r ON r.yr = y.yr
             WHERE y.yr >= :from_year
             ORDER BY y.yr
        """),
        {"area": area_name, "from_year": from_year},
    )
    points = [
        AreaHistoryPoint(
            period=str(r[0]),
            sale_count=r[1],
            median_price_sqm=round(float(r[2]), 2) if r[2] is not None else None,
            median_price=round(float(r[3]), 2) if r[3] is not None else None,
            rent_count=r[4],
            median_annual_rent=round(float(r[5]), 2) if r[5] is not None else None,
            is_partial=bool(r[6]),
        )
        for r in rows
    ]

    # Is the rent extract a history or a snapshot? Ask the data rather than assume:
    # if every contract was registered inside a single window, it is a snapshot.
    reg = (
        await conn.execute(
            text("""
                SELECT MIN(load_timestamp)::date, MAX(load_timestamp)::date,
                       COUNT(DISTINCT EXTRACT(YEAR FROM load_timestamp))
                  FROM raw_rent_contracts
                 WHERE UPPER(TRIM(area_name_en)) = UPPER(TRIM(:area))
            """),
            {"area": area_name},
        )
    ).first()

    reg_from, reg_to, reg_years = reg or (None, None, 0)
    return AreaHistory(
        area_name_en=area_name,
        interval="year",
        points=points,
        sales_are_historical=True,
        rents_are_historical=bool(reg_years and reg_years > 1),
        rent_registered_from=str(reg_from) if reg_from else None,
        rent_registered_to=str(reg_to) if reg_to else None,
    )


async def area_summary(conn: AsyncConnection, area_name: str) -> AreaSummary:
    """Cross-dataset stats for a single area.

    Matching is case- and whitespace-insensitive on purpose. The two sources spell the
    same place differently: the DLD transaction CSV has `Al Manara`, while the community
    polygons parsed out of Community.kml have `AL MANARA`. An exact match here returned
    HTTP 200 with every count set to 0 -- indistinguishable from a real area that
    genuinely has no transactions -- so the map's boundary layer opened a detail panel
    full of nothing and reported no error anywhere.

    Note this still cannot distinguish "area exists, no data" from "no such area"; both
    are zeros. `resolve_area_name` is what closes that gap, and the agent tool layer calls
    it first for exactly this reason.
    """
    async def stats(sql: str) -> AreaDatasetStats:
        row = (await conn.execute(text(sql), {"area": area_name})).fetchone()
        return AreaDatasetStats(
            count=row[0],
            avg_price=round(row[1], 2) if row[1] else None,
            min_price=round(row[2], 2) if row[2] else None,
            max_price=round(row[3], 2) if row[3] else None,
            avg_area_sqm=round(row[4], 2) if row[4] else None,
        )

    return AreaSummary(
        area_name_en=area_name,
        transactions=await stats("""
            SELECT COUNT(*), AVG(actual_worth), MIN(actual_worth),
                   MAX(actual_worth), AVG(procedure_area)
              FROM raw_transactions
             WHERE UPPER(TRIM(area_name_en)) = UPPER(TRIM(:area))
        """),
        rents=await stats("""
            SELECT COUNT(*), AVG(annual_amount), MIN(annual_amount),
                   MAX(annual_amount), AVG(actual_area)
              FROM raw_rent_contracts
             WHERE UPPER(TRIM(area_name_en)) = UPPER(TRIM(:area))
        """),
        valuations=await stats("""
            SELECT COUNT(*), AVG(actual_worth), MIN(actual_worth),
                   MAX(actual_worth), AVG(procedure_area)
              FROM raw_valuations
             WHERE UPPER(TRIM(area_name_en)) = UPPER(TRIM(:area))
        """),
    )


async def typical_annual_rent(conn: AsyncConnection, area_name: str) -> float | None:
    """The MEDIAN annual rent PER PROPERTY. The only rent figure fit to quote.

    Added in m15 because the agent got this wrong in a way that passed every check.

    Asked what a typical Dubai Marina apartment rents for, the agent routed correctly --
    resolved the name, called the SQL tool, never touched the corpus -- and answered
    **AED 550,010**. The true per-property median is **AED 120,000**. It was wrong by
    4.6x, and the routing eval passed it, because that eval grades the ROUTE and this was
    the right route.

    The cause is the trap this repository has already documented twice (changelog v0.5.0,
    G-02 in the retrieval golden set): `annual_amount` is the CONTRACT total and one
    contract can cover hundreds of properties -- 232 of them in this very area -- each
    getting its own row carrying the full portfolio amount. `AVG(annual_amount)` is
    therefore not a rent. `area_summary` exposed it to the agent as `avg_annual_rent` and
    the agent, reasonably, quoted it.

    A number that is documented as dangerous in two places and still reaches an answer is
    not a documentation problem. The division belongs in the query, so this function is
    what the tool layer returns and the raw mean is relabelled to say what it actually is.
    """
    row = (
        await conn.execute(
            text("""
                SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (
                           ORDER BY annual_amount / NULLIF(no_of_prop, 0)
                       ) FILTER (WHERE annual_amount > 0)
                  FROM raw_rent_contracts
                 WHERE UPPER(TRIM(area_name_en)) = UPPER(TRIM(:area))
            """),
            {"area": area_name},
        )
    ).first()
    return round(float(row[0]), 2) if row and row[0] is not None else None


# ── spatial ─────────────────────────────────────────────────────────────────


async def community_neighbors(
    conn: AsyncConnection, community_id: int, predicate: str = "touches"
) -> CommunityNeighborsResponse | None:
    """Adjacency: which communities border this one? None when the id does not exist.

    A spatial self-join -- the first query in this project where a polygon is the operand
    rather than the probe. Without an index it is O(n^2): 222 polygons is 49,284 candidate
    pairs. With `idx_communities_geom` the planner runs it in two stages, the GiST index
    answering the bounding-box operator first and the exact predicate refining only the
    survivors. See docs/polygon-adjacency-plans.md, including the honest finding that at
    this row count the index buys far less than the raw wall-clock suggests.
    """
    fn = ADJACENCY_PREDICATES[predicate.lower()]
    origin = (
        await conn.execute(
            text("SELECT id, community_name_en FROM communities WHERE id = :id"),
            {"id": community_id},
        )
    ).first()
    if origin is None:
        return None

    rows = await conn.execute(
        text(f"""
            SELECT
                b.id,
                b.community_name_en,
                -- the shared boundary is a LINE, so its length is what has meaning
                -- here, not an area; geography again for metres
                ST_Length(ST_Intersection(a.geom, b.geom)::geography) AS shared_m
            FROM communities a
            JOIN communities b
              ON a.id <> b.id
             AND {fn}(a.geom, b.geom)
            WHERE a.id = :id
            ORDER BY shared_m DESC, b.community_name_en
        """),
        {"id": community_id},
    )
    data = [
        CommunityNeighbor(
            id=r[0],
            community_name_en=r[1],
            shared_boundary_m=round(float(r[2] or 0.0), 2),
        )
        for r in rows.fetchall()
    ]
    return CommunityNeighborsResponse(
        id=origin[0],
        community_name_en=origin[1],
        predicate=predicate.lower(),
        total=len(data),
        data=data,
    )


async def community_names(conn: AsyncConnection) -> list[str]:
    """Every community polygon name. 222 of them, and they are NOT the area names."""
    rows = await conn.execute(
        text("SELECT community_name_en FROM communities ORDER BY 1")
    )
    return [r[0] for r in rows]


async def community_neighbors_by_name(
    conn: AsyncConnection, area_name: str, predicate: str = "touches"
) -> tuple[CommunityNeighborsResponse | None, list[str]]:
    """`community_neighbors` keyed by NAME. Returns (result, candidate names).

    The REST resource is keyed by `community_id`, which is correct for a REST resource
    and useless as a tool signature: a language model has no way to obtain an opaque
    integer, and inventing one is exactly the failure mode a tool layer must not invite.

    THE POLYGON TABLE HAS ITS OWN NAMING PROBLEM, AND IT IS WORSE THAN THE AREA TABLE'S.
    This was found by R-10 in the routing eval, not by design. "Which communities share a
    border with Palm Jumeirah?" failed, and the reason is that the boundary polygon for
    Palm Jumeirah is called **NAKHLAT JUMEIRA** -- `nakhlat` is Arabic for palm, and the
    KML was transliterated rather than translated. Nothing in `resolve_area_name` helps:
    that resolves against TRANSACTION area names, and this is a different table with a
    different vocabulary.

    Fuzzy matching does not rescue it either. "palm jumeirah" and "nakhlat jumeira" share
    no token -- `jumeirah` and `jumeira` are different strings -- so the correct answer
    scores below several wrong ones. Rather than guess, the closest names are returned so
    the caller can say what does exist. A human reading "NAKHLAT JUMEIRA" next to a
    question about Palm Jumeirah can see it; a similarity score never will.

    Only 106 of the 222 polygons match a transaction area name, so a miss here is a
    frequent, legitimate outcome rather than an error.
    """
    row = (
        await conn.execute(
            text("""
                SELECT id FROM communities
                 WHERE community_name_norm = UPPER(TRIM(:name))
                 ORDER BY id
                 LIMIT 1
            """),
            {"name": area_name},
        )
    ).first()
    if row is not None:
        return await community_neighbors(conn, int(row[0]), predicate), []

    names = await community_names(conn)
    ranked = sorted(((n, _similarity(area_name, n)) for n in names), key=lambda p: -p[1])
    return None, [n for n, _ in ranked[:MAX_CANDIDATES]]


# ── coverage ────────────────────────────────────────────────────────────────


async def dataset_overview(conn: AsyncConnection) -> dict:
    """What data exists at all: row counts, date ranges, and the enumerable filters.

    The agent needs this to refuse well. "Which agency closed the most deals?" is
    unanswerable because there is no agency column, and a model that cannot see the shape
    of the schema will either invent one or refuse for the wrong reason. Returning the
    enumerable dimensions -- four property types, not a free-text field -- lets a refusal
    name what IS available instead of just declining.
    """
    counts = (
        await conn.execute(
            text("""
                SELECT (SELECT COUNT(*) FROM raw_transactions),
                       (SELECT COUNT(*) FROM raw_rent_contracts),
                       (SELECT COUNT(*) FROM raw_valuations),
                       (SELECT COUNT(*) FROM communities),
                       (SELECT MIN(instance_date) FROM raw_transactions),
                       (SELECT MAX(instance_date) FROM raw_transactions)
            """)
        )
    ).one()
    property_types = [
        r[0]
        for r in await conn.execute(
            text("""
                SELECT property_type_en FROM raw_transactions
                 WHERE property_type_en IS NOT NULL
                 GROUP BY 1 ORDER BY COUNT(*) DESC
            """)
        )
    ]
    return {
        "transactions": counts[0],
        "rent_contracts": counts[1],
        "valuations": counts[2],
        "community_polygons": counts[3],
        "transactions_from": str(counts[4]) if counts[4] else None,
        "transactions_to": str(counts[5]) if counts[5] else None,
        "distinct_areas": len(await known_area_names(conn)),
        "property_types": property_types,
        "currency": "AED",
        "fields_not_available": [
            # Named explicitly so a refusal can be specific. Every one of these is a
            # plausible question about Dubai property that this data cannot answer.
            "real-estate agency, broker or agent",
            "buyer or seller identity",
            "listing or asking price (only registered transaction value)",
            "forecasts or projections of any kind",
        ],
    }
