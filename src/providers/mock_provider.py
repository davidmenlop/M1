"""Proveedor determinista para desarrollo y evals sin API keys.

No es un LLM: clasifica por palabras clave. Sirve para validar el pipeline de punta
a punta. Su accuracy no representa a un modelo real y no se usa para elegir prompts.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata

from src.providers.base import LLMProvider, LLMResponse

QUERY_PATTERN = re.compile(r"<consulta>\s*(.*?)\s*</consulta>", re.DOTALL)

KEYWORDS: dict[str, tuple[str, ...]] = {
    "billing": ("cobr", "factura", "reintegr", "pago", "suscrip", "cargo", "tarifa"),
    "technical": (
        "error",
        "dashboard",
        "falla",
        "cayo",
        "no funciona",
        "integracion",
        "sincroniz",
        "500",
        "bug",
        "tira",
    ),
    "account": (
        "usuario",
        "email",
        "correo",
        "contrasena",
        "password",
        "permiso",
        "cuenta",
        "administrador",
        "acceso",
    ),
    "other": ("descuento", "plan", "empresa", "empleados", "comercial", "demo", "contratar"),
}

TOPICS = {
    "billing": "facturación y cobros",
    "technical": "un inconveniente técnico",
    "account": "la gestión de tu cuenta",
    "other": "planes y condiciones comerciales",
}

ACTIONS = {
    "billing": ["Verificar pagos y cargos del cliente", "Iniciar reintegro si corresponde"],
    "technical": ["Reproducir el problema con la cuenta del cliente", "Escalar a ingeniería si persiste"],
    "account": ["Verificar la identidad del solicitante", "Aplicar el cambio en la cuenta"],
    "other": ["Derivar la consulta a comercial", "Enviar información de planes vigentes"],
}


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def classify(query: str) -> tuple[str, float]:
    text = _normalize(query)
    scores = {cat: sum(text.count(kw) for kw in kws) for cat, kws in KEYWORDS.items()}
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    (best, best_score), (_, runner_up) = ranked[0], ranked[1]
    if best_score == 0:
        return "other", 0.3
    if best_score == runner_up:
        return "other", 0.4
    margin = best_score - runner_up
    return best, round(min(0.95, 0.6 + 0.1 * margin), 2)


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, malformed_attempts: int = 0) -> None:
        self._malformed_remaining = malformed_attempts

    def complete(
        self,
        system: str,
        user: str,
        *,
        model: str,
        temperature: float | None,
        max_tokens: int,
        timeout_s: float,
        effort: str | None = None,
    ) -> LLMResponse:
        if self._malformed_remaining > 0:
            self._malformed_remaining -= 1
            text = "Lo siento, no puedo responder en formato JSON."
        else:
            text = self._build_payload(user)
        return LLMResponse(
            text=text,
            prompt_tokens=math.ceil(len(system + user) / 4),
            completion_tokens=math.ceil(len(text) / 4),
            token_source="estimated",
        )

    @staticmethod
    def _build_payload(user: str) -> str:
        match = QUERY_PATTERN.search(user)
        query = match.group(1) if match else user
        category, confidence = classify(query)
        payload = {
            "answer": (
                f"Gracias por escribirnos. Revisamos tu consulta sobre {TOPICS[category]} "
                "y te respondemos a la brevedad."
            ),
            "confidence": confidence,
            "category": category,
            "actions": ACTIONS[category],
        }
        return json.dumps(payload, ensure_ascii=False)
