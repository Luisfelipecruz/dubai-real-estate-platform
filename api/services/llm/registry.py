"""LLM_PROVIDER -> a provider instance, or a clear refusal.

`none` is a SUPPORTED CONFIGURATION, not a broken one. A machine that cannot host a 13 GB
model still serves the platform's 30 REST operations and still serves /search; only /ask
reports 503, and it says why. That property is asserted in api/tests/test_main.py, which
loads the app with the copilot routers absent entirely.

The instance is cached per process because building it is cheap but not free -- the
Anthropic client opens a connection pool -- and because a provider swapped mid-process
would make two /ask calls in one eval run incomparable. Tests clear it with `reset()`.
"""

import logging

from . import settings
from .base import LLMError, LLMProvider

logger = logging.getLogger(__name__)

_instance: LLMProvider | None = None
_instance_for: str | None = None

SUPPORTED = ("local", "anthropic", "none")


def reset() -> None:
    """Drop the cached instance. Called by tests, and by nothing else."""
    global _instance, _instance_for
    _instance = None
    _instance_for = None


def configured_provider() -> str:
    return settings.LLM_PROVIDER


def is_enabled() -> bool:
    return settings.LLM_PROVIDER != "none"


def get_provider(name: str | None = None) -> LLMProvider:
    """The provider for `name`, defaulting to LLM_PROVIDER.

    Raises LLMError(503) for `none` and for anything unrecognised. Unrecognised is a 503
    rather than a 500 on purpose: a typo in an environment variable is a deployment
    state, and the message names the three values that work rather than making someone
    read this file to find out.
    """
    global _instance, _instance_for
    requested = (name or settings.LLM_PROVIDER).strip().lower()

    if requested == "none":
        raise LLMError(
            "the generation layer is disabled (LLM_PROVIDER=none). /search still serves "
            "retrieval, and the platform's other operations are unaffected.",
            status_code=503,
        )
    if requested not in SUPPORTED:
        raise LLMError(
            f"LLM_PROVIDER={requested!r} is not one of {SUPPORTED}",
            status_code=503,
        )

    if _instance is not None and _instance_for == requested:
        return _instance

    if requested == "local":
        from .local_provider import OllamaProvider

        provider: LLMProvider = OllamaProvider()
    else:
        from .anthropic_provider import AnthropicProvider

        provider = AnthropicProvider()

    logger.info("generation layer: provider=%s model=%s", provider.name, provider.model)
    _instance, _instance_for = provider, requested
    return provider
