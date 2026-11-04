# Triage de soporte con LLMs — Nubbix (Proyecto Integrador M1)

Servicio que recibe una consulta de soporte en texto libre y devuelve un JSON validado
con `{answer, confidence, category, actions}`, con métricas de tokens, latencia y costo.

> **Estado:** en construcción. Fase 1 (contrato) completa. Falta CLI, proveedores,
> prompts, dataset y suite de evals.
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
python tests/test_pipeline.py      # 12/12 tests pasaron
python tests/test_anthropic_provider.py   # 13/13 tests pasaron (cliente falso, sin red)
python -m src.main --query "Me cobraron dos veces la suscripción"   # JSON validado (proveedor mock)
```

## Estado por fase

| Fase | Alcance | Estado |
|---|---|---|
| 0 | Configuración, entorno, higiene de repo | ✅ |
| 1 | Contrato Pydantic + tests | ✅ |
| 2 | CLI + `MockProvider` + pipeline + métricas | ✅ |
| 3 | Multi-proveedor y retry | ⏳ |
| 4 | Prompts versionados | ⏳ |
| 5 | Dataset de evaluación | ⏳ |
| 6 | Suite de evals | ⏳ |
| 7 | Comparativa empírica | ⏳ |
| 8 | Guardrails | ⏳ |
| 9 | Suite adversarial | ⏳ |
| 10 | Extras | ⏳ |
| 11 | Cierre y entrega | ⏳ |
