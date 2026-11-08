"""Carga de config/guardrails.yaml y normalización de texto para buscar patrones."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARDRAILS_PATH = REPO_ROOT / "config" / "guardrails.yaml"

_INVISIBLE = re.compile(r"[​-‏⁠-⁤﻿­]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_SPACED_LETTERS = re.compile(r"\b(?:[a-z] ){3,}[a-z]\b")
# Homoglifos: letras griegas y cirílicas que se ven como latinas (NFKC no las convierte).
_CONFUSABLES = str.maketrans({
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "һ": "h", "ӏ": "l", "ԛ": "q", "ԝ": "w",
    "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i", "κ": "k", "μ": "u", "ν": "v", "ο": "o", "ρ": "p",
    "τ": "t", "υ": "u", "χ": "x", "ς": "c", "σ": "o", "ω": "w", "ζ": "z",
})
_SPACES = re.compile(r"\s+")


class GuardrailConfigError(ValueError):
    pass


def clean(text: str) -> str:
    """Lo que se le manda al modelo: NFKC, sin caracteres invisibles ni de control."""
    text = unicodedata.normalize("NFKC", text)
    return _CONTROL.sub("", _INVISIBLE.sub("", text))


def fold(text: str, *, leet: bool = True) -> str:
    """Forma canónica solo para buscar patrones: resiste mayúsculas, tildes, leetspeak y letras espaciadas."""
    text = clean(text).lower().translate(_CONFUSABLES)
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    if leet:
        text = text.translate(_LEET)
    text = _SPACED_LETTERS.sub(lambda m: m.group(0).replace(" ", ""), text)
    return _SPACES.sub(" ", text).strip()


@dataclass(frozen=True)
class Rule:
    id: str
    pattern: re.Pattern[str]
    folded: bool
    replacement: str | None = None
    unless_in_query: bool = False

    def search(self, raw: str, folded: tuple[str, ...]) -> re.Match[str] | None:
        """Busca en el texto original o en cada variante normalizada (con y sin leetspeak)."""
        if not self.folded:
            return self.pattern.search(raw)
        for variant in folded:
            if match := self.pattern.search(variant):
                return match
        return None


def variants(text: str) -> tuple[str, ...]:
    """Variantes normalizadas: sin leetspeak (números intactos) y con leetspeak."""
    plain, leet = fold(text, leet=False), fold(text)
    return (plain,) if plain == leet else (plain, leet)


def _compile(entry: dict[str, Any], where: str) -> Rule:
    if ("folded" in entry) == ("raw" in entry):
        raise GuardrailConfigError(f"{where}: cada regla necesita 'folded' o 'raw', no ambos")
    source = entry.get("folded") or entry.get("raw")
    try:
        pattern = re.compile(source)
    except re.error as exc:
        raise GuardrailConfigError(f"{where}: regex inválida: {exc}") from exc
    return Rule(
        id=entry.get("id", where),
        pattern=pattern,
        folded="folded" in entry,
        replacement=entry.get("replacement"),
        unless_in_query=bool(entry.get("unless_in_query", False)),
    )


@dataclass(frozen=True)
class GuardrailRules:
    max_chars: int
    min_words_after_removal: int
    injection: tuple[Rule, ...]
    delimiter: Rule
    moderation: tuple[Rule, ...]
    sensitive: tuple[Rule, ...]
    leak_markers: Rule
    leak_shingle_words: int
    sensitive_request: Rule
    unverified: tuple[Rule, ...]
    texts: dict[str, Any]
    sha256: str


def load_rules(path: Path = GUARDRAILS_PATH) -> GuardrailRules:
    raw_bytes = path.read_bytes()
    data = yaml.safe_load(raw_bytes)
    try:
        inp, out, texts = data["input"], data["output"], data["texts"]
        rules = GuardrailRules(
            max_chars=int(inp["max_chars"]),
            min_words_after_removal=int(inp["min_words_after_removal"]),
            injection=tuple(_compile(e, f"input.injection[{i}]") for i, e in enumerate(inp["injection"])),
            delimiter=_compile({"id": "delimitador", **inp["delimiter"]}, "input.delimiter"),
            moderation=tuple(_compile(e, f"input.moderation[{i}]") for i, e in enumerate(inp["moderation"])),
            sensitive=tuple(_compile(e, f"input.sensitive[{i}]") for i, e in enumerate(inp["sensitive"])),
            leak_markers=_compile({"id": "fuga_prompt", "folded": out["leak_markers"]}, "output.leak_markers"),
            leak_shingle_words=int(out["leak_shingle_words"]),
            sensitive_request=_compile({"id": "pide_datos_sensibles", "folded": out["sensitive_request"]},
                                       "output.sensitive_request"),
            unverified=tuple(_compile(e, f"output.unverified[{i}]") for i, e in enumerate(out["unverified"])),
            texts=texts,
            sha256=hashlib.sha256(raw_bytes).hexdigest(),
        )
    except (KeyError, TypeError) as exc:
        raise GuardrailConfigError(f"{path.name}: falta o sobra una clave: {exc}") from exc
    for key in ("manipulacion", "escalar", "datos_sensibles", "revisar_respuesta", "humano"):
        if key not in rules.texts.get("actions", {}):
            raise GuardrailConfigError(f"{path.name}: falta texts.actions.{key}")
    return rules
