"""Caché de respuestas por hash MD5 (extra de la consigna, Fase 10, ADR-033).

La clave es el MD5 de todo lo que puede cambiar la respuesta: la consulta normalizada, el
proveedor y el modelo con sus parámetros, el texto completo del prompt y las reglas de los
guardrails. Si cualquiera cambia, la clave cambia y la entrada vieja simplemente no se usa.

MD5 no se usa como seguridad (no protege nada contra un atacante): es una clave de caché
rápida y estable, como pide la consigna.

Qué se guarda: solo respuestas válidas del modelo (nunca el fallback ni un bloqueo), ya
revisadas por el guardrail de salida. La consulta en texto plano **no** se guarda.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from src.config import ModelConfig
from src.prompts import PromptSpec
from src.schemas import TriageResponse

logger = logging.getLogger(__name__)

_SPACES = re.compile(r"\s+")
FORMAT_VERSION = 1


def normalize_query(query: str) -> str:
    """Variantes triviales de la misma consulta comparten entrada: espacios, NFKC, mayúsculas."""
    return _SPACES.sub(" ", unicodedata.normalize("NFKC", query)).strip().casefold()


def prompt_fingerprint(prompt: PromptSpec) -> str:
    system, user = prompt.render("{query}")
    return hashlib.md5(f"{prompt.version}\n{system}\n{user}".encode("utf-8")).hexdigest()


def cache_key(query: str, *, provider: str, model: ModelConfig, prompt: PromptSpec,
              guardrails_sha256: str | None) -> str:
    material = {
        "v": FORMAT_VERSION,
        "query": normalize_query(query),
        "provider": provider,
        "model": model.id,
        "temperature": model.temperature,
        "effort": model.effort,
        "max_tokens": model.max_tokens,
        "prompt": prompt_fingerprint(prompt),
        "guardrails": guardrails_sha256,
    }
    return hashlib.md5(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheEntry:
    response: TriageResponse
    created_at: float
    original_cost_usd: float
    original_latency_s: float
    output_flags: tuple[str, ...]


class ResponseCache:
    def __init__(self, directory: Path, ttl_s: float) -> None:
        if ttl_s <= 0:
            raise ValueError("ttl_s debe ser > 0")
        self.directory = directory
        self.ttl_s = ttl_s

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> CacheEntry | None:
        path = self._path(key)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("entrada de caché ilegible %s: %s; se ignora", path.name, exc)
            return None
        if time.time() - data.get("created_at", 0) > self.ttl_s:
            return None
        try:
            return CacheEntry(
                response=TriageResponse.model_validate(data["response"]),
                created_at=data["created_at"],
                original_cost_usd=data["original_cost_usd"],
                original_latency_s=data["original_latency_s"],
                output_flags=tuple(data.get("output_flags", [])),
            )
        except (KeyError, TypeError, ValidationError) as exc:
            logger.warning("entrada de caché inválida %s: %s; se ignora", path.name, exc)
            return None

    def put(self, key: str, response: TriageResponse, *, cost_usd: float, latency_s: float,
            output_flags: tuple[str, ...] = ()) -> None:
        payload: dict[str, Any] = {
            "format": FORMAT_VERSION,
            "created_at": time.time(),
            "response": response.to_dict(),
            "original_cost_usd": cost_usd,
            "original_latency_s": round(latency_s, 4),
            "output_flags": list(output_flags),
        }
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".tmp-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False)
                os.replace(tmp, self._path(key))
            finally:
                Path(tmp).unlink(missing_ok=True)
        except OSError as exc:
            # La caché es una optimización: si no se puede escribir, el request igual responde.
            logger.warning("no se pudo escribir la caché: %s", exc)
