"""Contrato común de los proveedores LLM."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ProviderError(RuntimeError):
    """Error transitorio o del proveedor. El pipeline lo trata como reintentable."""


class ProviderUnavailable(RuntimeError):
    """Proveedor desconocido, no implementado o sin credenciales. Se detecta antes de llamar."""


class ProviderFatalError(RuntimeError):
    """Error del proveedor que no se corrige reintentando (p. ej. clave inválida)."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    prompt_tokens: int
    completion_tokens: int
    token_source: str


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
    ) -> LLMResponse:
        raise NotImplementedError
