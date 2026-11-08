"""Orquestación de una consulta: guardrail de entrada, prompt, proveedor, parseo, validación,
reintento, fallback y guardrail de salida."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field, replace

from pydantic import ValidationError

from src.cache import ResponseCache, cache_key
from src.config import ModelConfig
from src.guardrails import GuardReport, Guardrails, InputVerdict
from src.observability.pricing import compute_cost
from src.prompts import PromptSpec
from src.providers.base import LLMProvider, LLMResponse, ProviderError
from src.schemas import Category, TriageResponse

logger = logging.getLogger(__name__)

FALLBACK_ANSWER = "No pudimos procesar tu consulta automáticamente. Un agente te responderá a la brevedad."
FALLBACK_ACTIONS = ["Escalar la consulta a un agente humano"]
MAX_FEEDBACK_CHARS = 500


class ParseError(ValueError):
    pass


def extract_json(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rsplit("```", 1)[0]
    for candidate in (stripped, _outermost_braces(stripped)):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ParseError("no se encontró un objeto JSON válido en la respuesta")


def _outermost_braces(text: str) -> str:
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else ""


def _describe(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for err in exc.errors():
            location = ".".join(str(part) for part in err["loc"]) or "raiz"
            parts.append(f"{location}: {err['msg']}")
        message = "; ".join(parts)
    else:
        message = str(exc)
    return message[:MAX_FEEDBACK_CHARS]


def _repair_message(base_user: str, error: str) -> str:
    return (
        f"{base_user}\n\n"
        f"Tu respuesta anterior no cumplió el contrato: {error}\n"
        "Devolvé únicamente el objeto JSON corregido, sin texto adicional."
    )


@dataclass
class _Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    estimated: bool = False

    def add(self, response: LLMResponse) -> None:
        self.prompt_tokens += response.prompt_tokens
        self.completion_tokens += response.completion_tokens
        self.calls += 1
        self.estimated = self.estimated or response.token_source == "estimated"

    @property
    def token_source(self) -> str:
        if self.calls == 0:
            return "none"
        return "estimated" if self.estimated else "api"


@dataclass(frozen=True)
class TriageResult:
    request_id: str
    response: TriageResponse
    success: bool
    provider: str
    model: str
    prompt_version: str
    attempts: int
    prompt_tokens: int
    completion_tokens: int
    token_source: str
    latency_s: float
    cost_usd: float
    error: str | None = field(default=None)
    guard: GuardReport | None = field(default=None)
    cache: str | None = field(default=None)          # hit | miss | None (caché desactivada)
    cache_saved_usd: float = field(default=0.0)      # costo del request original, en un hit


class TriagePipeline:
    def __init__(
        self,
        provider: LLMProvider,
        model: ModelConfig,
        prompt: PromptSpec,
        max_retries: int,
        timeout_s: float,
        guardrails: Guardrails | None = None,
        cache: ResponseCache | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries debe ser >= 0")
        self._provider = provider
        self._model = model
        self._prompt = prompt
        self._max_retries = max_retries
        self._timeout_s = timeout_s
        self._guardrails = guardrails
        self._cache = cache

    def run(self, query: str) -> TriageResult:
        request_id = uuid.uuid4().hex
        started = time.perf_counter()
        usage = _Usage()
        verdict, report = self._check_input(query)
        if verdict is not None and verdict.blocked:
            logger.warning("guardrail de entrada: consulta bloqueada (%s)", ", ".join(verdict.flags))
            return self._result(request_id, self._guardrails.blocked_response(), True, 0, usage, started,
                                None, report)
        key = None
        if self._cache is not None:
            key = cache_key(query, provider=self._provider.name, model=self._model, prompt=self._prompt,
                            guardrails_sha256=self._guardrails.sha256 if self._guardrails else None)
            entry = self._cache.get(key)
            if entry is not None:
                if report is not None:
                    report.output_flags = entry.output_flags
                result = self._result(request_id, entry.response, True, 0, usage, started, None, report)
                return replace(result, cache="hit", cache_saved_usd=entry.original_cost_usd)

        text = verdict.text if verdict is not None else query
        system, base_user = self._prompt.render(text)
        attempts = 0
        last_error: str | None = None

        for _ in range(self._max_retries + 1):
            attempts += 1
            user = base_user if last_error is None else _repair_message(base_user, last_error)
            try:
                response = self._provider.complete(
                    system,
                    user,
                    model=self._model.id,
                    temperature=self._model.temperature,
                    max_tokens=self._model.max_tokens,
                    timeout_s=self._timeout_s,
                    effort=self._model.effort,
                )
            except ProviderError as exc:
                last_error = f"error del proveedor: {exc}"[:MAX_FEEDBACK_CHARS]
                logger.warning("intento %d falló: %s", attempts, last_error)
                continue

            usage.add(response)
            try:
                data = self._prompt.strip_internal(extract_json(response.text))
                validated = TriageResponse.model_validate(data)
            except (ParseError, ValidationError) as exc:
                last_error = _describe(exc)
                logger.warning("intento %d inválido: %s", attempts, last_error)
                continue

            validated = self._check_output(validated, query, verdict, report)
            result = self._result(request_id, validated, True, attempts, usage, started, None, report)
            if self._cache is not None and key is not None:
                self._cache.put(key, validated, cost_usd=result.cost_usd, latency_s=result.latency_s,
                                output_flags=report.output_flags if report else ())
                result = replace(result, cache="miss")
            return result

        logger.error("sin respuesta válida tras %d intentos; se usa fallback", attempts)
        fallback = TriageResponse(
            answer=FALLBACK_ANSWER,
            confidence=0.0,
            category=Category.OTHER,
            actions=FALLBACK_ACTIONS,
        )
        return self._result(request_id, fallback, False, attempts, usage, started, last_error, report)

    def _check_input(self, query: str) -> tuple[InputVerdict | None, GuardReport | None]:
        if self._guardrails is None:
            return None, None
        began = time.perf_counter()
        verdict = self._guardrails.check_input(query)
        report = GuardReport(input_action=verdict.action, input_flags=verdict.flags,
                             removed_sentences=verdict.removed_sentences,
                             overhead_ms=(time.perf_counter() - began) * 1000)
        return verdict, report

    def _check_output(self, response: TriageResponse, query: str, verdict: InputVerdict | None,
                      report: GuardReport | None) -> TriageResponse:
        if self._guardrails is None or report is None:
            return response
        began = time.perf_counter()
        checked = self._guardrails.check_output(response, query, self._prompt.system, verdict)
        report.output_flags = checked.flags
        report.output_modified = checked.modified
        report.overhead_ms += (time.perf_counter() - began) * 1000
        if checked.flags:
            logger.warning("guardrail de salida: %s", ", ".join(checked.flags))
        return checked.response

    def _result(
        self,
        request_id: str,
        response: TriageResponse,
        success: bool,
        attempts: int,
        usage: _Usage,
        started: float,
        error: str | None,
        guard: GuardReport | None = None,
    ) -> TriageResult:
        cost = compute_cost(
            usage.prompt_tokens,
            usage.completion_tokens,
            self._model.input_per_1m_usd,
            self._model.output_per_1m_usd,
        )
        return TriageResult(
            request_id=request_id,
            response=response,
            success=success,
            provider=self._provider.name,
            model=self._model.id,
            prompt_version=self._prompt.version,
            attempts=attempts,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            token_source=usage.token_source,
            latency_s=time.perf_counter() - started,
            cost_usd=cost,
            error=error,
            guard=guard,
        )
