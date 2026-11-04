"""Construcción de proveedores por nombre."""

from __future__ import annotations

from src.providers.anthropic_provider import AnthropicProvider
from src.providers.base import LLMProvider, ProviderUnavailable
from src.providers.mock_provider import MockProvider

PLANNED = {"openai": "Fase 3 (siguiente paso)"}


def build_provider(name: str) -> LLMProvider:
    if name == "mock":
        return MockProvider()
    if name == "anthropic":
        return AnthropicProvider()
    if name in PLANNED:
        raise ProviderUnavailable(
            f"el proveedor '{name}' se implementa en la {PLANNED[name]}; usá --provider mock o anthropic"
        )
    raise ProviderUnavailable(f"proveedor desconocido '{name}'. Opciones: mock, anthropic")
