# Manual de construcción

## Triage de soporte con LLMs — Proyecto Integrador M1 (Nubbix)

> De un repositorio vacío a un servicio multi-proveedor, con contrato validado,
> evals ejecutables, guardrails y métricas auditables.

**Estado del manual:** v0.4 — capítulos 0 a 4 completos.
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
| 5 — Prompts versionados | Fase 4 | YAML v1/v2/v3 y técnica de context engineering | ⏳ |
| 6 — Dataset | Fase 5 | 40 casos etiquetados, guía de etiquetado, casos borde | ⏳ |
| 7 — Suite de evals | Fase 6 | Runner, métricas globales y por categoría | ⏳ |
| 8 — Iteración empírica | Fase 7 | Comparativa prompts × proveedores y elección con datos | ⏳ |
| 9 — Guardrails | Fase 8 | Entrada, salida y medición de su efecto | ⏳ |
| 10 — Suite adversarial | Fase 9 | 10 ataques, mitigación y tasa de bloqueo | ⏳ |
| 11 — Extras | Fase 10 | Caché MD5 y/o FastAPI, comparativa de modelos | ⏳ |
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
  docs/03-fase-2-cli-y-mock.md docs/04-fase-3-multi-proveedor.md docs/apendice-a-decisiones.md docs/apendice-b-glosario.md \
  -o manual.pdf --toc --number-sections

# DOCX
pandoc docs/00-introduccion.md docs/01-fase-0-configuracion.md docs/02-fase-1-contrato.md \
  docs/03-fase-2-cli-y-mock.md docs/04-fase-3-multi-proveedor.md \
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
| 0.4 | 2026-11-04 | Capítulo 4 (Fase 3): OpenAI verificado, varios modelos por proveedor, Haiku 5.5. ADR-016 corregida, ADR-012 revisada, ADR-018 y ADR-019 |
