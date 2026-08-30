"""Request and response shapes for `POST /agent/query`.

The response is deliberately verbose, and for the same reason `/ask` returns its
contexts: an orchestrated answer that shows only its conclusion cannot be audited by the
person reading it. `/ask` had one step to expose. This has up to eight, and the
interesting failures live between them -- a tool called with a name that resolved to the
wrong place, a refusal the model talked itself out of, a number that appeared in the
prose and in no tool result.

Every step is returned with its arguments, its result, its latency and its cost. That is
the observability the plan asks for in §4.5, and it is also the only way to tell an agent
that reasoned from an agent that guessed and got lucky.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

Outcome = Literal["answered", "refused", "max_steps", "failed"]


class ToolInvocation(BaseModel):
    """One tool call and what came back from it."""

    step: int
    name: str
    category: str = Field(
        ...,
        description="sql | rag | geo | meta. What eval/golden/routing.yaml grades "
        "against: a numeric question answered entirely from `rag` is a routing failure "
        "even when the prose reads correctly.",
    )
    arguments: dict[str, Any]
    ok: bool = Field(
        ..., description="False when the tool declined or raised. The run continues."
    )
    duration_ms: int
    result: str = Field(
        ...,
        description="The serialised result, exactly as the model received it -- "
        "truncation marker included. Not a summary of it.",
    )
    repeated: bool = Field(
        False,
        description="This tool was called with these exact arguments earlier in the "
        "run. The call was NOT executed again; the model was told so. See the executor.",
    )


class AgentStep(BaseModel):
    """One turn of the loop: what the model was asked, and what it decided."""

    step: int
    text: str | None = Field(
        None, description="Prose the model produced on this turn, if any."
    )
    tool_calls: list[ToolInvocation] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    latency_ms: int = 0
    stop_reason: str | None = None


class AgentUsage(BaseModel):
    steps: int
    tool_calls: int
    tool_errors: int
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = Field(
        None, description="Null when no model in the run was priced. Not zero."
    )
    cost_priced: bool


class AgentTimings(BaseModel):
    generate: int = Field(0, description="Summed across every turn.")
    tools: int = Field(0, description="Summed across every tool call.")
    total: int


class AgentResponse(BaseModel):
    question: str
    run_id: str
    provider: str
    model: str
    outcome: Outcome = Field(
        ...,
        description="answered | refused | max_steps | failed. `refused` is a SUCCESS: "
        "some questions have no answer in this data, and reporting that as a fault "
        "makes the refusal rate uncollectable. `max_steps` means the findings below are "
        "PARTIAL.",
    )
    answered: bool
    answer: str | None
    categories: list[str] = Field(
        default_factory=list,
        description="Tool categories the run used, in first-use order.",
    )
    steps: list[AgentStep]
    grounding_warnings: list[str] = Field(
        default_factory=list,
        description="What did not hold: numbers in the answer that appear in no tool "
        "result, a currency the tools never reported, a refusal that was overridden.",
    )
    usage: AgentUsage
    timings_ms: AgentTimings
