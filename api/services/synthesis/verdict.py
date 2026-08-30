"""What happened on the final turn, and what to say when it produced nothing.

Everything here is a pure function over one turn's shape. No database, no provider, no
clock. `census.py` counts how often each case occurs; this module decides what each case
means and what the run should carry instead of a null.

THE DISCRIMINATOR ALREADY EXISTED AND WAS BEING THROWN AWAY
------------------------------------------------------------
The handoff's open question asked whether a blank answer is a max-token truncation, a
final-turn parse failure, or the provider returning an empty message, and said nothing
distinguishes them. Something does: `finish_reason`. It arrives on every response, is
carried as `LLMResponse.stop_reason` and copied onto `AgentStep.stop_reason`, and is then
dropped -- `llm_calls` has no column for it and neither does `agent_runs`. It lived in
memory for the length of one request, which is why the question stood for three milestones.

Measured on 2026-08-30 by wrapping the provider and replaying both populations:

    finish_reason='length', out=1200 of 1200, reasoning=4906 chars, content=0
        -> the whole per-turn budget was spent in the REASONING channel and the model
           never reached the content channel. Not a parse failure: there was nothing to
           parse.

    finish_reason='stop',   out=14,           reasoning=0 chars,    content=0
        -> the model stopped voluntarily, having emitted nothing anywhere. A genuinely
           empty completion.

Two causes, not one, and they need different handling and different words.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

#: `finish_reason` values that mean the model was cut off mid-generation. Ollama reports
#: `length`; the Anthropic SDK reports `max_tokens`. Both are the same event and both are
#: matched, because a rule that only holds on the provider you happened to test with is a
#: rule that fails on the first day of the other one.
TRUNCATION_REASONS: frozenset[str] = frozenset({"length", "max_tokens"})

Diagnosis = Literal[
    "answered",
    "truncated_before_answering",
    "stopped_without_answering",
]


@dataclass(frozen=True)
class FinalTurn:
    """The shape of the turn the executor treated as the answer.

    `reasoning_chars` rather than the reasoning text itself, deliberately. The reasoning
    channel is the model's working-out; it is not an answer, it has not been through the
    number verification in `executor.verify_numbers`, and a salvage path that pasted it
    into `answer` would be publishing an unverified draft as a result. The LENGTH is
    evidence about what happened. The CONTENT is not evidence about Dubai.
    """

    text: str | None
    output_tokens: int
    max_output_tokens: int
    stop_reason: str | None = None
    reasoning_chars: int = 0
    tool_calls: int = 0

    @property
    def has_answer(self) -> bool:
        return bool((self.text or "").strip())

    @property
    def hit_the_cap(self) -> bool:
        """Truncated, by either signal, and `finish_reason` is only one of them.

        The token count is checked as well because it is the signal that survives in the
        database: `llm_calls.output_tokens` is stored and `finish_reason` is not, so the
        census of the 213 runs already on disk has nothing else to go on. Where both are
        available they agreed on every run measured.
        """
        by_reason = (self.stop_reason or "").lower() in TRUNCATION_REASONS
        by_tokens = (
            self.max_output_tokens > 0 and self.output_tokens >= self.max_output_tokens
        )
        return by_reason or by_tokens


@dataclass(frozen=True)
class Finding:
    """One thing a tool actually returned, for the salvage message to list."""

    tool: str
    category: str
    ok: bool = True


@dataclass(frozen=True)
class Verdict:
    diagnosis: Diagnosis
    answer: str | None
    #: For an operator, not for the person who asked the question.
    explanation: str
    #: Whether a different final turn could plausibly succeed. NOT whether to retry the
    #: same one -- see `retry_would_help`.
    recoverable: bool
    remedy: str | None = None
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def is_answer(self) -> bool:
        return self.diagnosis == "answered"


def retry_would_help(turn: FinalTurn, *, temperature: float) -> bool:
    """Whether re-issuing THE SAME final turn could produce a different result.

    It could not, at temperature 0, and this is the rule that kills the obvious fix. Plan
    §12.4 offers "retry the final synthesis turn" as one option; with deterministic
    decoding and an unchanged context, the retry returns the identical empty message and
    the run has spent another 30 seconds to arrive back where it was.

    A truncation is the exception, and only because the retry is not the same call: raising
    the cap changes the request. Anything else needs a different prompt, not a second
    attempt at the same one.
    """
    if turn.has_answer:
        return False
    if turn.hit_the_cap:
        return True
    return temperature > 0


def _describe(findings: Sequence[Finding]) -> str:
    """List what was gathered, and nothing more.

    THE SALVAGE MESSAGE REPORTS EVIDENCE AND NEVER DRAWS THE CONCLUSION. A function here
    that read four `area_price_history` payloads and wrote "Al Wasl grew fastest" would be
    inventing an answer the model never produced -- the same sin as computing a rate in the
    browser, one layer down, and worse because it would be indistinguishable from a real
    answer. So this names the tools that ran and stops.
    """
    successful = [f for f in findings if f.ok]
    if not successful:
        return "No tool returned a usable result."
    names = ", ".join(sorted({f.tool for f in successful}))
    return (
        f"{len(successful)} tool result(s) were gathered successfully "
        f"({names}) and are attached to this run."
    )


def assess(
    turn: FinalTurn,
    *,
    findings: Sequence[Finding] = (),
    temperature: float = 0.0,
) -> Verdict:
    """Classify the final turn and, when it produced nothing, say so honestly.

    THE OUTCOME LABEL IS NOT CHANGED HERE, and that is deliberate. A fifth `agent_runs`
    outcome would move these rows out of `answered`, and `observability.queries` counts
    `answered_empty` precisely to watch this population -- relabelling would zero that
    metric by moving the rows rather than by fixing the bug. The fix is that the run stops
    being blank: `answer` becomes an honest sentence instead of NULL, and
    `answered_empty` then falls to zero because there are no empty answers left.
    """
    if turn.tool_calls:
        raise ValueError(
            "assess() takes the FINAL turn, and a turn that requested tools is not one. "
            "The executor only stops when `not response.wants_tools`."
        )

    if turn.has_answer:
        return Verdict(
            diagnosis="answered",
            answer=turn.text,
            explanation="the final turn produced an answer",
            recoverable=False,
            findings=tuple(findings),
        )

    evidence = _describe(findings)

    if turn.hit_the_cap:
        return Verdict(
            diagnosis="truncated_before_answering",
            answer=(
                "I gathered the data but ran out of room before I could write the "
                f"summary. {evidence} Ask again, or ask a narrower question."
            ),
            explanation=(
                f"the final turn stopped at {turn.output_tokens} of "
                f"{turn.max_output_tokens} output tokens with "
                f"{turn.reasoning_chars} characters of reasoning and none of answer -- "
                f"the per-turn budget was consumed before the model reached its "
                f"conclusion"
            ),
            recoverable=True,
            # NOT simply "raise the budget", and this was measured rather than assumed.
            # Replaying the same question at 3,000 tokens on 2026-08-30 did not produce an
            # answer: turns 1 and 2 replayed identically (temperature 0) and turn 3 hit the
            # provider's 120 s client timeout while generating, so the run ended `failed`
            # with partial findings instead of blank. Raising the cap on this stack trades
            # a blank answer for a timeout. The remedy therefore names both levers and
            # commits to neither.
            remedy=(
                "give the synthesis turn a larger budget than the tool-selection turns, "
                "or reduce what the model must reason over before it answers. Raising the "
                "cap alone is not enough on a local model: at 3,000 tokens the same "
                "question timed out mid-generation instead"
            ),
            findings=tuple(findings),
        )

    # Everything else: the model ended the turn of its own accord and said nothing.
    # `stop`, an unrecognised reason and a missing one all land here on purpose -- the
    # observable fact is the same, and inventing a third label for "the provider did not
    # tell us why" would be a distinction with no evidence behind it.
    return Verdict(
        diagnosis="stopped_without_answering",
        answer=(
            "I gathered the data but could not write the summary. "
            f"{evidence} Ask again, or ask a narrower question."
        ),
        explanation=(
            f"the final turn ended after {turn.output_tokens} output token(s) with no "
            f"answer text and no tool call, reporting stop_reason="
            f"{turn.stop_reason!r} -- the model stopped rather than being cut off"
        ),
        recoverable=temperature > 0,
        remedy=(
            "at temperature 0 a retry is deterministic and returns the same empty "
            "message; the final turn needs a different prompt, not a second attempt"
        ),
        findings=tuple(findings),
    )
