"""Guardrails de entrada y salida (Fase 8). El pipeline usa solo esta fachada."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.guardrails.input_guard import InputVerdict, check_input
from src.guardrails.output_guard import OutputVerdict, blocked_response, check_output, prompt_shingles
from src.guardrails.rules import GUARDRAILS_PATH, GuardrailConfigError, GuardrailRules, load_rules
from src.schemas import TriageResponse

__all__ = ["GuardReport", "Guardrails", "GuardrailConfigError", "InputVerdict", "OutputVerdict"]


@dataclass
class GuardReport:
    """Lo que hicieron los guardrails en un request (va a métricas y a los resultados de evals)."""

    input_action: str = "allow"
    input_flags: tuple[str, ...] = ()
    output_flags: tuple[str, ...] = ()
    output_modified: bool = False
    overhead_ms: float = 0.0
    removed_sentences: int = field(default=0)

    def to_dict(self) -> dict:
        return {
            "input": self.input_action,
            "input_flags": list(self.input_flags),
            "output_flags": list(self.output_flags),
            "output_modified": self.output_modified,
            "removed_sentences": self.removed_sentences,
            "overhead_ms": round(self.overhead_ms, 3),
        }


class Guardrails:
    def __init__(self, rules: GuardrailRules) -> None:
        self.rules = rules
        self._shingle_cache: dict[str, set[str]] = {}

    @classmethod
    def from_config(cls, path: Path = GUARDRAILS_PATH) -> Guardrails:
        return cls(load_rules(path))

    @property
    def sha256(self) -> str:
        return self.rules.sha256

    def check_input(self, query: str) -> InputVerdict:
        return check_input(query, self.rules)

    def check_output(self, response: TriageResponse, query: str, system_template: str,
                     verdict: InputVerdict | None = None) -> OutputVerdict:
        shingles = self._shingle_cache.get(system_template)
        if shingles is None:
            shingles = prompt_shingles(system_template, self.rules.leak_shingle_words)
            self._shingle_cache[system_template] = shingles
        return check_output(response, query, self.rules, shingles, verdict)

    def blocked_response(self) -> TriageResponse:
        return blocked_response(self.rules)
