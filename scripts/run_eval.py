"""The evaluation harness: three suites, one entry point.

    docker compose exec api python /app/scripts/run_eval.py --suite truths
    docker compose exec api python /app/scripts/run_eval.py --suite retrieval
    docker compose exec api python /app/scripts/run_eval.py --suite agent
    docker compose exec api python /app/scripts/run_eval.py --suite all --gate

WHY THIS DID NOT ABSORB `run_routing_eval.py`
----------------------------------------------
m15 shipped `scripts/run_routing_eval.py` and left the merge as an explicit decision for
m16 rather than a guess. The decision, made deliberately:

  - `--suite agent` DOES grade route and answer together, and has to. "The route was
    right and the answer was 4.6x wrong" is a claim about ONE response, and a local 20B
    does not return the same response twice. Two scripts issuing two requests cannot make
    that statement; they can only report two rates that happen to disagree.

  - `run_routing_eval.py` stays, unchanged. It is m15's committed artefact, its fixture
    header records `graded_before_run: true`, and it needs no database — it runs anywhere
    the API runs. Deleting it to avoid two entry points would rewrite the record of what
    m15 measured, which is a worse outcome than one redundant script.

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
from decimal import Decimal
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.evaluation import grading, retrieval as retrieval_metrics, truth  # noqa: E402
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
    """The m15 route rules, applied to a response this script already has.

    Deliberately the same rules as `run_routing_eval.py` rather than an improvement on
    them. A test asserts the two agree; the moment this file starts grading routes
    differently, the m15 numbers stop being comparable with the m16 ones.
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
                results.append(
                    {
                        "id": question["id"],
                        "verdict": "error",
                        "passed": False,
                        "reasons": [error],
                        "elapsed_ms": elapsed,
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

    linked = [r for r in results if r.get("routing_id")]
    route_ok = sum(1 for r in linked if r.get("route_ok"))
    disagreements = [r for r in linked if r.get("route_ok") and not r.get("passed")]

    print(f"\nanswers  {passed}/{n}")
    for verdict, count in sorted(by_verdict.items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:18} {count}")
    if linked:
        print(f"\nroutes   {route_ok}/{len(linked)} on the {len(linked)} questions linked to routing.yaml")
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
    # THE ONE ROUTE THAT IS A PROPERTY RATHER THAN A RATE. R-01 is the m14 injection
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
        "route_n": len(linked),
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
    return 1 if failures else 0


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
    args = parser.parse_args()

    only = {q.strip() for q in args.only.split(",")} if args.only else None
    summary: dict = {}
    started = time.time()

    if args.suite in ("truths", "agent", "all") or args.regrade:
        answers = load(ANSWERS)
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
        results = run_agent(
            args.base, answers, resolved, routing, only, args.timeout, args.provider
        )
        agent_summary = report_agent(results)
        summary["agent"] = _agent_metrics(agent_summary)
        summary["_agent_results"] = results

    print(f"\n{time.time() - started:.0f}s\n\n{CAVEAT}")

    code = apply_gate(summary) if args.gate else 0
    if args.out:
        Path(args.out).write_text(json.dumps(summary, indent=2, default=str))
        print(f"\nwrote {args.out}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
