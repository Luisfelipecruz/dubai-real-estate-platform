"""What a call cost, computed from a table rather than from a log line.

The rate belongs in ONE place. Hardcoding `tokens * 0.000005` at the call site means a
price change is a grep, and a grep across log-formatting code is how half the costs in
a system end up stale while the other half do not.

RATES ARE INPUT, NOT MEASUREMENT. Everything in `RATES` is a published list price
copied by hand and dated; nothing here was measured by this repository. What IS measured
is `llm_calls.cost_usd`, which is this table applied to the token counts the provider
returned. If the rates drift, every historical row is re-priced by editing one dict --
which is the other reason the table exists.
"""

from dataclasses import dataclass

from .base import Usage


@dataclass(frozen=True)
class Rate:
    """USD per million tokens."""

    input: float
    output: float
    # Anthropic prices a cache READ at 0.1x the input rate and a 5-minute cache WRITE at
    # 1.25x. Stored as absolute rates rather than multipliers so a provider that prices
    # caching differently -- or not at all -- needs no special case.
    cache_read: float = 0.0
    cache_write: float = 0.0
    source: str = ""


# Dated on purpose. A rate table with no date is a rate table nobody trusts enough to
# correct.
RATES: dict[str, Rate] = {
    # Published Anthropic list price, 1M-token context window.
    "claude-opus-5": Rate(
        input=5.00,
        output=25.00,
        cache_read=0.50,
        cache_write=6.25,
        source="Anthropic published list price, recorded 2026-08-29",
    ),
    # The local models cost $0.00 per token and that is NOT the same as free. The real
    # cost is wall-clock latency on the host's GPU and the RAM the weights occupy while
    # resident, both of which /ask reports directly (latency_ms) or the host does
    # (`ollama ps`). Recording zero here keeps the arithmetic honest -- a zero that means
    # "no per-token billing relationship exists" -- rather than inventing an
    # amortised-hardware number that would be a guess dressed as a measurement.
    "gpt-oss:20b": Rate(input=0.0, output=0.0, source="local, no per-token billing"),
    "qwen3-coder:30b": Rate(input=0.0, output=0.0, source="local, no per-token billing"),
    "deepseek-r1:8b": Rate(input=0.0, output=0.0, source="local, no per-token billing"),
    "mistral:7b": Rate(input=0.0, output=0.0, source="local, no per-token billing"),
}

# A model nobody has priced. Returning 0.0 for it would be a lie that reads as a bargain,
# so cost_usd goes to None instead and the caller decides. `POST /ask` reports
# `cost_usd: null` with `cost_priced: false`, which is visibly different from "$0.00".
UNPRICED = None


def rate_for(model: str) -> Rate | None:
    """Exact match first, then the prefix before ':' so `gpt-oss:20b-q4` still prices.

    Deliberately not a fuzzy match. Guessing that an unknown `claude-opus-9` prices like
    `claude-opus-5` is how a 10x price change becomes invisible.
    """
    if model in RATES:
        return RATES[model]
    stem = model.split(":", 1)[0]
    for known, rate in RATES.items():
        if known.split(":", 1)[0] == stem and known != model:
            return rate
    return None


def cost_usd(model: str, usage: Usage) -> float | None:
    """USD for one call, or None when the model is not in the table."""
    rate = rate_for(model)
    if rate is None:
        return UNPRICED
    return (
        usage.input_tokens * rate.input
        + usage.output_tokens * rate.output
        + usage.cache_read_input_tokens * rate.cache_read
        + usage.cache_creation_input_tokens * rate.cache_write
    ) / 1_000_000
