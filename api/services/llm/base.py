"""The provider interface, and the value types that cross it.

Two backends -- a local 20B over Ollama and claude-opus-5 over the Anthropic API --
behind one interface. The point is not portability for its own sake. It is that m16 can
run the same golden set through both and compare answer quality, cost and latency on
identical inputs, and that comparison is only worth anything if the code on either side
of the provider is byte-identical. The interface is what makes that true.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
`stream()`. IMPLEMENTATION-PLAN.md §4.1 lists it alongside `complete()` and
`complete_structured()`, and m14 does not need it: /ask returns one validated JSON
object, and there is nothing to stream a partial JSON object to. m17's voice path is
what needs streaming, and it needs first-token latency and sentence-boundary chunking
that no /ask caller would exercise. Declaring an unimplemented method now would make
`isinstance`-style conformance checks pass against providers that cannot do it -- an
interface that lies is worse than one that grows.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class LLMError(RuntimeError):
    """Generation could not run, or ran and produced something unusable.

    Carries an HTTP status so the router does not have to re-classify the cause.
    503 = the provider is down, unconfigured, or disabled; 422 = the caller's request
    cannot be served (over budget); 502 = the provider answered and the answer was not
    what it promised.
    """

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Usage:
    """Token counts as the PROVIDER reported them, never as we estimated them.

    The two cache fields are Anthropic-specific and stay zero on the local provider.
    They are on the shared type rather than in a provider-specific bag because the
    cost table in pricing.py has to price them, and a field that is sometimes absent
    turns every cost calculation into a `getattr` with a default -- which is how a
    cache that silently stopped working goes unnoticed.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_input_tokens
            + self.cache_creation_input_tokens
        )


@dataclass(frozen=True)
class LLMResponse:
    """One completed call. Everything needed to price it, time it and trace it.

    `text` is the raw response body -- for structured calls, the JSON string. Parsing
    happens one layer up, in services/ask.py, so that a provider is never in a position
    to decide what a valid answer looks like.
    """

    text: str
    usage: Usage
    provider: str
    model: str
    latency_ms: int
    stop_reason: str | None = None
    request_id: str | None = None
    # Attempts that produced invalid JSON before this one. 0 on the happy path.
    repair_attempts: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@runtime_checkable
class LLMProvider(Protocol):
    """What /ask requires of a backend. Two methods, both awaited.

    `complete_structured` takes a JSON Schema and MUST return text that parses as JSON
    matching it, or raise. How it gets there is the provider's business: Anthropic has
    a first-party structured-output path, Ollama has constrained decoding plus a capped
    repair loop, and a third backend might have neither and need a different trick
    entirely. The caller's contract is the same in all three cases.
    """

    name: str
    model: str

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        effort: str = "medium",
    ) -> LLMResponse: ...

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        schema_name: str,
        max_tokens: int,
        effort: str = "medium",
        validate: Callable[[str], None] | None = None,
    ) -> LLMResponse: ...
        # `validate` is the caller's definition of valid, injected rather than assumed.
        # The provider owns the RETRY MECHANICS -- how many attempts, what to send back,
        # what to log -- and the caller owns what counts as a valid answer. Without the
        # injection the provider would have to import the answer model, and a backend
        # would then know what a GroundedAnswer is, which is exactly the coupling this
        # interface exists to prevent.
        #
        # It repairs SHAPE only. Grounding failures are rejected in services/ask.py and
        # never retried; see local_provider.complete_structured for why.
