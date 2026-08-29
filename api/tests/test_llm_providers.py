"""The generation layer's provider abstraction: registry, schema, pricing, both backends.

Every test here runs with NO model, NO network and NO API key. That is the point of the
split -- the parts of an LLM application that can be pinned exactly (which provider gets
built, what the schema looks like, what a call costs, what happens when the JSON is
malformed) should not require a 13 GB model to be resident before they can fail.

The two backends are exercised through a fake transport and a fake client rather than
through mocks of their own methods, so the code under test is the real request assembly
and the real response unpacking. A mock of `complete_structured` would assert only that
the test knows what it patched.
"""

import json

import pytest

from models.ask import Citation, GroundedAnswer
from services.llm import pricing, registry
from services.llm.anthropic_provider import AnthropicProvider
from services.llm.base import LLMError, LLMProvider, LLMResponse, Usage
from services.llm.local_provider import OllamaProvider
from services.llm.schema import strict_json_schema


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.reset()
    yield
    registry.reset()


# ── registry ────────────────────────────────────────────────────────────────


def test_provider_none_is_a_configuration_not_a_crash():
    """LLM_PROVIDER=none must fail cleanly and say so.

    A machine that cannot host a 13 GB model still serves this platform's 30 REST
    operations and still serves /search. The generation layer being off is a deployment
    choice, and the error names the alternative rather than leaving someone to grep.
    """
    with pytest.raises(LLMError) as exc:
        registry.get_provider("none")
    assert exc.value.status_code == 503
    assert "disabled" in str(exc.value)


def test_an_unrecognised_provider_lists_the_ones_that_work():
    with pytest.raises(LLMError) as exc:
        registry.get_provider("openai")
    assert "'local'" in str(exc.value) and "'anthropic'" in str(exc.value)


def test_local_is_the_default_and_needs_no_key():
    provider = registry.get_provider("local")
    assert isinstance(provider, OllamaProvider)
    assert provider.name == "local"


def test_the_instance_is_cached_but_not_across_a_switch():
    """Cached because building the Anthropic client opens a pool, and because two /ask
    calls in one eval run must go to the same place."""
    first = registry.get_provider("local")
    assert registry.get_provider("local") is first
    assert registry.get_provider("anthropic") is not first


def test_both_providers_satisfy_the_protocol():
    assert isinstance(OllamaProvider(), LLMProvider)
    assert isinstance(AnthropicProvider(api_key="x"), LLMProvider)


# ── schema normalisation ────────────────────────────────────────────────────


def test_the_answer_schema_is_self_contained():
    """No $ref, no $defs.

    Constrained decoders have to compile the schema into a grammar and support for
    local references ranges from complete to absent depending on the runtime. Inlining
    costs a few duplicated bytes and removes the question.
    """
    blob = json.dumps(strict_json_schema(GroundedAnswer))
    assert "$ref" not in blob
    assert "$defs" not in blob


def test_every_property_is_required_and_nothing_extra_is_allowed():
    """What OpenAI-style `strict: true` demands, and what we want anyway.

    A field with a default is optional in plain JSON Schema. Here `unanswerable_reason`
    must be present and explicitly null -- the model asserting "this IS answerable" is a
    claim, and an absent key is silence.
    """
    schema = strict_json_schema(GroundedAnswer)
    assert set(schema["required"]) == set(schema["properties"])
    assert "unanswerable_reason" in schema["required"]
    assert schema["additionalProperties"] is False
    item = schema["properties"]["citations"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == {"chunk_id", "quote"}


def test_nullable_fields_become_a_type_union_not_an_anyOf():
    """`{"type": ["string", "null"]}` is understood by strictly more decoders than
    `anyOf: [{string}, {null}]`, and it is the same schema."""
    schema = strict_json_schema(GroundedAnswer)
    assert schema["properties"]["unanswerable_reason"]["type"] == ["string", "null"]
    assert "anyOf" not in schema["properties"]["unanswerable_reason"]


def test_field_descriptions_survive_because_they_are_part_of_the_prompt():
    """The descriptions are shipped to the model inside the schema. Stripping them as
    'documentation' would silently delete prompt text."""
    schema = strict_json_schema(GroundedAnswer)
    assert "VERBATIM" in schema["properties"]["citations"]["items"]["properties"]["quote"]["description"]


# ── pricing ─────────────────────────────────────────────────────────────────


def test_cost_is_computed_from_the_rate_table():
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert pricing.cost_usd("claude-opus-5", usage) == pytest.approx(30.00)


def test_cached_reads_are_priced_separately_from_fresh_input():
    """If a cache read cost the same as fresh input there would be no point caching, and
    a cost report that prices them identically cannot show the saving."""
    fresh = Usage(input_tokens=1_000_000)
    cached = Usage(cache_read_input_tokens=1_000_000)
    assert pricing.cost_usd("claude-opus-5", cached) < pricing.cost_usd(
        "claude-opus-5", fresh
    )


def test_an_unpriced_model_costs_None_and_not_zero():
    """Zero means 'no per-token billing relationship exists'. None means 'nobody has
    priced this'. Collapsing them makes an unknown look like a bargain."""
    usage = Usage(input_tokens=1000, output_tokens=1000)
    assert pricing.cost_usd("some-model-nobody-priced", usage) is None
    assert pricing.cost_usd("gpt-oss:20b", usage) == 0.0


def test_a_quantised_tag_prices_like_its_base_model():
    assert pricing.rate_for("gpt-oss:20b-q4_K_M") is not None


# ── the local provider ──────────────────────────────────────────────────────


def _ollama_body(content: str, prompt_tokens: int = 100, completion_tokens: int = 20):
    return {
        "id": "chatcmpl-1",
        "model": "gpt-oss:20b",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content},
             "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


VALID_ANSWER = json.dumps(
    {"answer": "a", "citations": [], "confidence": "high", "unanswerable_reason": None}
)


class _ScriptedOllama(OllamaProvider):
    """Replays a list of response bodies. Everything above `_post` is the real code."""

    def __init__(self, bodies, **kwargs):
        super().__init__(**kwargs)
        self.bodies = list(bodies)
        self.payloads = []

    async def _post(self, payload):
        self.payloads.append(payload)
        return self.bodies.pop(0), 5


async def test_a_valid_structured_response_needs_no_repair():
    provider = _ScriptedOllama([_ollama_body(VALID_ANSWER)])
    response = await provider.complete_structured(
        system="s", user="u", schema={"type": "object"}, schema_name="x", max_tokens=100
    )
    assert response.repair_attempts == 0
    assert response.usage.input_tokens == 100
    assert json.loads(response.text)["confidence"] == "high"


async def test_the_repair_loop_feeds_the_error_back_and_is_capped():
    """Two things at once, because they are the same mechanism.

    A retry that re-sends an identical prompt at temperature 0 gets an identical answer,
    so the failed output and the validation error go back as the next turn. And the loop
    stops: an uncapped repair loop is how one question quietly becomes forty requests.
    """
    provider = _ScriptedOllama(
        [_ollama_body("not json at all"), _ollama_body(VALID_ANSWER)],
        repair_attempts=2,
    )
    response = await provider.complete_structured(
        system="s", user="u", schema={"type": "object"}, schema_name="x", max_tokens=100
    )
    assert response.repair_attempts == 1

    second = provider.payloads[1]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert "not json at all" == second[2]["content"]
    assert "did not validate" in second[3]["content"]


async def test_the_cap_is_enforced_and_the_error_says_what_the_cap_was():
    provider = _ScriptedOllama([_ollama_body("{{{")] * 3, repair_attempts=2)
    with pytest.raises(LLMError) as exc:
        await provider.complete_structured(
            system="s", user="u", schema={"type": "object"}, schema_name="x",
            max_tokens=100,
        )
    assert exc.value.status_code == 502
    assert "3 attempts" in str(exc.value)
    assert not provider.bodies  # all three were used, and no fourth was attempted


async def test_the_callers_validator_drives_the_loop_not_json_validity_alone():
    """Well-formed JSON that is the WRONG SHAPE must also trigger a repair.

    `{"nope": 1}` parses. If only json.loads gated the loop, a response that satisfies no
    schema at all would be returned as a success and blow up one layer higher, where the
    error would name the answer model instead of the provider.
    """
    provider = _ScriptedOllama(
        [_ollama_body('{"nope": 1}'), _ollama_body(VALID_ANSWER)], repair_attempts=1
    )

    def validate(payload):
        GroundedAnswer.model_validate_json(payload)

    response = await provider.complete_structured(
        system="s", user="u", schema={"type": "object"}, schema_name="x",
        max_tokens=100, validate=validate,
    )
    assert response.repair_attempts == 1


async def test_a_reasoning_field_is_not_concatenated_into_the_json():
    """gpt-oss returns chain-of-thought in `reasoning`, beside `content`.

    Joining them would prepend prose to the JSON body and produce a parse error that
    points at the schema -- the wrong place to go looking, and an expensive detour.
    """
    body = _ollama_body(VALID_ANSWER)
    body["choices"][0]["message"]["reasoning"] = "Let me think about this at length."
    provider = _ScriptedOllama([body])
    response = await provider.complete_structured(
        system="s", user="u", schema={"type": "object"}, schema_name="x", max_tokens=100
    )
    assert response.text == VALID_ANSWER
    assert "think about this" in response.raw["reasoning"]


async def test_an_unreachable_ollama_names_the_host_problem():
    """From inside the api container `localhost` is the container, not the Mac. The
    message has to say that, or the next hour goes into the wrong place.

    A real connection to a port nothing listens on, not a mocked transport: the thing
    under test is httpx's exception being mapped to a 503 with a useful message, and a
    mock that raises ConnectError on command would assert only that the test knows which
    exception to raise.
    """
    provider = OllamaProvider(base_url="http://127.0.0.1:1", timeout_s=2)
    with pytest.raises(LLMError) as exc:
        await provider.complete(system="s", user="u", max_tokens=10)
    assert exc.value.status_code == 503
    assert "HOST" in str(exc.value)


async def test_the_structured_payload_carries_the_named_schema_envelope():
    """Ollama's OpenAI-compatible endpoint wants the schema wrapped and named. Anthropic
    wants it bare. The interface carries the name because one backend needs it."""
    provider = _ScriptedOllama([_ollama_body(VALID_ANSWER)])
    await provider.complete_structured(
        system="s", user="u", schema={"type": "object"}, schema_name="grounded",
        max_tokens=10,
    )
    fmt = provider.payloads[0]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "grounded"
    assert fmt["json_schema"]["strict"] is True
    assert provider.payloads[0]["temperature"] == 0


# ── the anthropic provider ──────────────────────────────────────────────────


class _Block:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class _FakeUsage:
    input_tokens = 1200
    output_tokens = 300
    cache_read_input_tokens = 900
    cache_creation_input_tokens = 0


class _FakeMessage:
    model = "claude-opus-5"
    stop_reason = "end_turn"
    usage = _FakeUsage()
    _request_id = "req_abc"

    def __init__(self, blocks):
        self.content = blocks


class _FakeMessages:
    def __init__(self, message):
        self.message = message
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.message


class _FakeClient:
    def __init__(self, message):
        self.messages = _FakeMessages(message)


async def test_thinking_blocks_are_dropped_from_the_answer_text():
    """With adaptive thinking the content list carries ThinkingBlocks too. Joining every
    block's text prepends a reasoning trace to the JSON body."""
    client = _FakeClient(
        _FakeMessage([_Block("thinking", "hmm"), _Block("text", VALID_ANSWER)])
    )
    provider = AnthropicProvider(api_key="k", client=client)
    response = await provider.complete(system="s", user="u", max_tokens=100)
    assert response.text == VALID_ANSWER


async def test_the_request_uses_adaptive_thinking_and_the_effort_knob():
    """`{"type": "enabled", "budget_tokens": N}` is REJECTED WITH A 400 on this model.
    It is the most common stale pattern in Claude code written before 2026."""
    client = _FakeClient(_FakeMessage([_Block("text", VALID_ANSWER)]))
    provider = AnthropicProvider(api_key="k", client=client)
    await provider.complete_structured(
        system="s", user="u", schema={"type": "object"}, schema_name="ignored",
        max_tokens=100, effort="high",
    )
    call = client.messages.calls[0]
    assert call["thinking"] == {"type": "adaptive"}
    assert "budget_tokens" not in json.dumps(call["thinking"])
    assert call["output_config"]["effort"] == "high"
    # Bare schema, no envelope: this is not the OpenAI shape.
    assert call["output_config"]["format"] == {
        "type": "json_schema", "schema": {"type": "object"}
    }


async def test_the_system_prompt_is_sent_as_a_cacheable_block():
    """The cache breakpoint is after the system prompt; the question and the retrieved
    context go after it and are never cached."""
    client = _FakeClient(_FakeMessage([_Block("text", VALID_ANSWER)]))
    provider = AnthropicProvider(api_key="k", client=client)
    await provider.complete(system="SYSTEM", user="u", max_tokens=100)
    system = client.messages.calls[0]["system"]
    assert system == [
        {"type": "text", "text": "SYSTEM", "cache_control": {"type": "ephemeral"}}
    ]


async def test_cache_token_counts_reach_the_usage_record():
    """Cost accounting cannot show a cache saving it never recorded, and the assertion
    that caching works at all is `cache_read_input_tokens > 0` on a second call."""
    client = _FakeClient(_FakeMessage([_Block("text", VALID_ANSWER)]))
    provider = AnthropicProvider(api_key="k", client=client)
    response = await provider.complete(system="s", user="u", max_tokens=10)
    assert response.usage.cache_read_input_tokens == 900
    assert response.request_id == "req_abc"


async def test_a_missing_key_is_a_configuration_error_not_a_traceback():
    provider = AnthropicProvider(api_key="")
    with pytest.raises(LLMError) as exc:
        await provider.complete(system="s", user="u", max_tokens=10)
    assert exc.value.status_code == 503
    assert "LLM_PROVIDER=local" in str(exc.value)


async def test_anthropic_does_not_retry_a_schema_failure():
    """The server constrains generation to the schema. A failure there is structural --
    a rejected schema, a truncation at max_tokens -- and re-asking pays twice to learn
    the same thing. The error says which, using stop_reason."""
    client = _FakeClient(_FakeMessage([_Block("text", '{"partial":')]))
    provider = AnthropicProvider(api_key="k", client=client)

    def validate(payload):
        GroundedAnswer.model_validate_json(payload)

    with pytest.raises(LLMError) as exc:
        await provider.complete_structured(
            system="s", user="u", schema={"type": "object"}, schema_name="x",
            max_tokens=10, validate=validate,
        )
    assert len(client.messages.calls) == 1
    assert "stop_reason" in str(exc.value)


# ── the shared value types ──────────────────────────────────────────────────


def test_usage_totals_include_cached_tokens():
    usage = Usage(
        input_tokens=10, output_tokens=5, cache_read_input_tokens=100,
        cache_creation_input_tokens=1,
    )
    assert usage.total_tokens == 116


def test_llm_response_defaults_to_no_repairs():
    response = LLMResponse(text="{}", usage=Usage(), provider="local", model="m",
                           latency_ms=1)
    assert response.repair_attempts == 0


def test_a_citation_requires_both_an_id_and_a_quote():
    with pytest.raises(Exception):
        Citation(chunk_id=1)
