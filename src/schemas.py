"""Contrato de salida del servicio de triage: {answer, confidence, category, actions}."""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_ANSWER_CHARS = 800
MAX_ACTIONS = 3


class Category(StrEnum):
    BILLING = "billing"
    TECHNICAL = "technical"
    ACCOUNT = "account"
    OTHER = "other"


class TriageResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    answer: str = Field(
        ...,
        min_length=1,
        max_length=MAX_ANSWER_CHARS,
        description="Respuesta sugerida para el cliente, en español, concreta y accionable.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confianza calibrada en la clasificación y en la respuesta (0 a 1).",
    )
    category: Category = Field(
        ...,
        description="Categoría principal del ticket.",
    )
    actions: list[str] = Field(
        ...,
        min_length=1,
        max_length=MAX_ACTIONS,
        description="Acciones concretas para el agente humano (1 a 3).",
    )

    @field_validator("answer")
    @classmethod
    def _answer_has_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("answer no puede estar vacio ni contener solo espacios")
        return value.strip()

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("actions", mode="before")
    @classmethod
    def _normalize_actions(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            text = " ".join(item.split())
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
        return cleaned[:MAX_ACTIONS]

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=True, separators=(",", ":"))

    @classmethod
    def json_contract(cls, indent: int | None = None) -> str:
        return json.dumps(cls.model_json_schema(), ensure_ascii=False, indent=indent)
