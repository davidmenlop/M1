# Capítulo 7 — Suite de evals (Fase 6)

> Un script, no un framework: corre los casos validados por el mismo pipeline que la CLI,
> calcula métricas que responden preguntas concretas y guarda un resultado que se puede
> auditar meses después.

---

## 1. Objetivo

- `python evals/runner.py --prompt vN --provider X` → métricas globales, por clase, de calibración, costo y latencia;
- resultados versionados en `evals/results/` (son la evidencia de la comparativa);
- `--compare` → tabla markdown para el README;
- corrida completa con mock y con un proveedor real.

## 2. Resultado

```
evals/
├── metrics.py     # funciones puras: compute(), aggregate(), check_thresholds()
├── runner.py      # CLI: corre, reporta, guarda y compara
└── results/
    ├── 20261104-175711_mock-default_v1_dev.json
    └── 20261104-175754_openai-default_v1_dev.json
tests/test_eval_metrics.py   # 14 tests, con valores calculados a mano
```

## 3. Qué pregunta responde cada métrica

| Métrica | Pregunta |
|---|---|
| `schema_valid_rate` | ¿el servicio cumple el contrato después de los reintentos? |
| `first_try_valid_rate`, `retry_rate` | ¿cuánto depende del reintento? (cada reintento es costo y latencia) |
| `accuracy` | ¿cuántos tickets van a la cola correcta? |
| `macro-F1` | ¿acierta en **todas** las categorías, no solo en la mayoritaria? Es la métrica principal (ADR-022) |
| `min_class_recall` | ¿hay alguna cola que se esté quedando sin sus tickets? |
| matriz de confusión | ¿**qué** se confunde con **qué**? |
| accuracy por dificultad | ¿falla en lo fácil (problema serio) o solo en lo difícil? |
| `action_score` | ¿sugiere lo que haría un buen agente? (intents con keywords, ADR-023) |
| `answer_keyword_coverage` | ¿la respuesta al cliente menciona el tema? |
| `brier`, confidence en aciertos vs. errores | ¿se puede confiar en `confidence` para decidir cuándo escalar? |
| costo medio y total, p50/p95 | ¿cuánto cuesta y cuánto tarda, incluidos los peores casos? |

Umbrales de aceptación (guía de desarrollo): `schema_valid_rate` = 100 %, `accuracy` ≥ 85 %, recall ≥ 75 % en cada clase y costo medio < USD 0.01. El runner los marca con ✓ / ✗.

## 4. Cómo funciona el runner

1. Valida el dataset (si tiene errores, no corre) y usa **solo los casos `validated`** del split pedido (`dev` por defecto).
2. Construye proveedor, modelo y prompt igual que la CLI, y corre cada caso por `TriagePipeline`: mismo reintento, mismo fallback, mismo costo.
3. **Estima el costo antes de correr** y pide `--yes` si supera USD 0.50.
4. Un error fatal (clave inválida, sin saldo) **aborta sin guardar**: un resultado parcial se confundiría con uno completo.
5. Calcula métricas por corrida y, con `--repeat N`, la media y el desvío (para Anthropic, que no acepta temperatura: ADR-016 y ADR-022).
6. Guarda `evals/results/<fecha>_<proveedor>-<modelo>_<prompt>_<split>.json` con:
   - `meta`: proveedor, modelo, temperatura, effort, versión y **sha256 del prompt**, **sha256 del dataset**, split, ids de los casos, reintentos, **commit y si el árbol estaba sucio**;
   - `summary`, `thresholds` y, por corrida, las métricas y cada caso (respuesta, acciones, confidence, intentos, costo, latencia).

Con los hashes, un resultado se puede invalidar en forma automática si el prompt o el dataset cambiaron después (ADR-026).

**No escribe en `data/metrics.jsonl`.** Ese archivo es observabilidad de producción: 32 líneas por corrida de eval lo contaminarían, y el JSON de resultados ya guarda lo mismo con más detalle (ADR-026).

## 5. Verificación

### 5.1 Tests

```bash
.venv/bin/python tests/test_eval_metrics.py   # 14/14
```

Las métricas se prueban contra un escenario de 6 casos **calculado a mano** (precision, recall y F1 por clase, macro-F1, Brier, percentiles), más la selección de casos y una corrida de punta a punta con mock. Suite completa: 105/105.

### 5.2 Corridas de referencia

Las dos corridas salen del commit `831835b` con el árbol limpio:

```bash
.venv/bin/python evals/runner.py --provider mock
.venv/bin/python evals/runner.py --provider openai --prompt v1
.venv/bin/python evals/runner.py --compare evals/results/*.json
```

| corrida | proveedor / modelo | prompt | split | casos | schema | retry | accuracy | macro-F1 | recall mín | action | Brier | USD/req | p95 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 20261104-175711 | mock / mock-1 | v1 | dev | 32×1 | 100% | 0% | 59% | 0.567 | 25% | 0.406 | 0.219 | 0.00000 | 0.000 |
| 20261104-175754 | openai / gpt-4.1-mini | v1 | dev | 32×1 | 100% | 0% | 91% | 0.908 | 78% | 0.859 | 0.089 | 0.00037 | 1.863 |

**El mock es la línea base:** un clasificador por palabras clave saca 59 %. Un modelo que no lo supere por mucho no justifica su costo.

OpenAI con v1, matriz de confusión:

```
               billing technical   account     other
  billing            7         0         0         0
  technical          0         8         0         0
  account            2         0         7         0
  other              1         0         0         7
```

Se corrió dos veces (antes y después de commitear el runner). La **clasificación fue idéntica** (accuracy 91 %, los mismos 3 errores), pero el texto de las acciones varió: el action score pasó de 0.875 a 0.859, y el Brier de 0.088 a 0.089. Conclusión: `temperature: 0.0` reduce la varianza pero **no garantiza determinismo**. Una diferencia de 0.016 en action score es ruido, y eso confirma el umbral de empate de 0.03 (ADR-022).

## 6. Lo que ya dicen los datos (antes de la Fase 7)

1. **Los 3 errores son los casos discutibles.** `bil-03` (baja de la suscripción) y `bil-08` (email de facturas) son los dos que la revisión humana pasó de billing a account. `oth-01` (descuento por pago anual) estaba marcado como ambiguo. El modelo coincide con el borrador del asistente, no con la decisión del negocio. Esa regla no se infiere: hay que escribirla en el prompt. Ojo: **v2 y v3 dicen explícitamente lo contrario** ("cancelación de la suscripción" en billing), así que van a fallar `bil-03` por diseño.
2. **La `confidence` no sirve para escalar.** Promedia 0.93 en errores y 0.93 en aciertos. El Brier bajo (0.088) viene de la accuracy alta, no de la calibración. Usar `confidence < X` para derivar a un humano, con v1, no filtraría los errores.
3. **v1 inventa políticas.** En `oth-01` responde *"Sí, ofrecemos descuentos por pago anual adelantado"*, algo que no figura en ningún lado. v2 y v3 tienen la regla "no inventes políticas"; el action score y las keywords no lo detectan. Queda como criterio cualitativo para la Fase 7 y como candidato a guardrail de salida (Fase 8).
4. **Costo:** USD 0.00037 por request y unos USD 0.012 por corrida de 32 casos. La comparativa completa de la Fase 7 (3 prompts × 3 modelos, con 3 repeticiones en Anthropic) cuesta menos de USD 1, y el grueso es Haiku 4.5 (unas 5 veces más caro por request que `gpt-4.1-mini`).

## 7. Decisiones y trade-offs

| Decisión | ADR | Trade-off |
|---|---|---|
| Resultados con hash de prompt y dataset, y commit | 026 | archivos más grandes vs. evidencia auditable |
| El runner no escribe en `metrics.jsonl` | 026 | dos lugares con datos de costo vs. observabilidad limpia |
| Abortar ante error fatal, sin guardar parciales | 026 | se pierde lo corrido vs. ningún resultado engañoso |
| Script, sin pytest ni framework | — | menos features vs. lo que pide la consigna |

## 8. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `el dataset tiene errores` | el validador falla | `python evals/validate_dataset.py` |
| `se excluyen N casos sin validar` | hay casos en draft o disputed | revisarlos con `review_labels.py` |
| `el costo estimado supera USD 0.50` | `--repeat` alto, o `--split all` con un modelo caro | confirmar con `--yes` |
| `la corrida se aborta sin guardar` | clave inválida o cuenta sin saldo | corregir la clave o el saldo y repetir |
| `"dirty": true` en `meta.git` | se corrió con cambios sin commitear | commitear y repetir antes de usarlo como evidencia |

## 9. Checklist de cierre

- [x] runner con métricas globales, por clase, por dificultad, de calibración, costo y latencia
- [x] umbrales de aceptación evaluados en cada corrida
- [x] resultados trazables (hash del prompt, hash del dataset, commit, árbol limpio)
- [x] `--compare` genera la tabla markdown
- [x] corrida completa con mock y con OpenAI, guardadas en `evals/results/`
- [x] métricas validadas contra valores calculados a mano; 105/105 tests
- [ ] corrida con Anthropic (pendiente de saldo)

---

**Anterior:** [Capítulo 6 — Dataset](06-fase-5-dataset.md) · **Siguiente:** Capítulo 8 — Iteración empírica (Fase 7, pendiente)
