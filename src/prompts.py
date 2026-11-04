"""Carga de prompts versionados desde prompts/*.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from src.config import REPO_ROOT

PROMPTS_DIR = REPO_ROOT / "prompts"
REQUIRED_KEYS = ("version", "technique", "system", "user_template")


class PromptError(ValueError):
    pass


@dataclass(frozen=True)
class PromptSpec:
    version: str
    technique: str
    system: str
    user_template: str

    def render(self, query: str, contract: str) -> tuple[str, str]:
        system = self.system.replace("{contract}", contract)
        user = self.user_template.replace("{query}", query)
        return system, user


def load_prompt(version: str, prompts_dir: Path = PROMPTS_DIR) -> PromptSpec:
    matches = sorted(prompts_dir.glob(f"{version}_*.yaml"))
    if len(matches) != 1:
        raise PromptError(
            f"se esperaba un único archivo {version}_*.yaml en {prompts_dir}, hallados: {len(matches)}"
        )
    path = matches[0]
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [key for key in REQUIRED_KEYS if key not in raw]
    if missing:
        raise PromptError(f"{path.name}: faltan claves {missing}")

    spec = PromptSpec(
        version=str(raw["version"]),
        technique=str(raw["technique"]),
        system=str(raw["system"]),
        user_template=str(raw["user_template"]),
    )
    if spec.version != version:
        raise PromptError(f"{path.name} declara version={spec.version}, se pidió {version}")
    if "{contract}" not in spec.system:
        raise PromptError(f"{path.name}: el system prompt debe contener {{contract}}")
    if "{query}" not in spec.user_template:
        raise PromptError(f"{path.name}: el user_template debe contener {{query}}")
    return spec
