"""Carga de configuración desde .env y config/providers.yaml."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVIDERS_FILE = REPO_ROOT / "config" / "providers.yaml"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelConfig:
    id: str
    temperature: float | None
    max_tokens: int
    input_per_1m_usd: float
    output_per_1m_usd: float
    effort: str | None = None


DEFAULT_MODEL_KEY = "default"
EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}


@dataclass(frozen=True)
class Settings:
    default_provider: str
    default_prompt_version: str
    max_retries: int
    request_timeout_s: float
    metrics_path: Path
    log_level: str


def _env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _read_providers_file() -> dict[str, Any]:
    if not PROVIDERS_FILE.exists():
        raise ConfigError(f"no existe {PROVIDERS_FILE}")
    data = yaml.safe_load(PROVIDERS_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "providers" not in data:
        raise ConfigError("providers.yaml debe tener la clave 'providers'")
    return data


def load_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    providers = _read_providers_file()

    try:
        max_retries = int(_env("MAX_RETRIES", "2"))
        timeout_s = float(_env("REQUEST_TIMEOUT_S", "30"))
    except ValueError as exc:
        raise ConfigError("MAX_RETRIES y REQUEST_TIMEOUT_S deben ser numéricos") from exc
    if max_retries < 0 or timeout_s <= 0:
        raise ConfigError("se requiere MAX_RETRIES >= 0 y REQUEST_TIMEOUT_S > 0")

    log_level = _env("LOG_LEVEL", "INFO").upper()
    if not isinstance(logging.getLevelName(log_level), int):
        raise ConfigError(f"LOG_LEVEL inválido: {log_level}")

    metrics_path = Path(_env("METRICS_PATH", "data/metrics.jsonl"))
    if not metrics_path.is_absolute():
        metrics_path = REPO_ROOT / metrics_path

    return Settings(
        default_provider=_env("DEFAULT_PROVIDER", str(providers["default_provider"])),
        default_prompt_version=_env("DEFAULT_PROMPT_VERSION", "v1"),
        max_retries=max_retries,
        request_timeout_s=timeout_s,
        metrics_path=metrics_path,
        log_level=log_level,
    )


def available_models(provider: str) -> list[str]:
    providers = _read_providers_file()["providers"]
    try:
        return sorted(providers[provider]["models"])
    except (KeyError, TypeError):
        return []


def load_model_config(provider: str, model_key: str = DEFAULT_MODEL_KEY) -> ModelConfig:
    providers = _read_providers_file()["providers"]
    try:
        models = providers[provider]["models"]
    except (KeyError, TypeError) as exc:
        raise ConfigError(f"providers.yaml no define modelos para '{provider}'") from exc
    if model_key not in models:
        options = ", ".join(sorted(models))
        raise ConfigError(f"'{provider}' no tiene el modelo '{model_key}'. Opciones: {options}")
    raw = models[model_key]
    try:
        pricing = raw["pricing"]
        temperature = raw.get("temperature")
        effort = raw.get("effort")
        config = ModelConfig(
            id=str(raw["id"]),
            temperature=None if temperature is None else float(temperature),
            max_tokens=int(raw["max_tokens"]),
            input_per_1m_usd=float(pricing["input_per_1m_usd"]),
            output_per_1m_usd=float(pricing["output_per_1m_usd"]),
            effort=None if effort is None else str(effort),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(
            f"providers.yaml: el modelo '{model_key}' de '{provider}' necesita id, "
            "max_tokens y pricing válidos"
        ) from exc
    if config.effort is not None and config.effort not in EFFORT_LEVELS:
        raise ConfigError(f"effort inválido '{config.effort}'. Opciones: {sorted(EFFORT_LEVELS)}")
    return config
