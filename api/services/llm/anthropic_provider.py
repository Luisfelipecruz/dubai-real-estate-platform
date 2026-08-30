"""
The hosted half of the comparison. Nothing in /ask changes when this is selected --
same prompt, same schema, same grounding checks, same `llm_calls` row -- which is what
makes an m16 quality/cost/latency comparison between it and the local 20B mean anything.

THREE THINGS HERE THAT A 2024 TUTORIAL WOULD GET WRONG
------------------------------------------------------
1. `thinking={"type": "adaptive"}`. The older `{"type": "enabled", "budget_tokens": N}`
   form is REJECTED WITH A 400 on this model. It is the most common stale pattern in
   Claude code written before 2026 and it fails loudly, which is the good case.
2. Structured output is `output_config={"format": {"type": "json_schema", "schema": ...}}`
   on `messages.create`. There is also a deprecated top-level `output_format=` parameter
   on `create` that is NOT this. The typed helper `messages.parse(output_format=Model)`
   returns a validated Pydantic instance and is the nicer surface -- it is not used here
   because it would require this file to import GroundedAnswer, and a provider that knows
   what a grounded answer is stops being a provider.
3. `output_config={"effort": ...}` is per-call, not global. /ask uses "high" for
   synthesis; a classifier would use "low". Tuning effort per route rather than once for
   the whole application is where the cost curve actually bends.

The shapes above were checked against the installed SDK (anthropic 1.2.0) rather than
recalled: OutputConfigParam has exactly {effort, format}, JSONOutputFormatParam exactly
{type, schema}, and ThinkingConfigAdaptiveParam exactly {type, display}.
"""

import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

from . import settings
from .base import (
    Exchange,
    LLMError,
    LLMProvider,
    LLMResponse,
    ToolCall,
    ToolSpec,
    Usage,
)

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_s: float | None = None,
        client: Any = None,
    ):
        self.model = model or settings.ANTHROPIC_MODEL
        self.timeout_s = timeout_s if timeout_s is not None else settings.LLM_TIMEOUT_S
        self._api_key = api_key if api_key is not None else settings.ANTHROPIC_API_KEY
        # Injected in tests. Constructing the real client is deferred to first use so
        # that importing this module -- which api/main.py does on every startup through
        # the router -- never depends on a key being present.
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY is not set. Use LLM_PROVIDER=local (the default, and "
                "keyless) or set the key.",
                status_code=503,
            )
        try:
            import anthropic
        except ModuleNotFoundError as exc:  # pragma: no cover - pinned in requirements
            raise LLMError(
                "the anthropic package is not installed in this image", status_code=503
            ) from exc
        self._client = anthropic.AsyncAnthropic(
            api_key=self._api_key, timeout=self.timeout_s
        )
        return self._client

    # ── shared plumbing ─────────────────────────────────────────────────────

    @staticmethod
    def _text_of(message: Any) -> str:
        """The text blocks only.

        With adaptive thinking the content list also carries ThinkingBlocks. Joining
        every block's `.text` would prepend a reasoning trace to the JSON body and turn
        a perfectly good structured response into a parse error -- and the error would
        point at the schema, which is the wrong place to go looking.
        """
        parts = [
            block.text
            for block in getattr(message, "content", [])
            if getattr(block, "type", None) == "text"
        ]
        return "".join(parts)

    @staticmethod
    def _tool_calls_of(message: Any) -> tuple[ToolCall, ...]:
        """`tool_use` content blocks, whose `input` is ALREADY a parsed object.

        The difference from the OpenAI-compatible shape is worth naming because it is a
        trap in the other direction: there is no JSON string to decode here, so code that
        calls `json.loads` on `.input` fails on a dict. Each provider absorbs its own
        dialect precisely so the executor never has to know which one it is talking to.
        """
        return tuple(
            ToolCall(
                id=getattr(block, "id", "") or "",
                name=getattr(block, "name", "") or "",
                arguments=dict(getattr(block, "input", None) or {}),
            )
            for block in getattr(message, "content", [])
            if getattr(block, "type", None) == "tool_use"
        )

    @staticmethod
    def _usage_of(message: Any) -> Usage:
        usage = getattr(message, "usage", None)
        if usage is None:
            return Usage()
        return Usage(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0)
            or 0,
        )

    def _system_blocks(self, system: str) -> list[dict[str, Any]]:
        """System prompt as a cacheable block.

        The system prompt and the answer schema are stable across every request; the
        retrieved context and the question go after this breakpoint and are never cached.

        A CAVEAT WORTH STATING RATHER THAN ASSUMING: ephemeral caching has a minimum
        cacheable prefix, and a system prompt shorter than it simply is not cached --
        with no error and no warning. The check is `usage.cache_read_input_tokens > 0`
        on a second identical request, which is a test, not a hope. A zero there almost
        always means a silent invalidator, and the usual culprit is a timestamp in the
        prompt. This system prompt is ~600 estimated tokens and so may well fall UNDER
        the minimum; the breakpoint is declared anyway because it costs nothing and
        because the assertion is what turns "we cache" into a number.
        """
        return [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    async def _call(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int,
        effort: str,
        fmt: Any = None,
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        output_config: dict[str, Any] = {"effort": effort}
        if fmt is not None:
            output_config["format"] = fmt

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": self._system_blocks(system),
            "messages": messages or [{"role": "user", "content": user}],
            "thinking": {"type": "adaptive"},
            "output_config": output_config,
        }
        if tools:
            kwargs["tools"] = tools

        started = time.perf_counter()
        try:
            message = await client.messages.create(**kwargs)
        except LLMError:
            raise
        except Exception as exc:
            # Deliberately broad. The SDK raises a family of typed errors
            # (APIConnectionError, RateLimitError, APIStatusError, ...) and /ask's caller
            # needs one thing from all of them: that generation did not happen and the
            # reason is reportable. Narrowing here would mean importing the SDK at module
            # scope, which is what _get_client exists to avoid.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            raise LLMError(
                f"{type(exc).__name__} from the Anthropic API: {exc}",
                status_code=502 if status else 503,
            ) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        return LLMResponse(
            text=self._text_of(message),
            usage=self._usage_of(message),
            provider="anthropic",
            model=getattr(message, "model", self.model),
            latency_ms=latency_ms,
            stop_reason=getattr(message, "stop_reason", None),
            request_id=getattr(message, "_request_id", None),
            tool_calls=self._tool_calls_of(message),
            # The FULL content list, thinking blocks included, kept so the next turn can
            # send it back verbatim. With extended thinking active, an assistant turn
            # replayed WITHOUT its thinking blocks is rejected -- reconstructing the turn
            # from `text` alone would silently drop them and produce a 400 on the second
            # step of every tool-using run.
            raw={"content": list(getattr(message, "content", []) or [])},
        )

    # ── the interface ───────────────────────────────────────────────────────

    async def complete(
        self, *, system: str, user: str, max_tokens: int, effort: str = "medium"
    ) -> LLMResponse:
        return await self._call(
            system=system, user=user, max_tokens=max_tokens, effort=effort
        )

    async def complete_with_tools(
        self,
        *,
        system: str,
        user: str,
        tools: Sequence[ToolSpec],
        exchanges: Sequence[Exchange] = (),
        max_tokens: int,
        effort: str = "medium",
    ) -> LLMResponse:
        """One turn against the hosted model, with tools declared.

        **NOT VERIFIED AGAINST THE LIVE API.** There is no ANTHROPIC_API_KEY on the
        machine this was built on, so this path is asserted against a scripted client in
        api/tests/test_agent_providers.py and nothing about it has been observed against
        Anthropic's servers -- the same caveat m14 recorded for `complete_structured`,
        and it has not changed. It is stated here rather than in a commit message because
        this is where someone will read it. m16 is where it gets exercised.

        Three shape differences from the OpenAI-compatible dialect, all absorbed here:
        `input_schema` rather than a nested `function.parameters`; `tool_use` blocks with
        parsed input rather than a JSON string; and results returned as `tool_result`
        blocks inside a USER message rather than as messages with a `tool` role.
        """
        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        for exchange in exchanges:
            # Replay the assistant turn from its original blocks. See the `raw` comment
            # in _call: with adaptive thinking, dropping the thinking blocks is a 400.
            content = exchange.response.raw.get("content")
            if not content:
                content = [
                    {"type": "text", "text": exchange.response.text or ""},
                    *(
                        {
                            "type": "tool_use",
                            "id": call.id,
                            "name": call.name,
                            "input": call.arguments,
                        }
                        for call in exchange.response.tool_calls
                    ),
                ]
            messages.append({"role": "assistant", "content": content})
            # All results for the turn in ONE user message. Splitting them across several
            # is legal and teaches the model to stop calling tools in parallel, which
            # costs a step of latency per extra turn for the rest of the run.
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result.call_id,
                            "content": result.content,
                            "is_error": result.is_error,
                        }
                        for result in exchange.results
                    ],
                }
            )

        return await self._call(
            system=system,
            user=user,
            max_tokens=max_tokens,
            effort=effort,
            messages=messages,
            tools=[
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
                for tool in tools
            ],
        )

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
    ) -> LLMResponse:
        """First-party structured output. `schema_name` is unused and that is correct.

        Anthropic's format takes the schema alone; OpenAI-compatible endpoints wrap it in
        a named envelope. The name is part of the interface because one backend needs it,
        and a parameter that one implementation ignores is a smaller cost than two
        signatures.

        There is no repair loop here. The server constrains generation to the schema, so
        a validation failure means something structural is wrong -- a schema the API
        rejected, a truncation at max_tokens -- and re-asking would be paying twice to
        learn the same thing. The local provider retries because its guarantee is weaker.
        """
        response = await self._call(
            system=system,
            user=user,
            max_tokens=max_tokens,
            effort=effort,
            fmt={"type": "json_schema", "schema": schema},
        )
        if validate is not None:
            try:
                validate(response.text)
            except Exception as exc:
                raise LLMError(
                    f"{self.model} returned schema-invalid JSON despite constrained "
                    f"decoding ({type(exc).__name__}: {exc}). stop_reason="
                    f"{response.stop_reason!r} -- if that is 'max_tokens' the object was "
                    f"truncated, not malformed.",
                    status_code=502,
                ) from exc
        return response
