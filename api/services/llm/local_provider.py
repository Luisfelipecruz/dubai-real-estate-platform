"""Ollama, through its OpenAI-compatible endpoint.

Local and keyless. A fresh clone of this repository answers questions with no API key,
no account and no egress, which is the whole reason this provider is the default.

WHY THE HOST'S OLLAMA AND NOT THE CONTAINER
-------------------------------------------
`OLLAMA_BASE_URL` defaults to `http://host.docker.internal:11434`. Docker Desktop on
macOS cannot pass the Apple GPU into a Linux container, so `docker compose --profile llm
up ollama` gets you the same weights running on CPU -- several times slower for no
benefit. The container is still declared, for Linux hosts with a GPU and for CI where a
self-contained stack matters more than throughput. Point OLLAMA_BASE_URL at
`http://ollama:11434` there and nothing else changes.

WHY /v1/chat/completions AND NOT /api/chat
-------------------------------------------
Ollama's native endpoint takes a bare JSON Schema in `format`; the OpenAI-compatible one
takes the `response_format` envelope. The envelope is what every other hosted provider
speaks, so a third backend -- vLLM, llama.cpp's server, LM Studio, an OpenAI-compatible
gateway -- is a base-URL change rather than a new file. That is worth one extra level of
nesting.
"""

import json
import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx

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


class OllamaProvider(LLMProvider):
    name = "local"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float | None = None,
        repair_attempts: int | None = None,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout_s = timeout_s if timeout_s is not None else settings.LLM_TIMEOUT_S
        self.repair_attempts = (
            repair_attempts
            if repair_attempts is not None
            else settings.LLM_REPAIR_ATTEMPTS
        )

    # ── the wire ────────────────────────────────────────────────────────────

    async def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], int]:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions", json=payload
                )
                response.raise_for_status()
                body = response.json()
        except httpx.ConnectError as exc:
            # By far the most common failure, and the message has to name the cause:
            # from inside the api container `localhost` is the container, not the Mac.
            raise LLMError(
                f"cannot reach Ollama at {self.base_url} -- is it running on the HOST? "
                f"({exc})",
                status_code=503,
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMError(
                f"Ollama did not respond within {self.timeout_s:.0f}s. A cold model load "
                f"can exceed this; try again once `ollama ps` shows {self.model} resident.",
                status_code=504,
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise LLMError(
                f"Ollama returned {exc.response.status_code}: {exc.response.text[:400]}",
                status_code=502,
            ) from exc
        return body, int((time.perf_counter() - started) * 1000)

    @staticmethod
    def _tool_calls_of(message: dict[str, Any]) -> tuple[ToolCall, ...]:
        """OpenAI-style tool calls, with the argument blob parsed.

        `function.arguments` arrives as a JSON *string*, not an object, and it can be
        malformed even under constrained decoding. A parse failure yields a call with NO
        arguments rather than an exception, on purpose: the executor validates arguments
        against the tool's schema anyway, so an empty dict comes back as "missing
        required field", which is fed to the model as a normal error result and can be
        retried. Raising here would end an eight-step run over one bad blob.
        """
        calls = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            blob = function.get("arguments")
            try:
                arguments = json.loads(blob) if isinstance(blob, str) else (blob or {})
            except json.JSONDecodeError:
                logger.warning(
                    "tool call %s had unparseable arguments: %.200s",
                    function.get("name"),
                    blob,
                )
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append(
                ToolCall(
                    id=raw.get("id") or f"call_{len(calls)}",
                    name=function.get("name") or "",
                    arguments=arguments,
                )
            )
        return tuple(calls)

    @staticmethod
    def _unpack(body: dict[str, Any], model: str, latency_ms: int, repairs: int):
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError) as exc:
            raise LLMError(
                f"Ollama response had no choices: {json.dumps(body)[:400]}",
                status_code=502,
            ) from exc
        raw_usage = body.get("usage") or {}
        return LLMResponse(
            # gpt-oss puts chain-of-thought in a separate `reasoning` field, so `content`
            # is the JSON object alone. Do not concatenate them -- a reasoning trace
            # prepended to a JSON body is the single most common cause of a "constrained
            # decoding produced invalid JSON" report that is not actually that.
            text=message.get("content") or "",
            usage=Usage(
                input_tokens=int(raw_usage.get("prompt_tokens", 0)),
                output_tokens=int(raw_usage.get("completion_tokens", 0)),
            ),
            provider="local",
            model=body.get("model", model),
            latency_ms=latency_ms,
            stop_reason=(body.get("choices") or [{}])[0].get("finish_reason"),
            request_id=body.get("id"),
            repair_attempts=repairs,
            raw={"reasoning": message.get("reasoning")} if message.get("reasoning") else {},
            tool_calls=OllamaProvider._tool_calls_of(message),
        )

    # ── the interface ───────────────────────────────────────────────────────

    async def complete(
        self, *, system: str, user: str, max_tokens: int, effort: str = "medium"
    ) -> LLMResponse:
        # `effort` has no equivalent here. Silently ignoring a caller's quality/cost
        # lever would make the two providers look interchangeable when they are not, so
        # it is logged once per call at debug rather than dropped.
        logger.debug("local provider ignores effort=%s (no equivalent knob)", effort)
        body, latency_ms = await self._post(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                # Zero, and not for "accuracy". A grounded answer is graded against a
                # fixture; a sampled one makes every eval run a different experiment.
                "temperature": 0,
                "stream": False,
            }
        )
        return self._unpack(body, self.model, latency_ms, repairs=0)

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
        """One turn of a tool-using conversation. No loop, no repair.

        NO REPAIR LOOP HERE, and that is a decision rather than an omission.
        `complete_structured` retries because there is one right shape and a truncated
        object is unusable. A tool-calling turn has no single right shape: the model may
        answer, or call one tool, or call three, and all are valid. What could go wrong
        -- a bad argument blob, a tool that fails -- is handled by feeding the error back
        as a tool RESULT, which is the mechanism the model is already in the middle of
        using. Adding a second retry mechanism on top would double-count steps against
        AGENT_MAX_STEPS and hide failures the executor is supposed to see and log.

        gpt-oss:20b was verified to do native function calling through this endpoint
        before any of the agent layer was written: it routed a median-price question to
        the SQL tool and a "how does this work" question to the document tool, unprompted,
        on the first attempt.
        """
        logger.debug("local provider ignores effort=%s (no equivalent knob)", effort)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        for exchange in exchanges:
            messages.append(
                {
                    "role": "assistant",
                    "content": exchange.response.text or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                        for call in exchange.response.tool_calls
                    ],
                }
            )
            # Every result for this turn, together and in one go. See Exchange.
            for result in exchange.results:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.call_id,
                        "content": result.content,
                    }
                )

        body, latency_ms = await self._post(
            {
                "model": self.model,
                "messages": messages,
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.parameters,
                        },
                    }
                    for tool in tools
                ],
                "max_tokens": max_tokens,
                "temperature": 0,
                "stream": False,
            }
        )
        return self._unpack(body, self.model, latency_ms, repairs=0)

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
        """Constrained decoding, plus a CAPPED repair loop.

        Ollama constrains generation to the schema, which makes malformed JSON rare but
        not impossible -- hitting `max_tokens` mid-object truncates it, and the grammar
        cannot prevent that.

        WHAT GETS REPAIRED AND WHAT DOES NOT. The loop repairs SHAPE: unparseable JSON,
        or JSON that fails the caller's `validate`. It does not repair CONTENT. A
        citation pointing at a chunk that was never retrieved is a grounding failure, and
        retrying until the model produces one that resolves would be teaching the system
        to launder a hallucination into a well-formed one. Grounding is checked in
        services/ask.py, after this returns, and it rejects.

        The cap is logged on every retry. An uncapped repair loop is how one question
        quietly becomes forty requests -- at $0.02 a call that is a rounding error, and
        on a hosted model with a large context it is not.
        """
        logger.debug("local provider ignores effort=%s (no equivalent knob)", effort)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
        }

        last_error: str = ""
        cumulative_ms = 0
        for attempt in range(self.repair_attempts + 1):
            body, latency_ms = await self._post(payload)
            cumulative_ms += latency_ms
            response = self._unpack(body, self.model, cumulative_ms, repairs=attempt)
            try:
                json.loads(response.text)
                if validate is not None:
                    validate(response.text)
                return response
            except Exception as exc:  # json.JSONDecodeError or the caller's validator
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "local structured output invalid on attempt %d/%d (cap=%d): %s",
                    attempt + 1,
                    self.repair_attempts + 1,
                    self.repair_attempts,
                    last_error,
                )
                if attempt == self.repair_attempts:
                    break
                # Feed the failure back as the next turn rather than re-sending the same
                # prompt. Re-sending an identical prompt at temperature 0 gets an
                # identical answer, so a retry without the error text is not a retry.
                payload["messages"] = [
                    *payload["messages"][:2],
                    {"role": "assistant", "content": response.text},
                    {
                        "role": "user",
                        "content": (
                            "That response did not validate. The error was:\n"
                            f"{last_error}\n\n"
                            "Return ONLY a JSON object matching the schema. No prose, no "
                            "markdown fence, no explanation."
                        ),
                    },
                ]

        raise LLMError(
            f"{self.model} did not produce schema-valid JSON in "
            f"{self.repair_attempts + 1} attempts (cap={self.repair_attempts}). "
            f"Last error: {last_error}",
            status_code=502,
        )
