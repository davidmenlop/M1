"""Guardrail de salida: valida el contenido de una respuesta que ya cumple el contrato (ADR-030).

Pydantic garantiza la forma; esto revisa lo que dice:
1. fuga del prompt: marcadores internos o frases copiadas de las instrucciones;
2. pedido de datos sensibles al cliente (claves, códigos, tarjeta completa);
3. afirmaciones no verificables: políticas comerciales, porcentajes, plazos o montos que
   no estaban en la consulta;
4. tarjetas en la salida;
5. acciones obligatorias según lo que detectó el guardrail de entrada.

Nunca descarta la clasificación: reemplaza el texto riesgoso y agrega una acción para el
agente humano, que es quien envía la respuesta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.guardrails.input_guard import InputVerdict, redact_cards
from src.guardrails.rules import GuardrailRules, fold
from src.schemas import MAX_ACTIONS, Category, TriageResponse

INJECTION_FLAGS = {
    "ignorar_instrucciones", "cambio_de_rol", "actuar_como", "jailbreak", "exfiltracion",
    "mensaje_al_modelo", "dictar_salida", "etiqueta_de_rol", "delimitador", "codificado",
}
MODERATION_FLAGS = {"violencia", "autolesion"}
SENSITIVE_FLAGS = {"clave", "codigo_seguridad", "tarjeta"}
_PLACEHOLDERS = re.compile(r"\{(contract|examples)\}")
_EXAMPLES_SECTION = re.compile(r"##\s*Ejemplos.*", re.DOTALL)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass(frozen=True)
class OutputVerdict:
    response: TriageResponse
    flags: tuple[str, ...]
    modified: bool


def _shingles(text: str, size: int) -> set[str]:
    words = fold(text, leet=False).split()
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


def prompt_shingles(system_template: str, size: int) -> set[str]:
    """Frases del prompt que una respuesta legítima no tendría por qué copiar.

    Se excluyen los ejemplos (sus respuestas son, a propósito, parecidas a las del modelo)
    y el contrato (lo cubren los marcadores).
    """
    instructions = _PLACEHOLDERS.sub(" ", _EXAMPLES_SECTION.sub(" ", system_template))
    return _shingles(instructions, size)


def _in_query(fragment: str, folded_query: str) -> bool:
    """¿El dato ya estaba en la consulta? Los números se comparan como números ("$30" = "30 dólares")."""
    numbers = _NUMBER.findall(fragment)
    if numbers:
        query_numbers = {n.replace(".", "").replace(",", "") for n in _NUMBER.findall(folded_query)}
        return all(n.replace(".", "").replace(",", "") in query_numbers for n in numbers)
    return fragment.strip() in folded_query


def _with_action(actions: list[str], action: str) -> list[str]:
    if fold(action, leet=False) in (fold(a, leet=False) for a in actions):
        return actions
    if len(actions) < MAX_ACTIONS:
        return [*actions, action]
    return [*actions[: MAX_ACTIONS - 1], action]


def check_output(
    response: TriageResponse,
    query: str,
    rules: GuardrailRules,
    leak_shingles: set[str],
    input_verdict: InputVerdict | None = None,
) -> OutputVerdict:
    texts, actions_text = rules.texts, rules.texts["actions"]
    answer, actions = response.answer, list(response.actions)
    body = "\n".join([answer, *actions])
    folded_body = fold(body, leet=False)
    folded_query = fold(query, leet=False)
    flags: list[str] = []

    if rules.leak_markers.search(body, (folded_body,)) or _shingles(body, rules.leak_shingle_words) & leak_shingles:
        flags.append("fuga_prompt")
    if rules.sensitive_request.search(answer, (fold(answer, leet=False),)):
        flags.append("pide_datos_sensibles")
    for rule in rules.unverified:
        match = rule.search(answer, (fold(answer, leet=False),))
        if match and not (rule.unless_in_query and _in_query(match.group(0), folded_query)):
            flags.append(rule.id)

    if "fuga_prompt" in flags:
        answer = texts["safe_answer"]
        actions = [actions_text["manipulacion"], actions_text["humano"]]
    elif flags:
        answer = texts["neutral_answer"]
        actions = _with_action(actions, actions_text["revisar_respuesta"])

    redacted_answer, card_in_answer = redact_cards(answer)
    redacted_actions = [redact_cards(a)[0] for a in actions]
    if card_in_answer or redacted_actions != actions:
        flags.append("tarjeta_en_salida")
        answer, actions = redacted_answer, redacted_actions

    input_flags = set(input_verdict.flags) if input_verdict else set()
    if input_flags & INJECTION_FLAGS:
        actions = _with_action(actions, actions_text["manipulacion"])
    if input_flags & MODERATION_FLAGS:
        actions = _with_action(actions, actions_text["escalar"])
    if input_flags & SENSITIVE_FLAGS:
        actions = _with_action(actions, actions_text["datos_sensibles"])

    if answer == response.answer and actions == list(response.actions):
        return OutputVerdict(response=response, flags=tuple(flags), modified=False)
    updated = response.model_copy(update={"answer": answer, "actions": actions})
    return OutputVerdict(response=TriageResponse.model_validate(updated.model_dump()), flags=tuple(flags), modified=True)


def blocked_response(rules: GuardrailRules) -> TriageResponse:
    actions = rules.texts["actions"]
    return TriageResponse(
        answer=rules.texts["safe_answer"],
        confidence=0.0,
        category=Category.OTHER,
        actions=[actions["manipulacion"], actions["humano"]],
    )
