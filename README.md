# Triage de soporte con LLMs — Nubbix (Proyecto Integrador M1)

Servicio que recibe una consulta de soporte en texto libre y devuelve un JSON validado
con `{answer, confidence, category, actions}`, con métricas de tokens, latencia y costo.

> **Estado:** en construcción. Fases 0–4 completas: contrato, CLI, pipeline con
> reintento y fallback, métricas, proveedores OpenAI y Anthropic, y prompts v1/v2/v3.
> Faltan dataset, suite de evals, comparativa y guardrails.
>
> Este README se completa en el Capítulo 12 del manual. Por ahora, el documento
> principal del proyecto es el libro de construcción.

## Manual de construcción

El proyecto se documenta como un libro: una fase por capítulo, con decisiones,
trade-offs y el código explicado.

- [Índice del manual](docs/README.md)
- [Capítulo 0 — Introducción](docs/00-introduccion.md)
- [Capítulo 1 — Configuración](docs/01-fase-0-configuracion.md)
- [Capítulo 2 — El contrato](docs/02-fase-1-contrato.md)
- [Capítulo 3 — CLI y mock](docs/03-fase-2-cli-y-mock.md)
- [Capítulo 4 — Multi-proveedor](docs/04-fase-3-multi-proveedor.md)
- [Capítulo 5 — Prompts versionados](docs/05-fase-4-prompts.md)
- [Capítulo 6 — Dataset](docs/06-fase-5-dataset.md)
- [Apéndice A — Decisiones (ADR)](docs/apendice-a-decisiones.md)
- [Apéndice B — Glosario](docs/apendice-b-glosario.md)

## Requisitos

- Python 3.14 (gestionado con `uv`)
- `uv`

## Setup

```bash
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
```

En Windows:

```powershell
uv venv --python 3.14
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
Copy-Item .env.example .env
```

## Verificación actual

```bash
python -V                          # Python 3.14.3
python tests/test_schemas.py       # 10/10 tests pasaron
python tests/test_pipeline.py      # 15/15 tests pasaron
python tests/test_anthropic_provider.py   # 15/15 tests pasaron (cliente falso, sin red)
python tests/test_openai_provider.py      # 13/13 tests pasaron (cliente falso, sin red)
python tests/test_prompts.py              # 16/16 tests pasaron
python tests/test_dataset.py              # 21/21 tests pasaron
python evals/validate_dataset.py          # estructura, balance y leakage del dataset
python -m src.main --query "Me cobraron dos veces la suscripción"   # JSON validado (proveedor mock)
```

## Uso

```bash
# Sin claves: proveedor mock (default)
python -m src.main --query "Me cobraron dos veces la suscripción" --pretty

# Proveedores reales (requieren la clave en .env)
python -m src.main --query "..." --provider openai
python -m src.main --query "..." --provider anthropic                    # claude-haiku-4-5
python -m src.main --query "..." --provider anthropic --model haiku-5-5  # claude-haiku-5-5

# Versión del prompt: v1 (zero-shot, default), v2 (few-shot), v3 (few-shot + CoT + seguridad)
python -m src.main --query "..." --provider openai --prompt v2

# La consulta también puede llegar por stdin
echo "No puedo iniciar sesión" | python -m src.main --query -
```

JSON del contrato a stdout; logs a stderr; una línea por request en `data/metrics.jsonl`.
Los modelos, sus parámetros y sus precios están en `config/providers.yaml`.

## Estado por fase

| Fase | Alcance | Estado |
|---|---|---|
| 0 | Configuración, entorno, higiene de repo | ✅ |
| 1 | Contrato Pydantic + tests | ✅ |
| 2 | CLI + `MockProvider` + pipeline + métricas | ✅ |
| 3 | Multi-proveedor y retry | ✅ |
| 4 | Prompts versionados | ✅ |
| 5 | Dataset de evaluación | 🟡 40 casos en borrador, pendientes de validación humana |
| 6 | Suite de evals | ⏳ |
| 7 | Comparativa empírica | ⏳ |
| 8 | Guardrails | ⏳ |
| 9 | Suite adversarial | ⏳ |
| 10 | Extras | ⏳ |
| 11 | Cierre y entrega | ⏳ |
