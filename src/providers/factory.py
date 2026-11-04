"""Construcción de proveedores por nombre."""

from __future__ import annotations

from collections.abc import Callable

from src.providers.anthropic_provider import AnthropicProvider
from src.providers.base import LLMProvider, ProviderUnavailable
from src.providers.mock_provider import MockProvider
from src.providers.openai_provider import OpenAIProvider

PROVIDERS: dict[str, Callable[[], LLMProvider]] = {
    "mock": MockProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


def build_provider(name: str) -> LLMProvider:
    try:
        constructor = PROVIDERS[name]
    except KeyError:
        options = ", ".join(PROVIDERS)
        raise ProviderUnavailable(f"proveedor desconocido '{name}'. Opciones: {options}") from None
    return constructor()
