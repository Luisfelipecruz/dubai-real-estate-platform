"""The tenth tool: its argument model, its description, and its handler.

All of it lives here rather than in `services/agent/tools.py` so that registering it is
three lines in that file instead of sixty, and so the argument model, the description and
the handler can be tested together without loading the whole tool registry.

WHY THE DESCRIPTION IS THE LOAD-BEARING PART
---------------------------------------------
`tools.py` says it outright: routing is enforced in the DESCRIPTIONS, not in the system
prompt, because the description is what the model reads at the moment it is choosing. So
this one has to do three jobs beyond naming the parameters -- send area questions to
`area_summary`, name the measures, and say that the mean is deliberately absent. All three
are failures that were measured before they were written down.

WHY A REFUSAL COMES BACK AS DATA AND NOT AS is_error
------------------------------------------------------
`tools.ToolFailed` is the registry's mechanism for a decline: it becomes a `tool_result`
with `is_error: true`. This handler does not raise it, so that the module stays independent
of the registry it is plugged into -- nothing here needs `tools.run` to catch a particular
exception by name. A refusal is returned as `{"refused": true, "reason": ...}`, and the
payload carries the recovery path either way.

Whoever finishes this may prefer the other shape. It is one line in `tools.run`:

    except AggregateRefused as exc:
        return str(exc), True

and then this module raises instead of catching. Both are defensible; only one of them is
safe to ship half-wired.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from services.aggregates import queries
from services.aggregates.spec import DATASETS, AggregateRefused, dataset_spec

#: Every measure key across every dataset, as one closed set. A cross-dataset key -- asking
#: for `annual_rent_per_property` on `transactions` -- is still refused, with the list that
#: dataset does offer. Closing it in the schema means constrained decoding cannot emit a
#: key that does not exist anywhere; refusing the mismatch means the model is told which
#: ones it could have asked for.
#: Dimensions this tool ACCEPTS but never computes: it answers them with the name of the
#: tool that does. Kept as data so the schema, the handler and the test cannot disagree --
#: `test_every_dimension_in_the_schema_is_closed_except_property_type` asserts the schema
#: enum is exactly the computable dimensions PLUS these, and that none of these ever
#: reaches `queries.breakdown`.
ROUTED_ELSEWHERE: dict[str, str] = {"area_name": "list_areas"}

MEASURE_KEYS: tuple[str, ...] = tuple(
    sorted({key for name in DATASETS for key in dataset_spec(name).measures})
)

Measures = Literal[
    "annual_rent_contract",
    "annual_rent_per_property",
    "floor_area",
    "price_per_sqm",
    "sale_price",
    "valued_amount",
]


class DatasetAggregateArgs(BaseModel):
    """One question shape covering every dataset-wide total, median and extreme.

    `property_type` is the one free-text field, and deliberately: the values differ by
    dataset and are a property of the loaded data, not of this code. It is matched against
    what the table actually holds, and a miss is refused with the real values rather than
    answered with a zero.
    """

    dataset: Literal["transactions", "rent_contracts", "valuations"] = Field(
        ...,
        description="transactions = registered SALES (1977-2026, real history). "
        "rent_contracts = registered rent contracts, which are a SNAPSHOT: ~90% of them "
        "start in the most recent year. valuations = recorded valuations, which cover "
        "only a few months of the most recent year.",
    )
    metric: Literal["count", "median", "maximum", "minimum", "total"] = Field(
        ...,
        description="count needs no measure; the rest summarise one. There is NO mean: "
        "over all 200,001 sales the mean is 2.9x the median because one row is AED "
        "13.79 bn, so use median for anything described as typical or average.",
    )
    measure: Measures | None = Field(
        None,
        description="Which column to summarise. transactions: sale_price, price_per_sqm, "
        "floor_area. rent_contracts: annual_rent_per_property (use this one for rent -- "
        "annual_rent_contract may cover many properties at once), annual_rent_contract, "
        "floor_area. valuations: valued_amount, floor_area. Omit for count.",
    )
    year: int | None = Field(
        None,
        ge=1900,
        le=2100,
        description="Restrict to one calendar year. The tool refuses rather than "
        "answering zero if the dataset holds no rows from that year, and says when a "
        "year is only partly covered.",
    )
    property_type: str | None = Field(
        None,
        description="Restrict to one property type, e.g. 'Villa'. Case-insensitive. If "
        "the value does not exist the tool lists the ones that do -- it never returns a "
        "count of zero for a filter that cannot be applied.",
    )
    breakdown_by: Literal["year", "property_type", "area_name"] | None = Field(
        None,
        description="Split the metric into groups instead of returning one number. Use "
        "this for 'which type is most expensive' or 'how has this changed'. Each group "
        "carries its own row count, and a group too small to support the metric reports "
        "no value rather than a misleading one. "
        "`area_name` is accepted ONLY so this tool can tell you to use list_areas "
        "instead -- it does not compute a per-area breakdown.",
    )


DESCRIPTION = (
    "Totals, medians and extremes across a WHOLE dataset -- every recorded sale, rent "
    "contract or valuation in Dubai -- optionally filtered to one year or one property "
    "type, and optionally broken down by year or by property type. "
    "Prefer this over retrieved text for any number. "
    "This tool is NOT area-scoped: for a single district use area_summary or "
    "area_price_history, and do not call this one per area. "
    "For 'which areas had the most ...' -- a RANKING across areas -- use list_areas, "
    "which is built for exactly that and returns them ordered. "
    "It refuses, with the values that do exist, rather than returning a zero for a filter "
    "that cannot be applied -- so a zero from it is a real zero. "
    "Every answer carries the row counts it was computed over and says when a period is "
    "incomplete or a dataset is a snapshot rather than a history."
)


def _serialise(result: Any) -> dict[str, Any]:
    return {
        "dataset": result.dataset,
        "metric": result.metric,
        "measure": result.measure,
        "unit": result.unit,
        "value": result.value,
        "filters": dict(result.filters),
        "rows_matched": result.rows_matched,
        "rows_in_dataset": result.rows_in_dataset,
        "rows_excluded_by_measure": result.rows_excluded_by_measure,
        "period": result.period,
        "value_withheld_because": result.suppressed,
        "caveats": list(result.caveats),
    }


async def dataset_aggregate(
    conn: AsyncConnection,
    dataset: str,
    metric: str,
    measure: str | None = None,
    year: int | None = None,
    property_type: str | None = None,
    breakdown_by: str | None = None,
) -> dict[str, Any]:
    """Answer one dataset-wide question, or say why it will not be answered.

    Positional-or-keyword rather than keyword-only, because `tools.run` dispatches with
    `handler(conn, **parsed.model_dump())` and the model dump is a plain dict.
    """
    # ROUTING, NOT VALIDATION.
    #
    # `area_name` is deliberately not a dimension of this tool: `list_areas` already
    # ranks areas by activity, and two tools answering one question is precisely what the
    # routing eval grades.
    #
    # But the schema enforced that decision by REJECTING the argument, and a rejection is
    # not a redirection. Asked "Which areas had the most transactions in 2024?", the model
    # sent breakdown_by="area_name" -- the correct instinct, expressed correctly -- and
    # got back "Input should be 'year' or 'property_type'". Nothing in that sentence names
    # the tool that does the job, so the run gave up and refused a question the data
    # answers easily. Measured twice: once on that question, once inside the 146.9 s
    # Business Bay run.
    #
    # So the argument is now accepted and answered with the route. This is the same shape
    # as every other decline in this module -- data, with the recovery path attached --
    # and the same lesson as resolve_area_name listing the names that DO exist.
    if breakdown_by in ROUTED_ELSEWHERE:
        return {
            "refused": True,
            "reason": (
                "This tool aggregates over a whole dataset and does not break down by "
                "area. Use list_areas instead: it ranks areas by transaction, rent or "
                "valuation count and returns them in order, which is what a 'which "
                "areas' question needs. For ONE named district, use area_summary."
            ),
            "use_instead": ROUTED_ELSEWHERE[breakdown_by],
            "call_it_like": {"order_by": "transactions", "limit": 10},
        }

    try:
        if breakdown_by is not None:
            groups = await queries.breakdown(
                conn,
                dataset=dataset,
                metric=metric,
                dimension=breakdown_by,
                measure=measure,
            )
            spec = dataset_spec(dataset)
            resolved = spec.measures.get(measure) if measure else None
            return {
                "dataset": dataset,
                "metric": metric,
                "measure": measure,
                "unit": resolved.unit if resolved else spec.row_label,
                "grouped_by": breakdown_by,
                "groups": [
                    {
                        "key": g.key,
                        "rows": g.rows,
                        "value": g.value,
                        "value_withheld_because": g.suppressed,
                    }
                    for g in groups
                ],
            }
        result = await queries.aggregate(
            conn,
            dataset=dataset,
            metric=metric,
            measure=measure,
            year=year,
            property_type=property_type,
        )
        return _serialise(result)
    except AggregateRefused as exc:
        return {
            "refused": True,
            "reason": str(exc),
            "note": "This is NOT a zero and NOT an absence in the data. Do not report it "
            "as one. Either use a value named in the reason, or say that this platform "
            "does not hold what was asked for.",
        }


#: What `services/agent/tools.py` needs, once it is unblocked. Kept here so the wiring is
#: an import and a tuple entry rather than a design decision taken at the wrong moment.
REGISTRATION = {
    "name": "dataset_aggregate",
    "description": DESCRIPTION,
    "category": "sql",
    "arguments": DatasetAggregateArgs,
    "handler": dataset_aggregate,
}
