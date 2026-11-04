"""Carga de prompts versionados desde prompts/*.yaml.

Un prompt es inmutable una vez evaluado: cambiarlo significa crear una versión nueva.

Claves del YAML:
- obligatorias: version, technique, system (con {contract}), user_template (con {query})
- opcionales:
  - description
  - examples: lista de {query, output}. Exige {examples} en el system. Cada output se
    valida contra el contrato al cargar: un ejemplo inválido enseña a romper el contrato.
  - internal_fields: {nombre: descripción}. Campos que el modelo debe devolver *además*
    del contrato (p. ej. un razonamiento breve). Se agregan al JSON Schema inyectado y
    el pipeline los descarta antes de validar, así que nunca llegan al cliente.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from src.config import REPO_ROOT
from src.schemas import TriageResponse

PROMPTS_DIR = REPO_ROOT / "prompts"
REQUIRED_KEYS = ("version", "technique", "system", "user_template")
CONTRACT_FIELDS = frozenset(TriageResponse.model_fields)


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class Example:
    query: str
    output: dict[str, Any]


@dataclass(frozen=True)
class PromptSpec:
    version: str
    technique: str
    system: str
    user_template: str
    description: str = ""
    examples: tuple[Example, ...] = ()
    internal_fields: dict[str, str] = field(default_factory=dict)

    def contract(self) -> str:
        """JSON Schema que se inyecta en el prompt: el contrato más los campos internos."""
        schema = TriageResponse.model_json_schema()
        if self.internal_fields:
            internal = {
                name: {"type": "string", "description": text}
                for name, text in self.internal_fields.items()
            }
            # Los campos internos van primero: el modelo razona antes de responder.
            schema["properties"] = {**internal, **schema["properties"]}
            schema["required"] = [*self.internal_fields, *schema["required"]]
        return json.dumps(schema, ensure_ascii=False)

    def render_examples(self) -> str:
        blocks = []
        for number, example in enumerate(self.examples, start=1):
            output = json.dumps(example.output, ensure_ascii=False)
            blocks.append(
                f"Ejemplo {number}\n<consulta>\n{example.query}\n</consulta>\nRespuesta:\n{output}"
            )
        return "\n\n".join(blocks)

    def render(self, query: str) -> tuple[str, str]:
        system = self.system.replace("{contract}", self.contract())
        if self.examples:
            system = system.replace("{examples}", self.render_examples())
        user = self.user_template.replace("{query}", query)
        return system, user

    def strip_internal(self, data: dict[str, Any]) -> dict[str, Any]:
        """Quita los campos internos antes de validar contra el contrato."""
        if not self.internal_fields:
            return data
        return {key: value for key, value in data.items() if key not in self.internal_fields}


def _parse_examples(path: Path, raw: Any, internal_fields: dict[str, str]) -> tuple[Example, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw:
        raise PromptError(f"{path.name}: 'examples' debe ser una lista no vacía")
    examples = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or "query" not in item or "output" not in item:
            raise PromptError(f"{path.name}: el ejemplo {index} necesita 'query' y 'output'")
        output = item["output"]
        if not isinstance(output, dict):
            raise PromptError(f"{path.name}: el output del ejemplo {index} debe ser un objeto")
        missing = [name for name in internal_fields if not str(output.get(name, "")).strip()]
        if missing:
            raise PromptError(f"{path.name}: al ejemplo {index} le faltan los campos internos {missing}")
        contract_part = {k: v for k, v in output.items() if k not in internal_fields}
        try:
            TriageResponse.model_validate(contract_part)
        except ValidationError as exc:
            raise PromptError(f"{path.name}: el ejemplo {index} no cumple el contrato: {exc}") from exc
        examples.append(Example(query=str(item["query"]).strip(), output=output))
    return tuple(examples)


def _parse_internal_fields(path: Path, raw: Any) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not raw:
        raise PromptError(f"{path.name}: 'internal_fields' debe ser un mapa nombre -> descripción")
    clashes = sorted(CONTRACT_FIELDS & set(raw))
    if clashes:
        raise PromptError(f"{path.name}: internal_fields no puede redefinir campos del contrato {clashes}")
    return {str(name): str(text).strip() for name, text in raw.items()}


def list_versions(prompts_dir: Path = PROMPTS_DIR) -> list[str]:
    return sorted(path.name.split("_", 1)[0] for path in prompts_dir.glob("v*_*.yaml"))


def load_prompt(version: str, prompts_dir: Path = PROMPTS_DIR) -> PromptSpec:
    matches = sorted(prompts_dir.glob(f"{version}_*.yaml"))
    if len(matches) != 1:
        available = ", ".join(list_versions(prompts_dir)) or "ninguna"
        raise PromptError(
            f"se esperaba un único archivo {version}_*.yaml en {prompts_dir}, "
            f"hallados: {len(matches)}. Versiones disponibles: {available}"
        )
    path = matches[0]
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [key for key in REQUIRED_KEYS if key not in raw]
    if missing:
        raise PromptError(f"{path.name}: faltan claves {missing}")

    internal_fields = _parse_internal_fields(path, raw.get("internal_fields"))
    spec = PromptSpec(
        version=str(raw["version"]),
        technique=str(raw["technique"]),
        system=str(raw["system"]),
        user_template=str(raw["user_template"]),
        description=" ".join(str(raw.get("description", "")).split()),
        examples=_parse_examples(path, raw.get("examples"), internal_fields),
        internal_fields=internal_fields,
    )
    if spec.version != version:
        raise PromptError(f"{path.name} declara version={spec.version}, se pidió {version}")
    if "{contract}" not in spec.system:
        raise PromptError(f"{path.name}: el system prompt debe contener {{contract}}")
    if "{query}" not in spec.user_template:
        raise PromptError(f"{path.name}: el user_template debe contener {{query}}")
    has_slot = "{examples}" in spec.system
    if spec.examples and not has_slot:
        raise PromptError(f"{path.name}: hay 'examples' pero el system no contiene {{examples}}")
    if has_slot and not spec.examples:
        raise PromptError(f"{path.name}: el system contiene {{examples}} pero no hay 'examples'")
    return spec
