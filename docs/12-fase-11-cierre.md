# Capítulo 12 — Cierre y entrega (Fase 11)

> El criterio de cierre de la consigna: alguien que clone el repositorio debería poder
> instalarlo y correrlo sin preguntar nada. Se verificó haciendo exactamente eso.

---

## 1. Objetivo

- README final, consistente con el código;
- prueba en un clon limpio, siguiendo el README, sin claves;
- checklist de entrega y rúbrica, punto por punto;
- registro de lo que queda abierto.

## 2. Prueba en un clon limpio

```bash
git clone --branch desarrollo <repo> clean && cd clean
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env               # sin completar ninguna clave
```

Resultado, en una carpeta nueva y sin `.env` previo:

| Paso | Resultado |
|---|---|
| instalación | Python 3.14.3; dependencias fijadas instaladas sin compilar nada |
| `python -c "import openai, anthropic, pydantic, yaml, dotenv"` | ok |
| 11 archivos de tests | **155/155**, sin red |
| `python -m src.main --query "..."` (mock) | JSON válido, una línea en `data/metrics.jsonl`, exit 0 |
| consulta por stdin | ok |
| ataque puro | bloqueado sin llamar al modelo |
| `evals/validate_dataset.py --strict` | 46/46 validados, sin leakage |
| `evals/runner.py --provider mock` | 59 % de accuracy (línea base), guardrails activos |
| `evals/select.py evals/results/*.json` | reproduce la elección: Haiku 5.5 + v4 |
| `evals/guardrails_report.py` | 0 falsos positivos, 20 respuestas marcadas |
| `evals/adversarial.py --input-only` y `--compare` | 4/10 bloqueados; tabla de las 7 corridas |
| `--provider openai` sin clave | `error: falta OPENAI_API_KEY…`, exit 2 |

**Lo que la prueba encontró y se corrigió:**
- el ejemplo de stdin del README ("No puedo iniciar sesión") daba `other` con el mock, que es un clasificador por palabras clave; se cambió por un ejemplo que el mock clasifica bien;
- `adversarial.py --compare` mostraba dos columnas idénticas ("v4 · con guardrails") para las reglas v1 y v2; ahora muestra el hash de las reglas;
- correr la CLI modifica `data/metrics.jsonl`, que está versionado como evidencia (ADR-007). Es lo esperado en un log append-only; el README lo aclara para que no sorprenda en `git status`.

Al verificar el README contra el código aparecieron dos errores de documentación: el total de tests estaba mal sumado desde la Fase 9 (eran 146 y 155, no 151 y 160), y la tabla de decisiones del README citaba números de ADR equivocados. Ambos se corrigieron contando y contrastando con el apéndice, no de memoria.

## 3. Checklist de entrega de la consigna

| Ítem | Dónde | Estado |
|---|---|---|
| Claves por variable de entorno, nunca en el código | `src/providers/*`, `.env.example` | ✅ `git grep` sin secretos; `.env` ignorado; el historial completo no contiene ninguna clave |
| `src/main.py` incluido y versionado | `src/main.py` | ✅ |
| Al menos una ejecución de la CLI registrada, con JSON válido y línea de métricas | `data/metrics.jsonl` | ✅ 15 líneas reales (mock, OpenAI, Haiku 4.5, Haiku 5.5, caché) |
| Suite de evals corrida y reflejada en el README | `evals/results/`, README § Context engineering | ✅ |
| README y código consistentes; instalable sin preguntar | README | ✅ verificado en clon limpio |

## 4. Entregables

| Entregable | Archivo | Contenido mínimo pedido | Estado |
|---|---|---|---|
| CLI de triage | `src/main.py` | consulta por CLI, ≥ 2 proveedores, JSON validado, retry ante respuesta no parseable | ✅ OpenAI, Anthropic y mock; retry con el error de validación; fallback |
| Prompts versionados | `prompts/*.yaml` | ≥ 2 versiones, documentadas y comparadas contra el dataset | ✅ 4 versiones, 12 combinaciones comparadas |
| Dataset y suite de evals | `evals/dataset.jsonl`, `evals/runner.py` | ≥ 30 casos; runner por comando; score global y por categoría | ✅ 46 casos validados por una persona; métricas globales, por clase y por dificultad |
| Registro de métricas | `data/metrics.jsonl` | timestamp, tokens, latencia, costo | ✅ además: reintentos, guardrails, caché |
| Guardrails | `src/guardrails/` | ≥ 1 de entrada y ≥ 1 de salida | ✅ con efecto medido |
| README | `README.md` | setup, uso con ejemplos, técnica elegida y por qué, tabla de evals, decisiones | ✅ |
| Configuración | `.env.example`, `requirements.txt` | variables documentadas, dependencias declaradas | ✅ versiones fijadas |
| Seguridad adversarial (bonus) | `evals/adversarial.jsonl` + README | 10 ataques, mitigación y efecto medido | ✅ |
| Extra credit | README § Extras | al menos uno | ✅ caché MD5 y comparativa de modelos |

## 5. Rúbrica

| Categoría | Evidencia principal |
|---|---|
| Funcionalidad y contrato JSON | abstracción `LLMProvider` con 3 implementaciones; Pydantic estricto; reintento con feedback; fallback; casos borde en el dataset (Capítulos 2–4) |
| Suite de evals y dataset | 46 casos con guía de etiquetado y validación humana; runner con estimación de costo, umbrales y resultados trazables (Capítulos 6–7) |
| Context engineering y prompting | 4 prompts versionados; criterio declarado antes de medir y aplicado por script; holdout ampliado para confirmar v4 (Capítulos 5 y 8) |
| Seguridad y guardrails | 3 capas; 0 falsos positivos; suite adversarial congelada antes de probarla, con huecos encontrados y corregidos (Capítulos 9–10) |
| Observabilidad y métricas | JSONL append-only con tokens reales, costo auditable contra la tabla de precios versionada, latencia, guardrails y caché (Capítulos 3 y 11) |
| Repositorio, README y extras | módulos con una responsabilidad cada uno; 155 tests; README probado en un clon limpio; dos extras (Capítulos 11–12) |

## 6. Costo del desarrollo

| Fase | USD |
|---|---|
| 6 — primeras corridas reales (OpenAI, Haiku 4.5 y 5.5) | ≈ 0.15 |
| 7 — comparativa (dos rondas) | 1.61 |
| 8 — guardrails con el modelo elegido | 0.07 |
| 9 — suite adversarial | 0.12 |
| 10 — demostración de la caché | < 0.01 |
| **Total** | **≈ 1.95** |

Haiku 4.5 representó más de la mitad del total y se dejó de usar desde la ronda 2 de la Fase 7.

## 7. Lo que queda abierto

| Tema | Por qué quedó | Siguiente paso |
|---|---|---|
| `adv-08`: desvío de la clasificación con `gpt-4.1-mini` | no tiene palabras de ataque; la salida no reclasifica | una regla en un v5 del prompt, con nueva comparativa; o un clasificador semántico |
| Corridas asimétricas OpenAI ×1 vs. Anthropic ×3 | costo (≈ USD 0.20) | igualar a 3 corridas |
| Ataques nuevos, escritos sin conocer las reglas v2 | la medición posterior a la corrección es optimista | ampliar la suite, idealmente con otra persona |
| Acciones que el puntaje nunca reconoce (`bil-05`, `oth-03`) | revisar keywords cambia el dataset | revisión humana de las keywords |
| Tickets reales | no existen para este proyecto | un piloto con tráfico real, que también mediría la tasa de aciertos de la caché |
| FastAPI | la consigna pide una CLI | `POST /triage` sobre `TriagePipeline` |

## 8. Checklist de cierre

- [x] README final, con lo que pide la consigna y las limitaciones
- [x] clon limpio: instalación, 155 tests y comandos del README sin claves
- [x] sin secretos en el código ni en el historial
- [x] checklist de entrega y rúbrica revisados punto por punto
- [ ] merge de `desarrollo` a `master` y push (requiere confirmación)
- [ ] rotar la clave de OpenAI que se compartió durante el desarrollo

---

**Anterior:** [Capítulo 11 — Extras](11-fase-10-extras.md) · [Índice del manual](README.md)
