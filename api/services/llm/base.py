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

GROWN IN m15: complete_with_tools()
-----------------------------------
The sentence above said an interface is better grown than lied to, and m15 is that
growth. `complete_with_tools` is added HERE, on the Protocol, rather than in the agent
package dispatching on `provider.name`, because dispatching on a provider's name string
is precisely what a Protocol exists to prevent -- it would put Ollama's wire format
inside the orchestration layer and make the m16 provider comparison compare two
different code paths.

Unlike `stream()`, this method has two real implementations on the day it is declared,
which is the condition the paragraph above set. The two wire formats differ a great deal
(OpenAI-style `tool_calls` with a JSON-string argument blob; Anthropic-style `tool_use`
content blocks with parsed input), and every bit of that difference is absorbed by the
providers. The caller sees `ToolSpec` in and `ToolCall` out.
"""

from collections.abc import Callable, Sequence
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
class ToolSpec:
    """One tool, described once, in neither provider's dialect.

    `parameters` is a STRICT JSON Schema -- every property required,
    `additionalProperties: false` -- produced by the same `strict_json_schema` helper
    that builds the /ask answer schema. Both backends constrain generation against it,
    so argument validation is a guarantee rather than a defensive parse.

    `description` is not documentation. It is the text the model reads when deciding
    whether this tool is the right one, and it is where routing is actually enforced --
    far more cheaply than in a system prompt that has to describe every tool at once.
    """

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """A tool the model asked for, with its arguments already parsed.

    `id` is the provider's correlation id and it is opaque. It must be echoed back on the
    matching result: a result with no id, or an id that matches no call, is a malformed
    request on both backends -- and on Anthropic a `tool_use` block with no corresponding
    `tool_result` is a 400, not a warning.
    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """What a tool returned, on its way back to the model.

    `is_error` is a first-class field rather than an error string convention. A tool that
    raised must still produce a result block -- dropping it leaves a `tool_use` with no
    answer, which fails the request rather than the tool -- and the model needs to know
    the difference between "no rows matched" and "this blew up", because only one of
    those is worth retrying with different arguments.
    """

    call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Exchange:
    """One assistant turn that requested tools, and the results that answered it.

    The conversation is carried as a list of these rather than as a list of
    provider-shaped messages. That keeps the executor free of any wire format: it appends
    (what the model said, what the tools returned) and hands the whole list back on the
    next call, and each provider serialises it into its own dialect.

    It also makes the parallel-call rule structural rather than remembered. All results
    for one assistant turn live in ONE Exchange, so they are always sent together; a
    provider cannot accidentally split them across turns, which is the mistake that
    teaches a model to stop making parallel calls and quietly doubles latency over time.
    """

    response: "LLMResponse"
    results: tuple[ToolResult, ...]


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
    # Tools the model asked for. Empty on every m14 call path, which is why it is
    # defaulted -- adding it did not change a single existing construction site.
    tool_calls: tuple[ToolCall, ...] = ()

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


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

    async def complete_with_tools(
        self,
        *,
        system: str,
        user: str,
        tools: Sequence[ToolSpec],
        exchanges: Sequence[Exchange] = (),
        max_tokens: int,
        effort: str = "medium",
    ) -> LLMResponse: ...
        # ONE TURN, not a loop. The provider makes a single call and returns whatever
        # came back -- either a final answer, or `tool_calls` asking for more.
        #
        # The loop lives in services/agent/executor.py, deliberately. Both SDKs offer a
        # runner that would drive it (`client.beta.messages.tool_runner` on Anthropic),
        # and taking it would mean the local and hosted paths ran DIFFERENT loops with
        # different step accounting, different caps and different recovery. m16's whole
        # job is to compare those two providers on one golden set, and that comparison is
        # worth nothing if the orchestration differs between them. One loop, two
        # providers, one set of numbers.
        #
        # `exchanges` carries the conversation so far. It is empty on the first call.
