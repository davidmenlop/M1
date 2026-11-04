"""Proveedor OpenAI (Chat Completions) sobre el SDK oficial."""

from __future__ import annotations

import os
from typing import Any

import openai

from src.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderError,
    ProviderFatalError,
    ProviderUnavailable,
)

ENV_KEY = "OPENAI_API_KEY"

RETRYABLE = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
    openai.ConflictError,
)
FATAL = (
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.NotFoundError,
    openai.BadRequestError,
    openai.UnprocessableEntityError,
)


def _client_from_env() -> openai.OpenAI:
    api_key = os.getenv(ENV_KEY, "").strip()
    if not api_key:
        raise ProviderUnavailable(
            f"falta {ENV_KEY}. Copiá .env.example a .env y completá la clave, "
            "o usá --provider mock"
        )
    # Sin reintentos del SDK: la única política de reintentos es la del pipeline (ADR-015).
    return openai.OpenAI(api_key=api_key, max_retries=0)


class OpenAIProvider(LLMProvider):
    name = "openai"

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
        params: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": max_tokens,
            # JSON mode: la API garantiza un objeto JSON sintácticamente válido.
            # El schema lo sigue validando Pydantic en el pipeline.
            "response_format": {"type": "json_object"},
            "timeout": timeout_s,
        }
        if temperature is not None:
            params["temperature"] = temperature
        if effort is not None:
            params["reasoning_effort"] = effort
        try:
            completion = self._client.chat.completions.create(**params)
        except FATAL as exc:
            raise ProviderFatalError(_short(exc)) from exc
        except RETRYABLE as exc:
            raise ProviderError(_short(exc)) from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ProviderError(_short(exc)) from exc
            raise ProviderFatalError(_short(exc)) from exc

        choice = completion.choices[0]
        usage = completion.usage
        return LLMResponse(
            text=choice.message.content or "",
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            token_source="api",
        )


def _short(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:500]
