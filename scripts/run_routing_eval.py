"""Grade POST /agent/query against eval/golden/routing.yaml.

    python scripts/run_routing_eval.py [--base http://localhost:8000] [--out results.json]
    python scripts/run_routing_eval.py --only R-01,R-11 --max-steps 6

WHAT IT GRADES, AND WHY IT IS NOT ANSWER QUALITY
------------------------------------------------
This scores ROUTE, not prose. For each question the fixture records the tools that must
be called and the tools whose use is a failure, and the run is graded on those plus the
outcome. Whether the sentence reads well is m16's problem; whether a `COUNT(*)` question
reached SQL instead of a vector index is this milestone's, and it is the one that decides
whether the m14 injection finding was actually mitigated.

Deliberately a separate script from m16's `scripts/run_eval.py`, which does not exist
yet. m16 extends `eval/golden/retrieval.yaml` from 10 questions to 60 and adds ANSWER
grading; this file is the routing half and is complete on its own. Merging them is m16's
decision to make once both exist, not a guess made here.

THE GRADE IS NOT A PERCENTAGE ANYONE SHOULD QUOTE
--------------------------------------------------
n=14, hand-written, by the author of the tools. It detects a regression and demonstrates
a mechanism. It does not establish a routing accuracy rate, and the summary line says so
every time it runs so that nobody lifts the number out of context later.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "eval" / "golden" / "routing.yaml"


def grade(question: dict, response: dict | None, error: str | None) -> dict:
    """Score one question. Returns the verdict and every reason behind it.

    A pass requires ALL of: the run finished in an acceptable outcome, every expected
    tool was called, and no forbidden tool was. Partial credit is deliberately not
    offered -- "it called the right tool and also asked the corpus" is the exact failure
    the routing layer exists to prevent, and a scheme that awards it 0.5 hides that.
    """
    reasons: list[str] = []
    if error is not None:
        return {"verdict": "error", "reasons": [error], "called": [], "categories": []}

    called = [
        call["name"]
        for step in response["steps"]
        for call in step.get("tool_calls", [])
    ]
    categories = response.get("categories", [])
    outcome = response["outcome"]
    route = question["route"]

    expected = set(question.get("expect_tools") or [])
    forbidden = set(question.get("forbid_tools") or [])

    missing = expected - set(called)
    if missing:
        reasons.append(f"never called {sorted(missing)}")
    used_forbidden = forbidden & set(called)
    if used_forbidden:
        reasons.append(f"called forbidden {sorted(used_forbidden)}")

    if route == "refuse":
        # Graded on the OUTCOME alone. R-12 explicitly permits calling the history tool
        # first and then declining -- what is wrong there is answering with a number, not
        # looking. `max_steps` is not a refusal: it is a run that ran out of room.
        if outcome not in ("refused",):
            reasons.append(f"should have refused, outcome was {outcome!r}")
    else:
        if outcome not in ("answered",):
            reasons.append(f"expected an answer, outcome was {outcome!r}")

    return {
        "verdict": "pass" if not reasons else "fail",
        "reasons": reasons,
        "called": called,
        "categories": categories,
        "outcome": outcome,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument(
        "--out", default=None,
        help="Write full results as JSON. NOT under eval/ -- that directory is "
             "mounted read-only in the api container on purpose, so a container "
             "cannot rewrite a fixture that was graded before its run.",
    )
    parser.add_argument("--only", default=None, help="Comma-separated question ids.")
    parser.add_argument("--provider", default=None, choices=["local", "anthropic"])
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument(
        "--timeout", type=float, default=600.0,
        help="Per question. A local 20B is 7-21 s PER TURN and a run is several turns.",
    )
    args = parser.parse_args()

    fixture = yaml.safe_load(FIXTURE.read_text())
    questions = fixture["questions"]
    if args.only:
        wanted = {q.strip() for q in args.only.split(",")}
        questions = [q for q in questions if q["id"] in wanted]

    if not fixture.get("graded_before_run"):
        print("REFUSING: the fixture is not marked graded_before_run.", file=sys.stderr)
        return 2

    results = []
    started = time.time()
    print(f"{len(questions)} questions against {args.base}\n")

    with httpx.Client(timeout=args.timeout) as client:
        for question in questions:
            payload = {"q": question["text"]}
            if args.provider:
                payload["provider"] = args.provider
            if args.max_steps:
                payload["max_steps"] = args.max_steps

            mark = time.time()
            response = error = None
            try:
                raw = client.post(f"{args.base}/agent/query", json=payload)
                if raw.status_code != 200:
                    error = f"HTTP {raw.status_code}: {raw.text[:200]}"
                else:
                    response = raw.json()
            except Exception as exc:  # network, timeout, malformed body
                error = f"{type(exc).__name__}: {exc}"
            elapsed = int((time.time() - mark) * 1000)

            verdict = grade(question, response, error)
            results.append(
                {
                    "id": question["id"],
                    "text": question["text"],
                    "route": question["route"],
                    "elapsed_ms": elapsed,
                    **verdict,
                    "answer": (response or {}).get("answer"),
                    "warnings": (response or {}).get("grounding_warnings", []),
                    "run_id": (response or {}).get("run_id"),
                }
            )
            mark_char = {"pass": "PASS", "fail": "FAIL", "error": "ERR "}[verdict["verdict"]]
            print(
                f"  {mark_char} {question['id']}  {question['route']:6} "
                f"{elapsed / 1000:6.1f}s  {'+'.join(verdict['categories']) or '-':16} "
                f"{'; '.join(verdict['reasons'])}"
            )

    passed = sum(1 for r in results if r["verdict"] == "pass")
    by_route: dict[str, list] = {}
    for result in results:
        by_route.setdefault(result["route"], []).append(result["verdict"] == "pass")

    print(f"\n{passed}/{len(results)} passed in {time.time() - started:.0f}s")
    for route, verdicts in sorted(by_route.items()):
        print(f"  {route:6} {sum(verdicts)}/{len(verdicts)}")
    warned = sum(1 for r in results if r["warnings"])
    print(f"  runs with grounding warnings: {warned}/{len(results)}")
    print(
        "\nn=14, hand-written, one author. This detects a regression and demonstrates a "
        "mechanism.\nIt does NOT establish a routing accuracy rate -- do not quote it as "
        "one."
    )

    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2, default=str))
        print(f"\nwrote {args.out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
