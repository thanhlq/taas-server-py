from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

type Provider = Literal['none', 'anthropic', 'fake']


class AiError(RuntimeError):
    """The provider failed (network, quota, invalid answer)."""


class AiDisabledError(AiError):
    """No provider configured (``AI_GATEWAY_PROVIDER=none``)."""


class AiRefusedError(AiError):
    """The model declined the request (safety classifiers)."""


@dataclass(frozen=True, slots=True)
class AiSettings:
    provider: Provider = 'none'
    model_text: str = 'claude-opus-5-5'
    """Drafting / generation (``AI_GATEWAY_MODEL_TEXT``)."""
    model_fast: str = 'claude-opus-5-5'
    """Small edits: rewrite, alt text, SEO (``AI_GATEWAY_MODEL_FAST``); run at low effort."""
    api_key: str | None = None
    timeout_seconds: float = 60.0
    max_output_tokens: int = 4000

    @staticmethod
    def from_env() -> AiSettings:
        provider = (os.environ.get('AI_GATEWAY_PROVIDER') or 'none').strip().lower()
        if provider not in ('none', 'anthropic', 'fake'):
            raise ValueError('AI_GATEWAY_PROVIDER must be none, anthropic or fake')
        return AiSettings(
            provider=provider,  # type: ignore[arg-type]
            model_text=os.environ.get('AI_GATEWAY_MODEL_TEXT') or 'claude-opus-5-5',
            model_fast=os.environ.get('AI_GATEWAY_MODEL_FAST') or os.environ.get('AI_GATEWAY_MODEL_TEXT') or 'claude-opus-5-5',
            api_key=os.environ.get('AI_GATEWAY_API_KEY') or None,
            timeout_seconds=float(os.environ.get('AI_GATEWAY_TIMEOUT_SECONDS') or 60),
            max_output_tokens=int(os.environ.get('AI_GATEWAY_MAX_OUTPUT_TOKENS') or 4000),
        )


@lru_cache(maxsize=1)
def ai_settings() -> AiSettings:
    return AiSettings.from_env()


@dataclass(frozen=True, slots=True)
class AiImage:
    media_type: str
    """``image/webp`` · ``image/png`` · ``image/jpeg`` · ``image/gif``."""
    data_base64: str


@dataclass(frozen=True, slots=True)
class AiResult:
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0

    def json(self) -> Any:
        """The first JSON object / array in the answer (models may wrap it in prose or fences)."""
        text = self.text.strip()
        fenced = re.search(r'```(?:json)?\s*(.+?)```', text, re.S)
        if fenced:
            text = fenced.group(1).strip()
        start = min((i for i in (text.find('{'), text.find('[')) if i >= 0), default=-1)
        if start < 0:
            raise AiError('the model did not answer with JSON')
        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError as error:
            raise AiError(f'invalid JSON from the model: {error}') from error
        return value


class AiGatewayT(ABC):
    provider: str

    @abstractmethod
    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        task: str,
        fast: bool = True,
        json_schema: dict[str, Any] | None = None,
        image: AiImage | None = None,
        max_tokens: int | None = None,
    ) -> AiResult:
        """One completion. ``task`` names the use case (``rewrite``, ``section``, …) for logs and the fake
        provider; ``json_schema`` asks for structured JSON output."""


class DisabledGateway(AiGatewayT):
    provider = 'none'

    async def complete(self, **_: Any) -> AiResult:
        raise AiDisabledError('AI is not configured on this platform (AI_GATEWAY_PROVIDER)')


class AnthropicGateway(AiGatewayT):
    """Claude through the official ``anthropic`` SDK: adaptive thinking (always on for Claude Opus 5.5),
    effort ``low`` for small edits / ``medium`` for generation, structured outputs via
    ``output_config.format``, server-side refusal fallbacks (``fallbacks: "default"``)."""

    provider = 'anthropic'

    def __init__(self, settings: AiSettings) -> None:
        import anthropic

        self._settings = settings
        self._client = anthropic.AsyncAnthropic(api_key=settings.api_key, timeout=settings.timeout_seconds)

    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        task: str,
        fast: bool = True,
        json_schema: dict[str, Any] | None = None,
        image: AiImage | None = None,
        max_tokens: int | None = None,
    ) -> AiResult:
        import anthropic

        content: list[dict[str, Any]] = []
        if image is not None:
            content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': image.media_type, 'data': image.data_base64}})
        content.append({'type': 'text', 'text': prompt})
        output_config: dict[str, Any] = {'effort': 'low' if fast else 'medium'}
        if json_schema is not None:
            output_config['format'] = {'type': 'json_schema', 'schema': json_schema}
        try:
            response = await self._client.beta.messages.create(
                model=self._settings.model_fast if fast else self._settings.model_text,
                max_tokens=max_tokens or self._settings.max_output_tokens,
                system=system,
                messages=[{'role': 'user', 'content': content}],
                output_config=output_config,
                betas=['server-side-fallback-2026-07-01'],
                fallbacks='default',
            )
        except anthropic.RateLimitError as error:
            raise AiError('the AI provider is busy, try again in a moment') from error
        except anthropic.APIStatusError as error:
            raise AiError(f'AI provider error {error.status_code}') from error
        except anthropic.APIConnectionError as error:
            raise AiError('the AI provider is unreachable') from error
        if response.stop_reason == 'refusal':
            raise AiRefusedError('the AI declined this request')
        text = ''.join(block.text for block in response.content if block.type == 'text')
        if response.stop_reason == 'max_tokens' and json_schema is not None:
            raise AiError('the AI answer was cut off, try a shorter request')
        return AiResult(
            text=text.strip(),
            model=response.model,
            tokens_in=response.usage.input_tokens or 0,
            tokens_out=response.usage.output_tokens or 0,
        )


class FakeGateway(AiGatewayT):
    """Deterministic answers for development and tests (no network, no cost)."""

    provider = 'fake'

    async def complete(
        self,
        *,
        system: str,
        prompt: str,
        task: str,
        fast: bool = True,
        json_schema: dict[str, Any] | None = None,
        image: AiImage | None = None,
        max_tokens: int | None = None,
    ) -> AiResult:
        source = _between(prompt, '<text>', '</text>') or _between(prompt, '<request>', '</request>') or prompt
        source = source.strip()
        if task == 'shorten':
            text = re.split(r'(?<=[.!?])\s', source, maxsplit=1)[0]
        elif task == 'expand':
            text = f'{source} This makes a real difference for our customers every day.'
        elif task == 'fix':
            text = re.sub(r'\s+', ' ', source).strip()
            text = text[:1].upper() + text[1:] if text else text
        elif task == 'translate':
            text = f'[{_between(prompt, "<language>", "</language>") or "translated"}] {source}'
        elif task in ('rewrite', 'tone'):
            text = f'{source} (rewritten)'
        elif task == 'seo':
            title = (source.splitlines() or ['Page'])[0][:60]
            text = json.dumps({'title': title or 'Page', 'description': f'{title} — learn more about what we offer.'[:155]})
        elif task == 'alt':
            text = 'Illustration related to the page content'
        elif task == 'section':
            topic = source[:80] or 'Our offer'
            text = json.dumps({'blocks': [{
                'type': 'features',
                'props': {'title': topic, 'columns': 3, 'items': [
                    {'icon': 'sparkles', 'title': 'Quality', 'text': 'Carefully crafted, every time.'},
                    {'icon': 'clock', 'title': 'Speed', 'text': 'Delivered when you need it.'},
                    {'icon': 'heart', 'title': 'Care', 'text': 'A team that listens.'},
                ]},
            }]})
        else:
            text = source
        return AiResult(text=text, model='fake', tokens_in=len(prompt) // 4, tokens_out=len(text) // 4)


def _between(text: str, start: str, end: str) -> str | None:
    i = text.find(start)
    j = text.find(end, i + len(start)) if i >= 0 else -1
    return text[i + len(start) : j] if i >= 0 and j >= 0 else None


_override: list[AiGatewayT | None] = [None]
_gateway: list[AiGatewayT | None] = [None]


def use_ai_gateway(gateway: AiGatewayT | None) -> None:
    """Tests: replace the gateway (``None`` restores the configured one)."""
    _override[0] = gateway


def get_ai_gateway(settings: AiSettings | None = None) -> AiGatewayT:
    if _override[0] is not None:
        return _override[0]
    if _gateway[0] is None:
        settings = settings or ai_settings()
        if settings.provider == 'anthropic':
            _gateway[0] = AnthropicGateway(settings)
        elif settings.provider == 'fake':
            _gateway[0] = FakeGateway()
        else:
            _gateway[0] = DisabledGateway()
    return _gateway[0]
