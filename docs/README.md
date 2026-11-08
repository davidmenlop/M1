# Manual de construcción

## Triage de soporte con LLMs — Proyecto Integrador M1 (Nubbix)

> De un repositorio vacío a un servicio multi-proveedor, con contrato validado,
> evals ejecutables, guardrails y métricas auditables.

**Estado del manual:** v0.12 — capítulos 0 a 11 completos.
**Última actualización:** 2026-11-04.
**Fuente de verdad:** el código del repositorio. Si el manual y el código difieren, gana el código; el manual se corrige en el mismo commit.

---

## Qué es este manual

Este no es un README ni una guía de instalación. Es el **registro de construcción** del proyecto: qué decidimos, por qué, qué alternativas descartamos y cómo verificamos que funciona.

Cada capítulo corresponde a una fase del desarrollo y tiene la misma estructura:

1. **Objetivo** — qué problema resuelve la fase.
2. **Resultado** — qué queda en el repositorio al terminarla.
3. **Conceptos** — lo que hay que entender antes de leer el código.
4. **Paso a paso** — comandos y archivos, con su justificación.
5. **Código explicado** — línea por línea cuando aporta.
6. **Verificación** — cómo saber que está bien, con salida esperada.
7. **Decisiones y trade-offs** — lo que se eligió y lo que se descartó.
8. **Errores comunes** — cómo se ven y cómo se corrigen.
9. **Checklist de cierre** — criterio objetivo para avanzar.

La regla es simple: **ninguna decisión técnica se sostiene con intuición**. Si no hay una medición o un criterio explícito, queda marcada como pendiente.

---

## Cómo está organizado

| Capítulo | Fase | Contenido | Estado |
|---|---|---|---|
| [0 — Introducción](00-introduccion.md) | — | Problema, contrato, principios y arquitectura objetivo | ✅ |
| [1 — Configuración](01-fase-0-configuracion.md) | Fase 0 | Intérprete, uv, venv, higiene de repo, configuración base | ✅ |
| [2 — El contrato](02-fase-1-contrato.md) | Fase 1 | `src/schemas.py` línea por línea, validadores y tests | ✅ |
| [3 — CLI y mock](03-fase-2-cli-y-mock.md) | Fase 2 | CLI, `MockProvider`, pipeline con reintento, métricas JSONL | ✅ |
| [4 — Multi-proveedor](04-fase-3-multi-proveedor.md) | Fase 3 | Abstracción `LLMProvider`, OpenAI, Anthropic, `--model`, corrección de la temperatura | ✅ |
| [5 — Prompts versionados](05-fase-4-prompts.md) | Fase 4 | YAML v1/v2/v3, campos internos, criterio de selección | ✅ |
| [6 — Dataset](06-fase-5-dataset.md) | Fase 5 | 40 casos, guía de etiquetado, revisión humana, leakage | ✅ |
| [7 — Suite de evals](07-fase-6-evals.md) | Fase 6 | Runner, métricas, umbrales, resultados trazables | ✅ |
| [8 — Iteración empírica](08-fase-7-iteracion.md) | Fase 7 | Prompt v4, comparativa prompts × modelos, elección por script, holdout | ✅ |
| [9 — Guardrails](09-fase-8-guardrails.md) | Fase 8 | Entrada, salida, capas y medición de su efecto | ✅ |
| [10 — Suite adversarial](10-fase-9-adversarial.md) | Fase 9 | 10 ataques congelados, capas aisladas, mitigación medida | ✅ |
| [11 — Extras](11-fase-10-extras.md) | Fase 10 | Caché MD5, comparativa de modelos | ✅ |
| 12 — Cierre | Fase 11 | README final, clon limpio, entrega | ⏳ |

**Apéndices**

- [A — Registro de decisiones (ADR)](apendice-a-decisiones.md)
- [B — Glosario](apendice-b-glosario.md)

---

## Convenciones

- Los bloques ` ```bash ` se ejecutan **desde la raíz del repositorio**.
- Las referencias `src/schemas.py:21` significan *archivo:línea* del código vigente.
- Una **Decisión** es un trade-off registrado también en el Apéndice A, con su motivo y sus consecuencias.
- Los precios y los IDs de modelo son datos volátiles: se verifican antes de cada comparativa.
- Todo lo que se mide se registra; si una métrica no responde una pregunta concreta, no va.

---

## Cómo exportar el libro

El manual es Markdown plano, sin dependencias. Si querés un PDF o un `.docx`:

```bash
# PDF con tabla de contenidos
pandoc docs/00-introduccion.md docs/01-fase-0-configuracion.md docs/02-fase-1-contrato.md \
  docs/03-fase-2-cli-y-mock.md docs/04-fase-3-multi-proveedor.md docs/05-fase-4-prompts.md docs/06-fase-5-dataset.md docs/07-fase-6-evals.md docs/08-fase-7-iteracion.md docs/09-fase-8-guardrails.md docs/10-fase-9-adversarial.md docs/11-fase-10-extras.md docs/apendice-a-decisiones.md docs/apendice-b-glosario.md \
  -o manual.pdf --toc --number-sections

# DOCX
pandoc docs/00-introduccion.md docs/01-fase-0-configuracion.md docs/02-fase-1-contrato.md \
  docs/03-fase-2-cli-y-mock.md docs/04-fase-3-multi-proveedor.md docs/05-fase-4-prompts.md docs/06-fase-5-dataset.md docs/07-fase-6-evals.md docs/08-fase-7-iteracion.md docs/09-fase-8-guardrails.md docs/10-fase-9-adversarial.md docs/11-fase-10-extras.md \
  -o manual.docx --toc
```

`pandoc` es opcional. El repositorio no depende de él para ejecutarse.

---

## Historial del manual

| Versión | Fecha | Cambio |
|---|---|---|
| 0.1 | 2026-10-22 | Capítulos 0–2, apéndices A y B |
| 0.2 | 2026-10-27 | Capítulo 3 (Fase 2): CLI, mock, pipeline, métricas. ADR-012 a ADR-014 |
| 0.3 | 2026-10-28 | Proveedor Anthropic verificado con llamada real. Temperatura opcional por modelo. ADR-015 a ADR-017 |
| 0.12 | 2026-11-08 | Capítulo 11 (Fase 10): caché MD5 y comparativa de modelos. ADR-033 |
| 0.11 | 2026-11-08 | Capítulo 10 (Fase 9): suite adversarial, guardrails v2. ADR-032 |
| 0.10 | 2026-11-05 | Capítulo 9 (Fase 8): guardrails de entrada y salida, medición offline y con el ganador. ADR-030 y ADR-031 |
| 0.9 | 2026-11-05 | Capítulo 8, ronda 2: `oth-01` corregido, holdout de 14 casos, comparativa sin Haiku 4.5. ADR-029 |
| 0.8 | 2026-11-04 | Capítulo 8 (Fase 7): prompt v4, comparativa de 12 combinaciones, `select.py`, holdout. ADR-027 y ADR-028 |
| 0.7 | 2026-11-04 | Capítulo 7 (Fase 6): runner de evals, primera corrida real. Validación humana del dataset. ADR-026 |
| 0.6 | 2026-11-04 | Capítulo 6 (Fase 5): dataset, guía de etiquetado, revisión humana. ADR-023 a ADR-025 |
| 0.5 | 2026-11-04 | Capítulo 5 (Fase 4): prompts v2 y v3, criterio de selección. ADR-020 a ADR-022 |
| 0.4 | 2026-11-04 | Capítulo 4 (Fase 3): OpenAI verificado, varios modelos por proveedor, Haiku 5.5. ADR-016 corregida, ADR-012 revisada, ADR-018 y ADR-019 |
