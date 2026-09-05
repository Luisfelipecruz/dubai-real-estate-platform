"""The evaluation harness, exposed over HTTP.

ONE ENDPOINT, AND WHAT IT REFUSES TO DO
---------------------------------------
`GET /evals/latest` returns the most recently RECORDED result joined to the floors in
`eval/thresholds.yaml`. It does not run the suite. A full run is tens of minutes of model
calls against the live agent, and a handler that triggered one would turn a page refresh
into a billing event and a request that cannot finish inside any sane timeout.

It also computes nothing the fixtures did not measure. Every rate, margin, count and
staleness verdict comes out of `services/evaluation/results.assess`, which is pure and
directly asserted in `api/tests/test_eval_results.py`, so no number reaches a client
without a test standing behind it.

WHY THE ANSWER CAN BE "NOTHING HAS BEEN RECORDED", WITH A 200
-------------------------------------------------------------
A fresh checkout has never run the suite, and `eval/` is an optional mount. Neither is an
error and neither should be a 404: the question being asked is what this deployment can
prove about itself, and "nothing yet, run `make eval`" is a true and useful answer to it.

The one genuine failure -- the table is missing because the migration has not been applied
-- is a 503 carrying the command that fixes it.
"""

from fastapi import APIRouter, HTTPException, Query

from database import engine
from services.evaluation import results as eval_results

router = APIRouter()


def _live_tool_names() -> list[str] | None:
    """The registry as it stands right now, or None if the agent layer is not installed.

    None is not an empty list, and the difference is load-bearing. An empty list would make
    the staleness check report every recorded tool as REMOVED -- a confident, precise,
    completely false claim about drift -- on a deployment whose only fault is that the
    copilot routers are not installed. None makes it report that it cannot tell.
    """
    try:
        from services.agent import tools
    except Exception:  # pragma: no cover - the agent layer is an optional module
        return None
    return [tool.name for tool in tools.TOOLS]


@router.get("/evals/latest")
async def latest_eval(
    suite: str | None = Query(
        None,
        pattern="^(truths|retrieval|agent|all)$",
        description="Restrict to one suite. Default: the newest result of any suite.",
    ),
):
    """The last recorded run, every floor it is compared against, and its expiry.

    THE FIELD TO READ FIRST IS `registry`, not the score. A pass rate is a statement about
    a system, and the system it describes is the one that was running when the suite ran.
    A tool added since then can answer questions the agent used to decline, which moves
    every rate derived from them -- while the stored score and its timestamp stay exactly
    as they were. `registry.added_since` names the tools responsible, and `registry.stale`
    is what a page should draw before it draws a number.
    """
    async with engine.connect() as conn:
        try:
            row = await eval_results.latest(conn, suite)
        except eval_results.EvalResultsUnavailable as exc:
            raise HTTPException(status_code=503, detail=exc.remedy) from exc

    return eval_results.assess(
        row,
        eval_results.load_thresholds(),
        live_tools=_live_tool_names(),
    )
