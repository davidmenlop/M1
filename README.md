# Triage de soporte con LLMs — Nubbix (Proyecto Integrador M1)

Servicio que recibe una consulta de soporte en texto libre y devuelve un JSON validado
con `{answer, confidence, category, actions}`, con métricas de tokens, latencia y costo.

> **Estado:** en construcción. Fases 0–7 completas: contrato, CLI, pipeline con
> reintento y fallback, métricas, proveedores OpenAI y Anthropic, prompts v1–v4,
> dataset de 40 casos validado por una persona, suite de evals y comparativa
> empírica (gana Haiku 5.5 con v4). Faltan los guardrails y la suite adversarial.
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
- [Capítulo 7 — Suite de evals](docs/07-fase-6-evals.md)
- [Capítulo 8 — Iteración empírica](docs/08-fase-7-iteracion.md)
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
python tests/test_eval_metrics.py         # 14/14 tests pasaron
python evals/validate_dataset.py --strict # dataset validado: estructura, balance y leakage
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

## Evaluación

```bash
python evals/runner.py --provider mock                     # sin claves
python evals/runner.py --provider openai --prompt v2       # split dev (32 casos)
python evals/runner.py --provider anthropic --repeat 3     # media y desvío
python evals/runner.py --compare evals/results/*.json      # tabla comparativa
python evals/select.py evals/results/*.json                # aplica el criterio de selección
```

Solo se evalúan casos validados por una persona (`evals/dataset.jsonl`, 32 dev / 8 holdout).
Cada corrida guarda en `evals/results/` las métricas, cada caso y los hashes del prompt
y del dataset. Resultados actuales:

| corrida | proveedor / modelo | prompt | split | casos | schema | retry | accuracy | macro-F1 | recall mín | action | Brier | USD/req | p95 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 20261104-175711 | mock / mock-1 | v1 | dev | 32×1 | 100% | 0% | 59% | 0.567 | 25% | 0.406 | 0.219 | 0.00000 | 0.000 |
| 20261104-175754 | openai / gpt-4.1-mini | v1 | dev | 32×1 | 100% | 0% | 91% | 0.908 | 78% | 0.859 | 0.089 | 0.00037 | 1.863 |
| 20261104-233409 | openai / gpt-4.1-mini | v2 | dev | 32×1 | 100% | 0% | 94% | 0.938 | 78% | 0.984 | 0.078 | 0.00069 | 1.800 |
| 20261104-233458 | openai / gpt-4.1-mini | v3 | dev | 32×1 | 100% | 0% | 94% | 0.938 | 78% | 0.969 | 0.076 | 0.00096 | 1.817 |
| 20261104-233546 | openai / gpt-4.1-mini | v4 | dev | 32×1 | 100% | 0% | 100% | 1.000 | 100% | 0.969 | 0.020 | 0.00105 | 1.748 |
| 20261104-233906 | anthropic / claude-haiku-5-5 | v1 | dev | 32×3 | 100% ±0% | 1% ±2% | 92% ±2% | 0.918 ±0.017 | 78% ±0% | 0.943 ±0.009 | 0.107 ±0.000 | 0.00022 ±0.00000 | 2.890 ±0.340 |
| 20261104-234136 | anthropic / claude-haiku-5-5 | v2 | dev | 32×3 | 100% ±0% | 0% ±0% | 94% ±0% | 0.938 ±0.000 | 78% ±0% | 0.969 ±0.016 | 0.090 ±0.006 | 0.00032 ±0.00000 | 2.204 ±0.394 |
| 20261104-234443 | anthropic / claude-haiku-5-5 | v3 | dev | 32×3 | 100% ±0% | 0% ±0% | 94% ±0% | 0.938 ±0.000 | 78% ±0% | 0.943 ±0.018 | 0.082 ±0.013 | 0.00046 ±0.00001 | 2.700 ±0.249 |
| 20261104-234752 | anthropic / claude-haiku-5-5 | v4 | dev | 32×3 | 100% ±0% | 0% ±0% | 100% ±0% | 1.000 ±0.000 | 100% ±0% | 0.969 ±0.016 | 0.044 ±0.009 | 0.00050 ±0.00000 | 2.795 ±0.062 |
| 20261104-235214 | anthropic / claude-haiku-4-5 | v1 | dev | 32×3 | 100% ±0% | 0% ±0% | 97% ±0% | 0.969 ±0.000 | 89% ±0% | 0.885 ±0.009 | 0.053 ±0.001 | 0.00170 ±0.00002 | 3.194 ±0.106 |
| 20261104-235523 | anthropic / claude-haiku-4-5 | v2 | dev | 32×3 | 100% ±0% | 0% ±0% | 95% ±2% | 0.948 ±0.018 | 81% ±6% | 0.964 ±0.009 | 0.078 ±0.015 | 0.00243 ±0.00001 | 2.464 ±0.012 |
| 20261104-235933 | anthropic / claude-haiku-4-5 | v3 | dev | 32×3 | 100% ±0% | 0% ±0% | 94% ±0% | 0.938 ±0.000 | 78% ±0% | 0.938 ±0.016 | 0.078 ±0.003 | 0.00343 ±0.00000 | 3.139 ±0.099 |
| 20261105-000348 | anthropic / claude-haiku-4-5 | v4 | dev | 32×3 | 100% ±0% | 0% ±0% | 100% ±0% | 1.000 ±0.000 | 100% ±0% | 0.917 ±0.036 | 0.031 ±0.001 | 0.00372 ±0.00001 | 3.227 ±0.269 |
| 20261105-000447 | anthropic / claude-haiku-5-5 | v4 | holdout | 8×3 | 100% ±0% | 0% ±0% | 100% ±0% | 1.000 ±0.000 | 100% ±0% | 0.896 ±0.036 | 0.012 ±0.001 | 0.00051 ±0.00000 | 2.416 ±0.176 |

El mock es la línea base de un clasificador por palabras clave. Anthropic promedia 3 corridas (±desvío).

**Combinación elegida: Haiku 5.5 con v4** (criterio de ADR-022, aplicado por
`python evals/select.py evals/results/*.json`). Empata con `gpt-4.1-mini` + v4 en
macro-F1 y action score, y cuesta la mitad. Confirmado en holdout (8/8). Salvedad: v4 se
escribió después de ver dev y el holdout no tiene casos de sus reglas nuevas
([Capítulo 8](docs/08-fase-7-iteracion.md)).

```bash
python -m src.main --provider anthropic --model haiku-5-5 --query "..."   # prompt v4 por defecto
```

## Estado por fase

| Fase | Alcance | Estado |
|---|---|---|
| 0 | Configuración, entorno, higiene de repo | ✅ |
| 1 | Contrato Pydantic + tests | ✅ |
| 2 | CLI + `MockProvider` + pipeline + métricas | ✅ |
| 3 | Multi-proveedor y retry | ✅ |
| 4 | Prompts versionados | ✅ |
| 5 | Dataset de evaluación | ✅ 40 casos validados por una persona |
| 6 | Suite de evals | ✅ |
| 7 | Comparativa empírica | ✅ Haiku 5.5 + v4 |
| 8 | Guardrails | ⏳ |
| 9 | Suite adversarial | ⏳ |
| 10 | Extras | ⏳ |
| 11 | Cierre y entrega | ⏳ |
