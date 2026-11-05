# Capítulo 8 — Iteración empírica (Fase 7)

> Cuatro prompts, tres modelos, un criterio fijado antes de medir y un script que lo aplica.
> El ganador sale de los datos; lo que los datos no pueden probar, se dice.

---

## 1. Objetivo

- correr los prompts v1–v4 con varios modelos sobre el split dev;
- elegir la combinación con el criterio de ADR-022, sin ajustarlo después de ver resultados;
- confirmar el ganador una sola vez en holdout;
- dejar el prompt elegido como predeterminado.

## 2. Resultado

```
prompts/v4_business_rules.yaml      # v3 + reglas de la guía de etiquetado (ADR-027)
evals/select.py                     # aplica ADR-022 a los resultados guardados
evals/dataset.jsonl                 # 46 casos: 32 dev / 14 holdout (6 nuevos, ADR-029)
evals/results/                      # ronda 1 (histórica) y ronda 2 (evidencia vigente)
tests/test_select.py                # 8 tests del criterio
src/config.py, .env.example         # DEFAULT_PROMPT_VERSION=v4 (ADR-028)
```

**Ganador: Haiku 5.5 con v4.** Macro-F1 1.000 en dev (3 corridas) y 1.000 en el holdout de 14 casos, incluidos los 6 que prueban sus reglas nuevas. USD 0.0005 por request.

La fase tuvo **dos rondas**:

| | Ronda 1 | Ronda 2 (vigente) |
|---|---|---|
| modelos | `gpt-4.1-mini`, Haiku 4.5, Haiku 5.5 | `gpt-4.1-mini`, Haiku 5.5 |
| dataset | 40 casos, holdout de 8 | 46 casos, holdout de 14; `oth-01` corregido |
| ganador | Haiku 5.5 + v4 | Haiku 5.5 + v4 |
| costo | USD 1.33 | USD 0.28 |

La ronda 1 dejó dos problemas: un caso del dataset contradecía al prompt y el holdout no tenía casos de las reglas nuevas. Corregirlos cambió el sha256 del dataset, y `select.py` descarta automáticamente toda corrida hecha con un dataset distinto del actual, así que la ronda 2 repite la comparativa entera. Haiku 4.5 no se repitió por costo (ADR-029).

## 3. El prompt v4

La revisión humana del dataset (Capítulo 6) decidió que la baja de la suscripción y el email de facturas son `account`. v2 y v3 dicen lo contrario, y en la Fase 6 los tres modelos fallaron `bil-03` con v1. Como los prompts son inmutables (ADR-020), la corrección es una versión nueva:

- **v4 = v3 + la taxonomía y las reglas de desempate de `evals/guia-de-etiquetado.md`**: baja del servicio y emails registrados → `account`; reportes con datos incorrectos → `technical`; precios y descuentos antes de contratar → `other`; nunca afirmar que existen descuentos o promociones.
- **Mismos ejemplos, mismo campo `reasoning` y misma sección de seguridad que v3.** `test_v4_only_changes_rules_over_v3` lo verifica, para que cualquier diferencia con v3 se atribuya solo a las reglas.
- **No agrega ejemplos parecidos a los casos que fallaban.** Sería entrenar con el examen; además, el chequeo de leakage lo detectaría.

**La salvedad (ADR-027):** v4 se escribió sabiendo qué casos fallaban. Las reglas vienen de la guía, no de los errores, pero el resultado de v4 en dev es **optimista** y solo cuenta si se sostiene en holdout (§5).

## 4. Cómo se elige

`evals/select.py` aplica el criterio sin intervención manual:

```bash
.venv/bin/python evals/select.py evals/results/*.json
```

1. **Qué cuenta como evidencia:** árbol limpio, mismo sha256 de dataset y de prompt que los actuales, split dev y, en Anthropic, al menos 3 corridas. Si una combinación tiene varias corridas, se usa la más reciente. El mock es la línea base: no compite.
2. **Requisitos mínimos:** schema 100 % y retry ≤ 10 %.
3. **Macro-F1:** las que quedan a 0.03 o más del mejor salen.
4. **Action score:** entre las empatadas, las que quedan a 0.03 o más del mejor salen.
5. **Costo por request**, y después latencia p95.

Las diferencias se redondean antes de compararlas con 0.03: sin eso, `0.96 - 0.93` da `0.0299…` y contaría como empate. Lo detectó un test.

## 5. Ronda 2: la evidencia vigente

### 5.1 Selección en dev

| # | combinación | corridas | macro-F1 | action | USD/req | p95 s | resultado |
|---|---|---|---|---|---|---|---|
| 1 | anthropic / claude-haiku-5-5 · v4 | 3 | 1.000 | 0.953 | 0.00050 | 2.59 | GANADOR |
| 2 | openai / gpt-4.1-mini · v4 | 1 | 1.000 | 0.953 | 0.00105 | 1.81 | empate en F1 y action; más caro (2.1×) |
| 3 | openai / gpt-4.1-mini · v2 | 1 | 0.938 | 1.000 | 0.00069 | 1.89 | macro-F1 a 0.062 del mejor |
| 4 | anthropic / claude-haiku-5-5 · v3 | 3 | 0.938 | 0.958 | 0.00046 | 2.55 | macro-F1 a 0.062 del mejor |
| 5 | openai / gpt-4.1-mini · v3 | 1 | 0.938 | 0.953 | 0.00096 | 1.71 | macro-F1 a 0.062 del mejor |
| 6 | anthropic / claude-haiku-5-5 · v2 | 3 | 0.938 | 0.938 | 0.00033 | 2.45 | macro-F1 a 0.062 del mejor |
| 7 | openai / gpt-4.1-mini · v1 | 1 | 0.908 | 0.891 | 0.00037 | 1.82 | macro-F1 a 0.092 del mejor |
| 8 | anthropic / claude-haiku-5-5 · v1 | 3 | 0.908 | 0.911 | 0.00022 | 3.61 | macro-F1 a 0.092 del mejor |

Haiku 5.5 y `gpt-4.1-mini` con v4 empatan en macro-F1 y en action score; decide el costo. Con v2 y v3, los dos modelos fallan los mismos casos (`bil-03`, `bil-08`); con v1, además `oth-01` (OpenAI) o `tec-06` (Haiku 5.5).

### 5.2 Confirmación en holdout

```bash
.venv/bin/python evals/runner.py --provider anthropic --model haiku-5-5 --prompt v4 --split holdout --repeat 3
```

**14 de 14 en las tres corridas:** macro-F1 1.000, sin caída respecto de dev. Action score 0.929, Brier 0.014, USD 0.0005 por request.

El holdout tiene 6 casos nuevos (ADR-029) escritos **después** de crear v4 pero **sin correrlos** antes de que una persona validara sus etiquetas. Prueban las reglas de v4 e incluyen contrastes, para que no alcance con "menciona baja → account":

| caso | consulta (resumen) | etiqueta | v3 (3 corridas) | v4 (3 corridas) |
|---|---|---|---|---|
| `acc-09` | cancelar el plan para que no se renueve | account | billing ✗ | account ✓ |
| `acc-10` | borrar la cuenta y todos los datos | account | account ✓ | account ✓ |
| `bil-09` | di de baja y me debitaron igual; quiero la plata | billing | billing ✓ | billing ✓ |
| `acc-11` | las facturas tienen que llegarle a la contadora | account | billing ✗ | account ✓ |
| `tec-09` | el email está bien, pero no llegan las facturas | technical | billing ✗ | technical ✓ |
| `bil-10` | la factura del mail tiene mal el CUIT | billing | billing ✓ | billing ✓ |

**Diagnóstico con v3 (no se usó para elegir):** se corrió v3 sobre el mismo holdout para saber si los casos nuevos realmente exigen las reglas. v3 falla 3 de los 6 (accuracy 79 %, macro-F1 0.819); v4 acierta los 6, incluidos los contrastes `bil-09` y `bil-10`, donde la regla nueva podría haber sobrecorregido. Es la evidencia de que **las reglas generalizan a casos que no se usaron para escribirlas**, y no solo que v4 no rompió nada.

Sigue siendo un holdout chico: 14 casos, solo 2 de `other`. Según la clase, un error movería el macro-F1 entre 0.04 y 0.11.

## 6. Lo que muestran los datos

1. **El salto lo explican las reglas, no el modelo.** Con v2 y v3, todos los modelos fallan `bil-03` y `bil-08`: el prompt les dice "cancelación → billing". Con v4, todos llegan a 1.000. Un modelo no puede adivinar una regla de negocio que contradice su prompt.
2. **Sin v4, el resultado habría sido otro.** En la ronda 1, aplicando el criterio solo a v1–v3, ganaba Haiku 4.5 con v2, a USD 0.0024 por request: casi 5 veces el ganador actual.
3. **Los ejemplos mejoran las acciones.** El action score pasa de 0.89–0.91 con v1 a 0.94–1.00 con v2–v4. Los ejemplos few-shot enseñan acciones concretas y verificables.
4. **El razonamiento (v3) no mejoró la clasificación.** v3 empata con v2 en macro-F1 en todos los modelos y cuesta alrededor de un 40 % más. Se mantiene en v4 por la seguridad (Fase 9), no por calidad.
5. **Varianza de Anthropic: baja.** En la ronda 2, el desvío de macro-F1 entre 3 corridas es 0.000 en las 4 combinaciones de Haiku 5.5. Que la ronda 1 y la 2 den el mismo orden confirma que el umbral de empate de 0.03 está bien elegido.
6. **Inventar políticas depende del prompt.** En `oth-01` (descuento por pago anual), v1 y v2 con OpenAI afirman que existen descuentos; con v4, todos los modelos derivan a una persona sin prometer nada.
7. **La confidence sigue sin servir para escalar.** Con v4 no hay errores, así que no se puede medir. Con v3 en holdout, la confidence media fue 0.84 en los errores y 0.89 en los aciertos: los errores vienen con confianza alta, y un umbral de escalado no los filtraría.

### 6.1 Acciones que el puntaje no reconoce

ADR-023 pide revisar los fallos de acciones del ganador:

- **`oth-01`**: el dataset esperaba "Informar planes o descuentos", y v4 prohíbe afirmar que existen. Por decisión humana, el caso ahora espera solo "Derivar al equipo comercial" (ADR-029). En la ronda 2 no falla.
- **`bil-05` → "Informar el motivo o ajustar el cargo"** (3/3 en dev) y **`oth-03` → "Enviar información de funcionalidades"** (3/3 en holdout): fallan en todas las corridas, así que no es varianza. Puede ser un sinónimo que no está en las keywords o una acción que el modelo no propone. Revisarlos cambia el dataset, así que queda para una próxima revisión humana.
- El resto (`bil-06`, `edge-08`, `tec-03`, `edge-06`, `tec-09`) falla en 1 o 2 de 3 corridas: varianza.

## 7. Ronda 1 (histórica)

Se hizo con el dataset de 40 casos e incluyó Haiku 4.5. Sus corridas siguen en `evals/results/`, pero `select.py` ya no las cuenta (el dataset cambió).

| combinación | macro-F1 | action | USD/req |
|---|---|---|---|
| Haiku 5.5 · v4 | 1.000 | 0.969 | 0.00050 |
| `gpt-4.1-mini` · v4 | 1.000 | 0.969 | 0.00105 |
| Haiku 4.5 · v4 | 1.000 | 0.917 | 0.00372 |
| Haiku 4.5 · v1 | 0.969 | 0.885 | 0.00170 |
| Haiku 4.5 · v2 | 0.948 | 0.964 | 0.00243 |
| resto (v1–v3 de Haiku 5.5 y OpenAI, v3 de Haiku 4.5) | 0.908–0.938 | — | — |

El ganador fue el mismo, Haiku 5.5 con v4, confirmado en el holdout de 8 casos. Haiku 4.5 se llevó el 81 % del costo de la ronda (USD 1.08 de 1.33) y no ganó, así que se excluyó de la ronda 2.

## 8. Costo

| | USD |
|---|---|
| Ronda 1: OpenAI v2–v4, Haiku 5.5 y Haiku 4.5 v1–v4 ×3, holdout | 1.33 |
| Ronda 2: OpenAI v1–v4, Haiku 5.5 v1–v4 ×3 | 0.24 |
| Ronda 2: holdout del ganador y diagnóstico con v3 | 0.04 |
| **Total de la Fase 7** | **1.61** |

## 9. Decisiones y trade-offs

| Decisión | ADR | Trade-off |
|---|---|---|
| Crear v4 después de ver dev, con confirmación en holdout | 027 | resultado en dev optimista vs. medir al modelo contra reglas que nadie le dio |
| Aplicar el criterio con un script | 022 | menos flexibilidad vs. una elección reproducible y sin sesgo |
| v4 como prompt predeterminado; el proveedor sigue siendo `mock` | 028, 012 | hay que pedir `--provider anthropic --model haiku-5-5` explícitamente vs. no gastar sin querer |
| Holdout ampliado con casos de las reglas; ronda 2 sin Haiku 4.5 | 029 | repetir la comparativa (USD 0.28) vs. una confirmación que no probaba nada |

## 10. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `select.py` excluye una corrida "dataset distinto del actual" | el dataset cambió después de correr | es lo esperado: repetir la comparativa |
| `select.py` excluye una corrida "prompt distinto del actual" | el YAML cambió después de correr | los prompts no se editan; crear una versión nueva |
| una corrida de Anthropic queda afuera por "1 corrida" | se corrió sin `--repeat 3` | repetirla con `--repeat 3` |
| `--provider anthropic` corre Haiku 4.5 | la clave `default` de Anthropic es Haiku 4.5 | usar siempre `--model haiku-5-5` |

## 11. Checklist de cierre

- [x] 4 prompts × 2 modelos en dev (ronda 2), Anthropic con 3 corridas
- [x] criterio aplicado por script, con tests
- [x] ganador confirmado en un holdout que incluye casos de sus reglas nuevas, validados por una persona
- [x] diagnóstico: los casos nuevos distinguen v3 de v4
- [x] prompt predeterminado actualizado
- [x] `oth-01` corregido por decisión humana

---

**Anterior:** [Capítulo 7 — Suite de evals](07-fase-6-evals.md) · **Siguiente:** Capítulo 9 — Guardrails (Fase 8, pendiente)
