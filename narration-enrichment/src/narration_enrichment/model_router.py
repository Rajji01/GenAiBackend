"""
P7 Day 4 — model routing + the fallback chain.

Routing: WHICH model serves a surface is data, not code —
`MODEL_ENRICH` / `MODEL_CHAT` / `MODEL_DISPUTES` (empty = the default
`MODEL_NAME`). Moving chat to a bigger model is an env change and a
restart, not a diff.

Clients: one Instructor client per model, built lazily and cached —
and `client_for(default_model)` returns THE existing `service._client`
object, not a twin. That identity is load-bearing twice over: (a) no
duplicate client for the common case, and (b) every existing test that
patches `<module>._client.create*` keeps working under default config,
because all module-level `_client` names and the router resolve to the
same object.

Fallback: `FALLBACK_MODEL` (empty = off). One secondary, one narrow
trigger — a call whose PRIMARY attempt exhausts as provider-down (the
`counts_as_provider_down` whitelist) is retried ONCE on the fallback
model. An OPEN circuit never consults the fallback: the breaker's
verdict is "the PROVIDER is down", and both models live behind the
same endpoint/key here — routing to a sibling model during an outage
is a retry storm in a costume (P7_DESIGN §4). A real second VENDOR
slots into this same chain the day Rajat adds its key.
"""

from __future__ import annotations

import logging
import threading

from narration_enrichment.config import get_settings

logger = logging.getLogger(__name__)

_clients: dict[str, object] = {}
_lock = threading.Lock()


def model_for(surface: str) -> str:
    settings = get_settings()
    override = {
        "enrich": settings.model_enrich,
        "chat": settings.model_chat,
        "dispute_agent": settings.model_disputes,
        "dispute_judge": settings.model_disputes,
    }.get(surface, "")
    return override or settings.model_name


def chain_for(surface: str) -> list[str]:
    """[primary] or [primary, fallback]. The fallback is dropped when
    it IS the primary — a chain that retries the same model twice is
    tenacity's job, already done."""
    settings = get_settings()
    primary = model_for(surface)
    if settings.fallback_model and settings.fallback_model != primary:
        return [primary, settings.fallback_model]
    return [primary]


def client_for(model: str):
    settings = get_settings()
    if model == settings.model_name:
        # THE default client, by identity — see module docstring.
        from narration_enrichment.service import _client

        return _client
    with _lock:
        if model not in _clients:
            import instructor

            from narration_enrichment.service import get_raw_client

            # Same raw client (same key, same timeout budget) wrapped
            # for a different model — the router routes models, it
            # does not invent transports.
            _clients[model] = instructor.from_genai(get_raw_client(), model=model)
            logger.info("model_client_built model=%s", model)
        return _clients[model]


def _reset_for_tests() -> None:
    with _lock:
        _clients.clear()
