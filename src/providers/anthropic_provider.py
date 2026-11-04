"""Proveedor Anthropic (Messages API) sobre el SDK oficial.

Sobre la temperatura: el SDK envía ``anthropic-version: 2026-10-21``
(``anthropic._constants.ANTHROPIC_API_VERSION``). Desde esa versión la API rechaza
``temperature``, ``top_p`` y ``top_k`` con 400 en *todos* los modelos, no solo en
Haiku 4.5. Por eso este proveedor nunca envía muestreo. La variabilidad se controla
con el prompt y, en los modelos que piensan, con ``effort`` (ADR-016).
"""

from __future__ import annotations

import os
from typing import Any

import anthropic

from src.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderError,
    ProviderFatalError,
    ProviderUnavailable,
)

ENV_KEY = "ANTHROPIC_API_KEY"

RETRYABLE = (
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
    anthropic.OverloadedError,
)
FATAL = (
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.NotFoundError,
    anthropic.BadRequestError,
)


def _client_from_env() -> anthropic.Anthropic:
    api_key = os.getenv(ENV_KEY, "").strip()
    if not api_key:
        raise ProviderUnavailable(
            f"falta {ENV_KEY}. Copiá .env.example a .env y completá la clave, "
            "o usá --provider mock"
        )
    return anthropic.Anthropic(api_key=api_key, max_retries=0)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, client: Any | None = None) -> None:
        self._client = client if client is not None else _client_from_env()

    def complete(
        self,
        system: str,
        user: str,
        *,
        model: str,
        temperature: float | None,
        max_tokens: int,
        timeout_s: float,
        effort: str | None = None,
    ) -> LLMResponse:
        if temperature is not None:
            raise ProviderFatalError(
                "la API de Anthropic (versión 2026-10-21) rechaza 'temperature' en todos "
                "los modelos; poné 'temperature: null' en config/providers.yaml"
            )
        params: dict[str, Any] = {
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "timeout": timeout_s,
        }
        if effort is not None:
            params["output_config"] = {"effort": effort}
        try:
            message = self._client.messages.create(**params)
        except FATAL as exc:
            raise ProviderFatalError(_short(exc)) from exc
        except RETRYABLE as exc:
            raise ProviderError(_short(exc)) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ProviderError(_short(exc)) from exc
            raise ProviderFatalError(_short(exc)) from exc

        text = "".join(block.text for block in message.content if block.type == "text")
        return LLMResponse(
            text=text,
            prompt_tokens=message.usage.input_tokens,
            completion_tokens=message.usage.output_tokens,
            token_source="api",
        )


def _short(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]
