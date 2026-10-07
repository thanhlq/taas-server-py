"""AI gateway of the EWS apps (taas-specs/site-builder/ai-assist-spec.md §4): one interface, provider
picked by ``AI_GATEWAY_PROVIDER``; provider keys never leave the server.

Providers: ``anthropic`` (official SDK), ``fake`` (deterministic, development / tests), ``none``
(disabled). Callers own prompts, credits and audit (e.g. ``ews.sites._ai``).
"""

from ._gateway import (
    AiDisabledError,
    AiError,
    AiGatewayT,
    AiImage,
    AiRefusedError,
    AiResult,
    AiSettings,
    ai_settings,
    get_ai_gateway,
    use_ai_gateway,
)

__all__ = [
    'AiDisabledError',
    'AiError',
    'AiGatewayT',
    'AiImage',
    'AiRefusedError',
    'AiResult',
    'AiSettings',
    'ai_settings',
    'get_ai_gateway',
    'use_ai_gateway',
]
