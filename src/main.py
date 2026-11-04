"""CLI de triage: recibe una consulta y devuelve un JSON validado por el contrato."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from src.config import ConfigError, load_model_config, load_settings
from src.observability.metrics import append_metric, build_record
from src.pipeline import TriagePipeline
from src.prompts import PromptError, load_prompt
from src.providers.base import ProviderFatalError, ProviderUnavailable
from src.providers.factory import build_provider

logger = logging.getLogger("triage")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.main",
        description="Triage de soporte Nubbix: consulta en texto libre -> JSON validado.",
    )
    parser.add_argument("--query", required=True, help="consulta del cliente; '-' lee desde stdin")
    parser.add_argument("--provider", help="mock | openai | anthropic (por defecto: DEFAULT_PROVIDER)")
    parser.add_argument("--prompt", help="versión del prompt, por ejemplo v1 (por defecto: DEFAULT_PROMPT_VERSION)")
    parser.add_argument("--pretty", action="store_true", help="imprime el JSON indentado")
    return parser.parse_args(argv)


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as exc:
        return _fail(str(exc))

    logging.basicConfig(
        level=settings.log_level,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )

    query = (sys.stdin.read() if args.query == "-" else args.query).strip()
    if not query:
        return _fail("la consulta está vacía")

    provider_name = args.provider or settings.default_provider
    prompt_version = args.prompt or settings.default_prompt_version

    try:
        provider = build_provider(provider_name)
        model = load_model_config(provider_name)
        prompt = load_prompt(prompt_version)
    except (ProviderUnavailable, ConfigError, PromptError) as exc:
        return _fail(str(exc))

    pipeline = TriagePipeline(
        provider=provider,
        model=model,
        prompt=prompt,
        max_retries=settings.max_retries,
        timeout_s=settings.request_timeout_s,
    )
    try:
        result = pipeline.run(query)
    except ProviderFatalError as exc:
        return _fail(f"el proveedor '{provider_name}' rechazó la solicitud: {exc}")
    logger.info(
        "request=%s provider=%s attempts=%d success=%s cost_usd=%.8f latency_s=%.4f",
        result.request_id,
        result.provider,
        result.attempts,
        result.success,
        result.cost_usd,
        result.latency_s,
    )

    exit_code = 0
    try:
        append_metric(settings.metrics_path, build_record(result, query))
    except OSError as exc:
        logger.error("no se pudo escribir la métrica en %s: %s", settings.metrics_path, exc)
        exit_code = 1

    if args.pretty:
        print(json.dumps(result.response.to_dict(), ensure_ascii=True, indent=2))
    else:
        print(result.response.to_json())
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
