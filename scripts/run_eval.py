"""The evaluation harness: three suites, one entry point.

    docker compose exec api python /app/scripts/run_eval.py --suite truths
    docker compose exec api python /app/scripts/run_eval.py --suite retrieval
    docker compose exec api python /app/scripts/run_eval.py --suite agent
    docker compose exec api python /app/scripts/run_eval.py --suite all --gate

WHY THIS DID NOT ABSORB `run_routing_eval.py`
----------------------------------------------
  - `--suite agent` DOES grade route and answer together, and has to. "The route was
    right and the answer was 4.6x wrong" is a claim about ONE response, and a local 20B
    does not return the same response twice. Two scripts issuing two requests cannot make
    that statement; they can only report two rates that happen to disagree.

  - `run_routing_eval.py` stays because it needs no database and runs anywhere the API
    runs, which `--suite agent` does not. Deleting it to avoid two entry points would cost
    that property to save one redundant script.

The grading logic is NOT duplicated. It moved to `services/evaluation/`, where it has
tests; `run_routing_eval.py` keeps its own inlined copy of the route rules exactly as it
shipped, and `api/tests/test_eval_fixtures.py` asserts the two agree on every question in
the routing fixture. If they ever diverge, a test says so.

WHAT EACH SUITE COSTS
----------------------
  truths      seconds. Postgres only, no model, no network. This is the suite that
              validates the fixture itself and it should be run before the other two.
  retrieval   ~1 minute for 4 modes over the fixture, plus 11 minutes ONCE if the
              cross-encoder is cold (it is 1.1 GB and loads lazily).
  agent       minutes to tens of minutes. Every question is a multi-turn conversation
              with a 20B model, 1.3 s to 40 s each, and the host load moves it by 1.7x.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.evaluation import grading, retrieval as retrieval_metrics, truth  # noqa: E402
from services.evaluation import results as eval_results  # noqa: E402
from services.evaluation.numeric import matches as numeric_matches  # noqa: E402
from services.evaluation.numeric import parse_tolerance  # noqa: E402

GOLDEN = ROOT / "eval" / "golden"
ANSWERS = GOLDEN / "answers.yaml"
RETRIEVAL = GOLDEN / "retrieval.yaml"
ROUTING = GOLDEN / "routing.yaml"
THRESHOLDS = ROOT / "eval" / "thresholds.yaml"

CAVEAT = (
    "Hand-written, one author, one project's own data. These numbers detect a REGRESSION\n"
    "and demonstrate a mechanism. They do not establish an accuracy rate for anything."
)


def load(path: Path) -> dict:
    fixture = yaml.safe_load(path.read_text())
    if not fixture.get("graded_before_run", True):
        raise SystemExit(f"REFUSING: {path.name} is not marked graded_before_run.")
    return fixture


# ───────────────────────────────────────────────────────────────────────────────
# suite: truths
# ───────────────────────────────────────────────────────────────────────────────


async def resolve_truths(fixture: dict) -> dict[str, dict]:
    """Run every ground-truth query and every decoy query, once.

    Separated from grading so a fixture can be validated without spending a single token,
    and so the model suite does not pay for the database round trips per question.
    """
    from database import async_session  # imported late: it builds an engine on import

    resolved: dict[str, dict] = {}
    async with async_session() as session:
        universes: dict[str, list[str]] = {}
        for name, sql in (fixture.get("universes") or {}).items():
            universes[name], _ = await truth.resolve_set(session, sql)

        for question in fixture["questions"]:
            entry: dict = {"id": question["id"], "kind": question["kind"]}
            if question.get("expect") == "abstain":
                entry["expect_abstain"] = True
                resolved[question["id"]] = entry
                continue

            if question["kind"] == "name_set":
                names, sql = await truth.resolve_set(session, question["ground_truth_sql"])
                entry["expected_names"] = names
                entry["sql"] = sql
                entry["universe"] = universes.get(question.get("universe", "communities"), [])
                entry["live_value"] = len(names)
            else:
                got = await truth.resolve_scalar(session, question["ground_truth_sql"])
                entry["truth"] = got.value
                entry["sql"] = got.sql
                entry["live_value"] = got.value
                decoys: dict[str, Decimal] = {}
                for name, sql in (question.get("decoys") or {}).items():
                    decoy = await truth.resolve_scalar(session, sql)
                    if decoy.value is not None:
                        decoys[name] = decoy.value
                entry["decoys"] = decoys
            resolved[question["id"]] = entry
    return resolved


# Drift detection is NOT graded with the question's own tolerance, and the difference
# matters. A-14 grades at +/-1% because a rent median that moves 0.8% is still the right
# answer; drift at 1% would hide a reload that shifted every median in the file. So drift
# uses its own, far tighter, comparison and only tolerates float noise.
#
# It has to tolerate that much. `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY a / b)` on a
# division returns DOUBLE PRECISION, so A-20 comes back as 166765.08000000002 and A-15 as
# 22035.725 against readings recorded through psql's ROUND(...,2). Comparing those exactly
# reports two drifts that are formatting, which is a false alarm in a check whose entire
# value is that it is quiet until something real moves.
_DRIFT_TOLERANCE = parse_tolerance("rel:1e-9")


def report_truths(fixture: dict, resolved: dict[str, dict]) -> int:
    """Print live value against recorded value. Drift is reported, never fatal.

    A data reload is not a regression. Failing the build for one would train everyone to
    re-baseline the fixture on sight, which is precisely how a threshold ends up equal to
    whatever the system currently does.
    """
    print(f"{'id':6} {'kind':10} {'recorded':>18} {'live':>18}  note")
    drifted = 0
    for question in fixture["questions"]:
        entry = resolved[question["id"]]
        if entry.get("expect_abstain"):
            print(f"{question['id']:6} {'abstain':10} {'-':>18} {'-':>18}  no query by design")
            continue
        recorded = question.get("recorded_value")
        live = Decimal(str(entry["live_value"]))
        same = recorded is not None and numeric_matches(
            live, Decimal(str(recorded)), _DRIFT_TOLERANCE
        )
        if not same:
            drifted += 1
        print(
            f"{question['id']:6} {entry['kind']:10} "
            f"{'-' if recorded is None else f'{Decimal(str(recorded)):,.2f}':>18} "
            f"{live:>18,.2f}  {'' if same else 'DRIFTED'}"
        )
    print(f"\n{len(fixture['questions'])} questions, {drifted} drifted from the recorded reading.")
    if drifted:
        print("Drift is information, not a failure. Check whether the data was reloaded.")
    return 0


# ───────────────────────────────────────────────────────────────────────────────
# suite: retrieval
# ───────────────────────────────────────────────────────────────────────────────

MODES = ("dense", "lexical", "hybrid", "hybrid+rerank")


def _relevance_for(question: dict, results: list[dict]) -> dict[str, int]:
    """The graded map for one question, including the `expect_source_type` questions.

    The vague questions have no single right document — they exist to test that the area
    fact sheets are FINDABLE at all — so any sheet is a 3 and everything else is 0. That
    is the m13a rule, unchanged; encoding it here rather than expanding the fixture keeps
    the fixture readable for a human grader.
    """
    # `decoys` is a SEPARATE key in the fixture and must be merged in, not ignored. A
    # decoy is graded 0, which is numerically what an unjudged document already scores —
    # so dropping the key changes no metric except the one it exists for. `score_question`
    # reports "a document the fixture explicitly called a decoy outranked the answer" by
    # testing that the key is PRESENT, and an unmerged decoy makes that count zero forever.
    relevance = dict(question.get("decoys") or {})
    if "relevance" in question:
        relevance.update(question["relevance"])
        return relevance
    wanted = question.get("expect_source_type")
    relevance.update({r["source_id"]: 3 for r in results if r.get("source_type") == wanted})
    return relevance


def run_retrieval(base: str, fixture: dict, modes: tuple[str, ...], k: int, timeout: float) -> dict:
    out: dict[str, dict] = {}
    cohorts = {q["id"]: q.get("cohort", "unlabelled") for q in fixture["questions"]}
    with httpx.Client(timeout=timeout) as client:
        for mode in modes:
            rerank = mode.endswith("+rerank")
            search_mode = mode.split("+")[0]
            scored = []
            print(f"\n── {mode} ──")
            for question in fixture["questions"]:
                response = client.get(
                    f"{base}/search",
                    params={
                        "q": question["text"],
                        "k": k,
                        "mode": search_mode,
                        "rerank": str(rerank).lower(),
                    },
                )
                if response.status_code != 200:
                    print(f"  ERR  {question['id']}  HTTP {response.status_code}")
                    continue
                results = response.json()["results"]
                relevance = _relevance_for(question, results)
                scores = retrieval_metrics.score_question(
                    question["id"], [r["source_id"] for r in results], relevance
                )
                scored.append(scores)
                flag = "ideal" if scores.top1_ideal else ("hit@5" if scores.hit_at.get(5) else "MISS")
                decoyed = ""
                if scores.decoy_at_top:
                    decoyed = f"  DECOY AT RANK 1: {scores.decoy_at_top}"
                elif scores.decoys_above_answer:
                    decoyed = f"  decoy above the answer: {scores.decoys_above_answer}"
                print(
                    f"  {question['id']:6} {flag:6} mrr={scores.mrr:.3f} "
                    f"ndcg@5={scores.ndcg_at_5:.3f}  {results[0]['source_id'] if results else '-'}"
                    f"{decoyed}"
                )
            out[mode] = retrieval_metrics.aggregate(scored)
            # Per cohort as well as combined. "dense 8/10 top-1" is a published figure and
            # adding ten questions must not silently redefine it; the m13a column is the
            # one that stays comparable with what this project has already claimed.
            for cohort in sorted({cohorts[s.id] for s in scored}):
                subset = [s for s in scored if cohorts[s.id] == cohort]
                out[f"{mode}::{cohort}"] = retrieval_metrics.aggregate(subset)
    return out


def report_retrieval(summary: dict) -> None:
    print(f"\n{'mode':24} {'top1 ideal':>12} {'hit@1':>9} {'hit@5':>9} {'MRR':>7} {'nDCG@5':>8}")
    for mode, agg in summary.items():
        n = agg["n"]
        if not n:
            continue
        print(
            f"{mode:24} {agg['top1_ideal_count']:>5}/{n:<6} "
            f"{agg['hit_at_count'][1]:>4}/{n:<4} {agg['hit_at_count'][5]:>4}/{n:<4} "
            f"{agg['mrr']:>7.3f} {agg['ndcg_at_5']:>8.3f}"
        )


# ───────────────────────────────────────────────────────────────────────────────
# suite: agent — route and answer, graded on ONE response
# ───────────────────────────────────────────────────────────────────────────────


def grade_route(routing_question: dict | None, response: dict) -> tuple[bool, list[str]]:
    """The route rules, applied to a response this script already has.

    Deliberately the same rules as `run_routing_eval.py` rather than an improvement on
    them. A test asserts the two agree; the moment this file starts grading routes
    differently, results from the two stop being comparable.
    """
    if routing_question is None:
        return True, []
    called = [c["name"] for step in response["steps"] for c in step.get("tool_calls", [])]
    reasons = []
    missing = set(routing_question.get("expect_tools") or []) - set(called)
    if missing:
        reasons.append(f"never called {sorted(missing)}")
    used = set(routing_question.get("forbid_tools") or []) & set(called)
    if used:
        reasons.append(f"called forbidden {sorted(used)}")
    if routing_question["route"] == "refuse":
        if response["outcome"] != "refused":
            reasons.append(f"should have refused, outcome was {response['outcome']!r}")
    elif response["outcome"] != "answered":
        reasons.append(f"expected an answer, outcome was {response['outcome']!r}")
    return (not reasons), reasons


def run_agent(
    base: str,
    fixture: dict,
    resolved: dict[str, dict],
    routing: dict[str, dict],
    only: set[str] | None,
    timeout: float,
    provider: str | None,
) -> list[dict]:
    results = []
    questions = [q for q in fixture["questions"] if not only or q["id"] in only]
    print(f"{len(questions)} questions against {base}\n")
    with httpx.Client(timeout=timeout) as client:
        for question in questions:
            entry = resolved[question["id"]]
            payload = {"q": question["text"]}
            if provider:
                payload["provider"] = provider
            mark = time.time()
            response = error = None
            try:
                raw = client.post(f"{base}/agent/query", json=payload)
                if raw.status_code != 200:
                    error = f"HTTP {raw.status_code}: {raw.text[:200]}"
                else:
                    response = raw.json()
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            elapsed = int((time.time() - mark) * 1000)

            if error:
                # THE LINK SURVIVES THE ERROR, AND THAT IS THE WHOLE POINT OF THESE TWO
                # FIELDS. An errored record used to carry no `routing_id`, so the question
                # left the route denominator instead of failing in it — and a timeout on
                # the hardest linked question RAISED the reported route accuracy. Keeping
                # the id here means the question is still counted as linked; `route_ok`
                # stays None because the route is unknown, not wrong. Nothing came back to
                # grade.
                results.append(
                    {
                        "id": question["id"],
                        "verdict": "error",
                        "passed": False,
                        "reasons": [error],
                        "elapsed_ms": elapsed,
                        "routing_id": question.get("routing_id"),
                        "route_ok": None,
                    }
                )
                print(f"  ERR  {question['id']:6} {elapsed/1000:6.1f}s  {error}")
                continue

            answer = response.get("answer") or ""
            outcome = response["outcome"]
            expect_abstain = bool(entry.get("expect_abstain"))

            if question["kind"] == "name_set":
                verdict = grading.grade_set(
                    answer,
                    outcome,
                    entry.get("expected_names", []),
                    entry.get("universe", []),
                    expect_abstain=expect_abstain,
                    subjects=question.get("subjects"),
                    leading_only=bool(question.get("expect_leading")),
                )
                record = {
                    "verdict": verdict.verdict,
                    "passed": verdict.passed,
                    "reasons": verdict.reasons,
                    "expected": verdict.expected,
                    "mentioned": verdict.mentioned,
                    "recall": verdict.recall,
                    "precision": verdict.precision,
                }
            else:
                verdict = grading.grade_numeric(
                    answer,
                    outcome,
                    entry.get("truth"),
                    parse_tolerance(question.get("tolerance")),
                    unit=question.get("unit"),
                    decoys=entry.get("decoys") or {},
                    expect_abstain=expect_abstain,
                )
                record = {
                    "verdict": verdict.verdict,
                    "passed": verdict.passed,
                    "reasons": verdict.reasons,
                    "truth": str(verdict.truth) if verdict.truth is not None else None,
                    "matched": str(verdict.matched) if verdict.matched is not None else None,
                    "decoy_hit": verdict.decoy_hit,
                    "leads_with_truth": verdict.leads_with_truth,
                    "unit_ok": verdict.unit_ok,
                }

            route_ok, route_reasons = grade_route(
                routing.get(question.get("routing_id")), response
            )
            results.append(
                {
                    "id": question["id"],
                    "text": question["text"],
                    "kind": question["kind"],
                    "elapsed_ms": elapsed,
                    "route_ok": route_ok,
                    "route_reasons": route_reasons,
                    "routing_id": question.get("routing_id"),
                    "answer": answer,
                    "outcome": outcome,
                    "run_id": response.get("run_id"),
                    "warnings": response.get("grounding_warnings", []),
                    **record,
                }
            )
            # The route/answer split is printed on every line, because the single most
            # useful thing this harness reports is a question where they disagree.
            route_mark = "route:ok " if route_ok else "route:FAIL"
            if question.get("routing_id") is None:
                route_mark = "route:--  "
            # Route reasons are printed on the same line as the answer verdict. The first
            # run of this harness showed `route:FAIL` with no explanation and the reason
            # had to be recovered by re-issuing the request by hand — which on a
            # non-deterministic model is not recovering it at all.
            why = "; ".join(record["reasons"] + [f"ROUTE: {r}" for r in route_reasons])
            print(
                f"  {'PASS' if record['passed'] else 'FAIL'} {question['id']:6} "
                f"{route_mark} {record['verdict']:16} {elapsed/1000:6.1f}s  {why[:130]}"
            )
    return results


def regrade(fixture: dict, resolved: dict[str, dict], previous: list[dict]) -> list[dict]:
    """Re-score a stored run with the CURRENT graders. No model calls, no cost.

    This exists because it was needed twice in one afternoon, and because doing it by hand
    is how a grader fix quietly becomes a re-run whose numbers cannot be compared with the
    ones before it. A local 20B does not answer the same question the same way twice, so
    "we fixed the grader and the score went up" is unreadable if the responses also
    changed. Holding the responses fixed makes the attribution exact: this many failures
    were the system, this many were the measurement.

    On the first full run it moved 25/40 to 29/40 with six verdicts changing, every one of
    them a correct answer the harness could not see.
    """
    by_id = {q["id"]: q for q in fixture["questions"]}
    out = []
    for record in previous:
        question = by_id.get(record["id"])
        if question is None or record.get("verdict") == "error":
            out.append(record)
            continue
        entry = resolved[record["id"]]
        expect_abstain = bool(entry.get("expect_abstain"))
        answer, outcome = record.get("answer") or "", record.get("outcome", "answered")
        if question["kind"] == "name_set":
            verdict = grading.grade_set(
                answer, outcome, entry.get("expected_names", []), entry.get("universe", []),
                expect_abstain=expect_abstain, subjects=question.get("subjects"),
                leading_only=bool(question.get("expect_leading")),
            )
            fields = {"verdict": verdict.verdict, "passed": verdict.passed,
                      "reasons": verdict.reasons, "mentioned": verdict.mentioned}
        else:
            verdict = grading.grade_numeric(
                answer, outcome, entry.get("truth"),
                parse_tolerance(question.get("tolerance")), unit=question.get("unit"),
                decoys=entry.get("decoys") or {}, expect_abstain=expect_abstain,
            )
            fields = {"verdict": verdict.verdict, "passed": verdict.passed,
                      "reasons": verdict.reasons,
                      "leads_with_truth": verdict.leads_with_truth,
                      "unit_ok": verdict.unit_ok}
        if fields["verdict"] != record.get("verdict"):
            print(f"  {record['id']:6} {record.get('verdict'):16} -> {fields['verdict']}")
        out.append({**record, **fields})
    return out


def report_agent(results: list[dict]) -> dict:
    n = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    by_verdict: dict[str, int] = {}
    for result in results:
        by_verdict[result["verdict"]] = by_verdict.get(result["verdict"], 0) + 1

    # THREE STATES, not two. A linked question was routed right, routed wrong, or never
    # answered at all — and the third is not a quieter version of the second. An errored
    # run has no route to grade, so folding it in as a failure invents a verdict, and
    # dropping it from the denominator flatters the score. It gets counted separately and
    # reported beside the rate it would otherwise distort.
    linked = [r for r in results if r.get("routing_id")]
    errored = [r for r in linked if r.get("route_ok") is None]
    graded = [r for r in linked if r.get("route_ok") is not None]
    route_ok = sum(1 for r in graded if r["route_ok"])
    disagreements = [r for r in graded if r["route_ok"] and not r.get("passed")]

    print(f"\nanswers  {passed}/{n}")
    for verdict, count in sorted(by_verdict.items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:18} {count}")
    if linked:
        print(f"\nroutes   {route_ok}/{len(graded)} graded"
              f"   of {len(linked)} linked to routing.yaml")
        if errored:
            print(
                f"  NOT MEASURED: {len(errored)}  {[r['id'] for r in errored]}"
                f"   coverage {len(graded)}/{len(linked)}"
            )
            print("  The rate above is accuracy among the questions that answered. It is "
                  "not the fixture's score.")
        print(
            f"  RIGHT ROUTE, WRONG ANSWER: {len(disagreements)}"
            + (f"  {[d['id'] for d in disagreements]}" if disagreements else "")
        )
        if disagreements:
            print("  This is the gap route grading cannot see. It is why this suite exists.")
    numeric = [r for r in results if "leads_with_truth" in r and r["leads_with_truth"] is not None]
    if numeric:
        leads = sum(1 for r in numeric if r["leads_with_truth"])
        print(f"\ncontainment {sum(1 for r in numeric if r['passed'])}/{len(numeric)}"
              f"   leads-with-truth {leads}/{len(numeric)}")
    warned = sum(1 for r in results if r.get("warnings"))
    print(f"grounding warnings on {warned}/{n} runs")
    # The two PROPERTY metrics the threshold file gates at 1.0. They are counted here
    # rather than derived from `by_verdict` downstream so the definition lives in one
    # place: `fabricated` means a figure was produced for a question with no answer in the
    # data, and `decoyed` means the figure matched a trap the fixture names.
    fabricated = by_verdict.get("fabricated", 0)
    decoyed = by_verdict.get("decoyed", 0)
    unanswerable = sum(1 for r in results if r["verdict"] in
                       ("abstained", "fabricated", "over_answered", "empty"))
    # THE ONE ROUTE THAT IS A PROPERTY RATHER THAN A RATE. R-01 is the injection
    # question: a false sentence about Business Bay transaction volume, written into a
    # public note, produced a high-confidence answer with every grounding check green.
    # Verification cannot catch that; keeping the question away from prose can. This
    # question reaching `search_documents` is the mitigation failing, and it is gated at
    # 1.0 while overall route accuracy is not — because run 2 of this suite showed the
    # ROUTER IS NOT DETERMINISTIC at temperature 0. A-14 routed cleanly in run 1 and
    # reached for the corpus in run 2 on identical code. A probabilistic mitigation is
    # still worth having and is not the same thing as a guarantee, and the threshold file
    # should not blur the two.
    injection = next((r for r in results if r.get("routing_id") == "R-01"), None)
    injection_ok = 1.0 if (injection is None or injection.get("route_ok")) else 0.0
    print(f"the injection question stayed out of the corpus: {bool(injection_ok)}")
    print(f"fabricated figures on unanswerable questions: {fabricated}")
    print(f"answers matching a NAMED decoy: {decoyed}")
    return {
        "n": n,
        "passed": passed,
        "by_verdict": by_verdict,
        "route_ok": route_ok,
        # `route_n` is the GRADED denominator and `route_linked` is the fixture's. They
        # were the same number until a question could error while staying linked, and the
        # gap between them is the only thing that says a rate was measured on part of the
        # set.
        "route_n": len(graded),
        "route_linked": len(linked),
        "route_errors": len(errored),
        "route_error_ids": [r["id"] for r in errored],
        "right_route_wrong_answer": [d["id"] for d in disagreements],
        "fabricated": fabricated,
        "decoyed": decoyed,
        "unanswerable_n": unanswerable,
        "injection_ok": injection_ok,
    }


# ───────────────────────────────────────────────────────────────────────────────


def _agent_metrics(agent_summary: dict) -> dict:
    """The shape `eval/thresholds.yaml` gates on.

    The two 1.0 floors are expressed as "none of these happened", inverted into a rate, so
    the gate can compare them the same way it compares everything else. They are not rates
    in any meaningful sense — a single fabricated figure fails, whatever the denominator.
    """
    return {
        "answer_accuracy": agent_summary["passed"] / max(agent_summary["n"], 1),
        "route_accuracy": agent_summary["route_ok"] / max(agent_summary["route_n"], 1),
        # COVERAGE IS NOT ACCURACY AND IT IS NOT GATED. It answers a different question:
        # how much of the linked set the run actually measured. It falls below 1.0 only
        # when a question errored, which is an infrastructure fact rather than a quality
        # one, so it is reported and targeted rather than floored — a floor here would
        # turn a host-level timeout into a red build, and `thresholds.yaml` already
        # records what happens to a gate that goes red for reasons nobody can fix.
        "route_coverage": (
            agent_summary["route_n"] / max(agent_summary.get("route_linked") or 0, 1)
            if agent_summary.get("route_linked")
            else 1.0
        ),
        "unanswerable_no_fabrication": 0.0 if agent_summary["fabricated"] else 1.0,
        "no_decoyed_answers": 0.0 if agent_summary["decoyed"] else 1.0,
        "injection_question_stays_out_of_the_corpus": agent_summary["injection_ok"],
    }


def apply_gate(summary: dict) -> int:
    """Compare against eval/thresholds.yaml. Returns a process exit code.

    A threshold is a floor someone argued for, not a record of what the system did on the
    day it was written. Every entry in that file carries the argument.
    """
    if not THRESHOLDS.exists():
        print("\nno eval/thresholds.yaml — nothing gated")
        return 0
    thresholds = yaml.safe_load(THRESHOLDS.read_text())
    failures = []
    print("\n── gate ──")
    for key, floor in (thresholds.get("floors") or {}).items():
        section, _, metric = key.partition(".")
        actual = (summary.get(section) or {}).get(metric)
        if actual is None:
            print(f"  SKIP  {key} — not measured in this run")
            continue
        ok = actual >= floor
        print(f"  {'OK  ' if ok else 'FAIL'}  {key:34} {actual:.3f} >= {floor}")
        if not ok:
            failures.append(key)

    # A GREEN GATE ON A PARTIAL RUN IS THE FAILURE THIS PRINTS AGAINST. Coverage carries
    # no floor, so nothing above would mention it — and a run that could not measure its
    # hardest linked question passes every floor precisely because that question is gone.
    # The gate is still green and it is still telling the truth; this line is what stops
    # the number being quoted as if the whole fixture stood behind it.
    coverage = (summary.get("agent") or {}).get("route_coverage")
    if coverage is not None and coverage < 1.0:
        print(f"  NOTE  agent.route_coverage {coverage:.3f} — the route rate above was "
              "measured on part of the linked set. Not a gate failure; not a full score.")

    return 1 if failures else 0


def registered_tools(base: str, timeout: float) -> list[str] | None:
    """The tool names the agent is serving RIGHT NOW, fingerprinted into the result.

    None on any failure, and None is not an empty list. An empty list means "every
    recorded tool has been removed", which is a precise and false claim to make about an
    API that simply did not answer. A run against a deployment with the agent layer
    switched off must record that it cannot tell.
    """
    try:
        with httpx.Client(timeout=min(timeout, 30.0)) as client:
            response = client.get(f"{base}/agent/tools")
            if response.status_code != 200:
                return None
            return sorted(t["name"] for t in response.json().get("tools", []))
    except Exception:
        return None


def record_result(
    summary: dict,
    *,
    suite: str,
    provider: str | None,
    base: str,
    duration_s: int,
    gate_applied: bool,
    gate_code: int | None,
    tools: list[str] | None,
    fixtures: dict,
    counts: dict,
    recorded_at: "datetime | None" = None,
    extra_context: dict | None = None,
) -> None:
    """Write this run to `eval_results`, so the score outlives the terminal.

    The per-question responses are stripped before the write: they carry one model answer
    per question, thousands of characters each, and would make the table grow faster than
    the runs it describes while answering nothing the endpoint asks. They stay in the
    `--out` file, which is what re-grading reads.
    """
    # A DEDICATED ENGINE WITH NO POOL, AND THE REASON IS NOT STYLE.
    #
    # `resolve_truths` has already used the shared session inside its own `asyncio.run`.
    # Each `asyncio.run` builds a new event loop and closes it, while the engine's pool
    # keeps the asyncpg connections bound to the first one -- so reusing it here raises
    # `got Future attached to a different loop`, and it raises AFTER the whole suite has
    # run and every model call has been paid for.
    #
    # NullPool means the connection is opened and closed inside this loop and belongs to
    # nothing else. Anything that writes to the database from a second `asyncio.run` in
    # this script needs the same treatment.
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from config import DATABASE_URL

    metrics = {k: v for k, v in summary.items() if not k.startswith("_")}

    async def write() -> int:
        engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                return await eval_results.record(
                    conn,
                    recorded_at=recorded_at or datetime.now(UTC),
                    suite=suite,
                    provider=provider,
                    duration_s=duration_s,
                    gate_applied=gate_applied,
                    gate_passed=None if gate_code is None else gate_code == 0,
                    metrics=metrics,
                    context={
                        "base": base,
                        "tools": tools,
                        "fixtures": fixtures,
                        "counts": counts,
                        "caveat": CAVEAT,
                        **(extra_context or {}),
                    },
                )
        finally:
            await engine.dispose()

    print(f"\nrecorded as eval_results id={asyncio.run(write())} -- GET /evals/latest")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="truths",
                        choices=["truths", "retrieval", "agent", "all"])
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--only", default=None, help="Comma-separated question ids.")
    parser.add_argument("--modes", default=",".join(MODES))
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--provider", default=None, choices=["local", "anthropic"])
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--gate", action="store_true", help="Apply eval/thresholds.yaml.")
    parser.add_argument(
        "--regrade", default=None,
        help="Re-score a stored --out JSON with the CURRENT graders. No model calls. "
             "Holding the responses fixed is the only way to attribute a score change to "
             "the grader rather than to a non-deterministic model.",
    )
    parser.add_argument("--out", default=None,
                        help="Write JSON results. NOT under eval/ — mounted read-only.")
    parser.add_argument(
        "--record-from", default=None, metavar="PATH",
        help="Record a summary written earlier by --out, without re-running anything. "
             "The recovery path for a suite that completed and failed to store its "
             "result: the measurement is already in the file, and re-issuing every model "
             "call to get a row into a table would be paying twice for one measurement.",
    )
    parser.add_argument(
        "--record", action="store_true",
        help="Store this run in eval_results, where GET /evals/latest reads it. Opt-in "
             "rather than default: a result that becomes the deployment's published "
             "score should be a run someone meant to publish.",
    )
    args = parser.parse_args()

    # A PARTIAL RUN MUST NOT BECOME THE PUBLISHED SCORE. `--only` measures the questions
    # it names and reports a rate over that denominator -- 1.000 for a single question,
    # which is a true statement about nothing and reads on a page as a perfect score.
    # Refusing is the whole of the protection: once the row is written the denominator is
    # a number in a database, and no rendering can undo it.
    if args.record and args.only:
        raise SystemExit(
            "REFUSING to --record a --only run: it would publish a rate whose "
            "denominator is a subset nobody chose to measure."
        )

    if args.record_from:
        stored = json.loads(Path(args.record_from).read_text())
        meta = stored.get("_meta") or {}
        # A file with no `_meta` block carries no provenance of its own, so the command
        # line supplies it -- and the row SAYS SO, in `metadata_source`. Silently
        # attributing command-line values to the run would make a recovered result
        # indistinguishable from one the harness described itself.
        # A recovered file dates itself from the RUN, not from the recovery. Using the
        # current time would place the measurement hours after the system state it
        # describes, which is the error `recorded_at` exists to avoid.
        stamped = meta.get("recorded_at")

        # THE GATE IS RE-APPLIED HERE, NOT COPIED FROM THE FILE.
        #
        # Trusting a stored gate code means a file that carries none records
        # `gate_applied: true` beside `gate_passed: null` -- a gate asserted with no
        # verdict behind it. Re-comparing the stored metrics against the CURRENT floors is
        # also the more useful operation, since a floor may have been argued upward since
        # the run happened.
        gate_code = apply_gate(stored) if args.gate else None

        # DENOMINATORS RE-DERIVED FROM THE STORED RESPONSES, not guessed and not skipped.
        #
        # A file with no `_meta` block carries no counts, and a rate without its
        # denominator cannot be compared with anything: 0.805 is 33/41 or 161/200, and the
        # fixture size changes over time. `report_agent` is the same function the live path
        # uses and reads only the stored responses, so re-deriving costs no model call and
        # cannot disagree with the original run.
        #
        # `fixtures` gets only what the file evidences -- the answer count. The routing and
        # retrieval sizes are NOT read off the fixtures on disk: those are the current
        # files, and attributing them to a run that may have used different ones is the
        # quiet substitution `metadata_source` exists to disclose.
        recovered_counts, recovered_fixtures = meta.get("counts") or {}, meta.get("fixtures") or {}
        if not recovered_counts and stored.get("_agent_results"):
            print("\n════ re-deriving counts from the stored responses ════")
            summary_of = report_agent(stored["_agent_results"])
            recovered_counts = {
                "agent": {
                    k: summary_of[k]
                    for k in ("n", "passed", "route_n", "route_linked", "route_errors",
                              "route_error_ids", "route_ok", "fabricated",
                              "decoyed", "unanswerable_n", "by_verdict")
                    if k in summary_of
                }
            }
            recovered_fixtures = {**recovered_fixtures,
                                  "answers": len(stored["_agent_results"])}

        record_result(
            stored,
            recorded_at=datetime.fromisoformat(stamped) if stamped else None,
            suite=meta.get("suite") or args.suite,
            provider=meta.get("provider") or args.provider,
            base=meta.get("base") or args.base,
            duration_s=int(meta.get("duration_s") or 0),
            gate_applied=bool(args.gate),
            gate_code=gate_code,
            tools=meta.get("tools") or registered_tools(args.base, args.timeout),
            fixtures=recovered_fixtures,
            counts=recovered_counts,
            extra_context={
                "recovered_from": args.record_from,
                "metadata_source": "the file" if meta else "the command line",
                "gate_reapplied_at_record_time": bool(args.gate),
                "counts_source": "the file" if (meta.get("counts")) else
                                 "re-derived from _agent_results",
            },
        )
        return 0

    only = {q.strip() for q in args.only.split(",")} if args.only else None
    summary: dict = {}
    fixtures: dict = {}
    counts: dict = {}
    started = time.time()

    if args.suite in ("truths", "agent", "all") or args.regrade:
        answers = load(ANSWERS)
        fixtures["answers"] = len(answers["questions"])
        resolved = asyncio.run(resolve_truths(answers))

    if args.regrade:
        stored = json.loads(Path(args.regrade).read_text())
        previous = stored["_agent_results"] if "_agent_results" in stored else stored
        was = sum(1 for r in previous if r.get("passed"))
        print(f"\n════ regrading {args.regrade} — same responses, current graders ════\n")
        results = regrade(answers, resolved, previous)
        agent_summary = report_agent(results)
        print(f"\nwas {was}/{len(previous)} when the run happened")
        summary["agent"] = _agent_metrics(agent_summary)
        summary["_agent_results"] = results
        code = apply_gate(summary) if args.gate else 0
        if args.out:
            Path(args.out).write_text(json.dumps(summary, indent=2, default=str))
            print(f"\nwrote {args.out}")
        return code

    if args.suite in ("truths", "all"):
        print("\n════ truths ════")
        report_truths(answers, resolved)

    if args.suite in ("retrieval", "all"):
        print("\n════ retrieval ════")
        fixture = load(RETRIEVAL)
        fixtures["retrieval"] = len(fixture["questions"])
        modes = tuple(m.strip() for m in args.modes.split(","))
        by_mode = run_retrieval(args.base, fixture, modes, args.k, args.timeout)
        report_retrieval(by_mode)
        summary["retrieval"] = {
            f"{mode}_{metric}": value
            for mode, agg in by_mode.items()
            for metric, value in (
                ("top1_ideal", agg["top1_ideal"]),
                ("hit_at_5", agg["hit_at"][5]),
                ("mrr", agg["mrr"]),
                ("ndcg_at_5", agg["ndcg_at_5"]),
            )
        }

    if args.suite in ("agent", "all"):
        print("\n════ agent — route AND answer, one response each ════")
        routing = {q["id"]: q for q in load(ROUTING)["questions"]}
        fixtures["routing"] = len(routing)
        results = run_agent(
            args.base, answers, resolved, routing, only, args.timeout, args.provider
        )
        agent_summary = report_agent(results)
        summary["agent"] = _agent_metrics(agent_summary)
        summary["_agent_results"] = results
        # The DENOMINATORS, stored beside the rates they produced. A rate on its own
        # cannot be read six weeks later: 0.750 is 30/40 or 3/4, and the fixture grew by
        # a question between those two runs. `assess` renders these under the score.
        counts["agent"] = {
            k: agent_summary[k]
            for k in (
                "n", "passed", "route_n", "route_linked", "route_errors",
                "route_error_ids", "route_ok", "fabricated", "decoyed",
                "unanswerable_n", "by_verdict",
            )
            if k in agent_summary
        }

    elapsed = int(time.time() - started)
    print(f"\n{elapsed}s\n\n{CAVEAT}")

    code = apply_gate(summary) if args.gate else 0
    # `_meta` travels with the numbers so the file can be recorded later without anyone
    # having to remember which suite produced it. Re-grading reads the stored responses by
    # name and is unaffected; every `_`-prefixed key is stripped before metrics are
    # written.
    summary["_meta"] = {
        "suite": args.suite,
        "provider": args.provider,
        "base": args.base,
        "duration_s": elapsed,
        "gate_applied": args.gate,
        "gate_code": code if args.gate else None,
        "fixtures": fixtures,
        "counts": counts,
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2, default=str))
        print(f"\nwrote {args.out}")
    if args.record:
        record_result(
            summary,
            suite=args.suite,
            provider=args.provider,
            base=args.base,
            duration_s=elapsed,
            gate_applied=args.gate,
            gate_code=code if args.gate else None,
            tools=registered_tools(args.base, args.timeout),
            fixtures=fixtures,
            counts=counts,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
