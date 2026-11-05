"""Guardrail de entrada: sanea la consulta antes de que llegue al modelo (ADR-030).

Orden de las capas:
1. limpieza (NFKC, sin invisibles ni caracteres de control) y truncado;
2. datos sensibles: claves, códigos de seguridad y tarjetas se ocultan;
3. delimitador: `<consulta>` / `</consulta>` dentro de la consulta se neutraliza;
4. inyección: se eliminan las oraciones con señales de inyección; si no queda un pedido
   legítimo, se bloquea (no se llama al modelo);
5. moderación: violencia o autolesión no bloquean, pero se marcan para escalar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.guardrails.rules import GuardrailRules, clean, variants

_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
_DIGIT_RUN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_WORD = re.compile(r"[^\W\d_]{2,}")

ALLOW, SANITIZE, BLOCK = "allow", "sanitize", "block"


@dataclass(frozen=True)
class InputVerdict:
    text: str                      # lo que se le manda al modelo
    action: str                    # allow | sanitize | block
    flags: tuple[str, ...]         # señales detectadas (ids de reglas)
    removed_sentences: int = 0

    @property
    def blocked(self) -> bool:
        return self.action == BLOCK


def luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def redact_cards(text: str) -> tuple[str, bool]:
    found = False

    def replace(match: re.Match[str]) -> str:
        nonlocal found
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            found = True
            return "[tarjeta oculta]"
        return match.group(0)

    return _DIGIT_RUN.sub(replace, text), found


def check_input(query: str, rules: GuardrailRules) -> InputVerdict:
    flags: list[str] = []
    text = clean(query).strip()
    original = text

    if len(text) > rules.max_chars:
        text = text[: rules.max_chars]
        flags.append("truncada")

    text, card_found = redact_cards(text)
    if card_found:
        flags.append("tarjeta")
    for rule in rules.sensitive:
        text, count = rule.pattern.subn(rule.replacement, text)
        if count:
            flags.append(rule.id)

    if rules.delimiter.pattern.search(text):
        text = rules.delimiter.pattern.sub(lambda m: m.group(0).replace("<", "‹").replace(">", "›"), text)
        flags.append(rules.delimiter.id)

    kept, removed = [], 0
    for sentence in _SENTENCES.split(text):
        hits = [rule.id for rule in rules.injection if rule.search(sentence, variants(sentence))]
        if hits:
            removed += 1
            flags.extend(hit for hit in hits if hit not in flags)
        elif sentence.strip():
            kept.append(sentence.strip())
    if removed:
        text = " ".join(kept)

    folded = variants(text)
    flags.extend(rule.id for rule in rules.moderation if rule.search(text, folded))

    if removed and len(_WORD.findall(text)) < rules.min_words_after_removal:
        return InputVerdict(text="", action=BLOCK, flags=tuple(flags), removed_sentences=removed)
    action = SANITIZE if text != original else ALLOW
    return InputVerdict(text=text, action=action, flags=tuple(flags), removed_sentences=removed)
