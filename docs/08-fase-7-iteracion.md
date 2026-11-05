# Capítulo 8 — Iteración empírica (Fase 7)

> Doce combinaciones de prompt y modelo, un criterio fijado antes de medir y un script que
> lo aplica. El ganador sale de los datos; lo que los datos no pueden probar, se dice.

---

## 1. Objetivo

- correr los prompts v1–v4 con los tres modelos sobre el split dev;
- elegir la combinación con el criterio de ADR-022, sin ajustarlo después de ver resultados;
- confirmar el ganador una sola vez en holdout;
- dejar el prompt elegido como predeterminado.

## 2. Resultado

```
prompts/v4_business_rules.yaml      # v3 + reglas de la guía de etiquetado (ADR-027)
evals/select.py                     # aplica ADR-022 a los resultados guardados
evals/results/                      # 12 corridas dev (Anthropic ×3) + 1 holdout
tests/test_select.py                # 8 tests del criterio
src/config.py, .env.example         # DEFAULT_PROMPT_VERSION=v4 (ADR-028)
```

**Ganador: Haiku 5.5 con v4.** Macro-F1 1.000 en dev (3 corridas) y 1.000 en holdout, USD 0.0005 por request.

## 3. El prompt v4

La revisión humana del dataset (Capítulo 6) decidió que la baja de la suscripción y el email de facturas son `account`. v2 y v3 dicen lo contrario, y en la Fase 6 los tres modelos fallaron `bil-03` con v1. Como los prompts son inmutables (ADR-020), la corrección es una versión nueva:

- **v4 = v3 + la taxonomía y las reglas de desempate de `evals/guia-de-etiquetado.md`**: baja del servicio y emails registrados → `account`; reportes con datos incorrectos → `technical`; precios y descuentos antes de contratar → `other`; nunca afirmar que existen descuentos o promociones.
- **Mismos ejemplos, mismo campo `reasoning` y misma sección de seguridad que v3.** `test_v4_only_changes_rules_over_v3` lo verifica, para que cualquier diferencia con v3 se atribuya solo a las reglas.
- **No agrega ejemplos parecidos a los casos que fallaban.** Sería entrenar con el examen; además, el chequeo de leakage lo detectaría.

**La salvedad (ADR-027):** v4 se escribió sabiendo qué casos fallaban. Las reglas vienen de la guía, no de los errores, pero el resultado de v4 en dev es **optimista** y solo cuenta si se sostiene en holdout.

## 4. Cómo se eligió

`evals/select.py` aplica el criterio sin intervención manual:

```bash
.venv/bin/python evals/select.py evals/results/*.json
```

1. **Qué cuenta como evidencia:** árbol limpio, mismo sha256 de dataset y de prompt que los actuales, split dev y, en Anthropic, al menos 3 corridas. Si una combinación tiene varias corridas, se usa la más reciente. El mock es la línea base: no compite. Las corridas de Anthropic de una sola repetición de la Fase 6 quedan afuera.
2. **Requisitos mínimos:** schema 100 % y retry ≤ 10 %. Las doce combinaciones los cumplen.
3. **Macro-F1:** las que quedan a 0.03 o más del mejor salen.
4. **Action score:** entre las empatadas, las que quedan a 0.03 o más del mejor salen.
5. **Costo por request**, y después latencia p95.

Las diferencias se redondean antes de compararlas con 0.03: sin eso, `0.96 - 0.93` da `0.0299…` y contaría como empate. Lo detectó un test.

### 4.1 Resultado

| # | combinación | corridas | macro-F1 | action | USD/req | p95 s | resultado |
|---|---|---|---|---|---|---|---|
| 1 | anthropic / claude-haiku-5-5 · v4 | 3 | 1.000 | 0.969 | 0.00050 | 2.79 | GANADOR |
| 2 | openai / gpt-4.1-mini · v4 | 1 | 1.000 | 0.969 | 0.00105 | 1.75 | empate en F1 y action; más caro (2.1×) |
| 3 | anthropic / claude-haiku-4-5 · v4 | 3 | 1.000 | 0.917 | 0.00372 | 3.23 | empate en F1; action a 0.052 del mejor |
| 4 | anthropic / claude-haiku-4-5 · v1 | 3 | 0.969 | 0.885 | 0.00170 | 3.19 | macro-F1 a 0.031 del mejor |
| 5 | anthropic / claude-haiku-4-5 · v2 | 3 | 0.948 | 0.964 | 0.00243 | 2.46 | macro-F1 a 0.052 del mejor |
| 6 | openai / gpt-4.1-mini · v2 | 1 | 0.938 | 0.984 | 0.00069 | 1.80 | macro-F1 a 0.062 del mejor |
| 7 | anthropic / claude-haiku-5-5 · v2 | 3 | 0.938 | 0.969 | 0.00032 | 2.20 | macro-F1 a 0.062 del mejor |
| 8 | openai / gpt-4.1-mini · v3 | 1 | 0.938 | 0.969 | 0.00096 | 1.82 | macro-F1 a 0.062 del mejor |
| 9 | anthropic / claude-haiku-5-5 · v3 | 3 | 0.938 | 0.943 | 0.00046 | 2.70 | macro-F1 a 0.062 del mejor |
| 10 | anthropic / claude-haiku-4-5 · v3 | 3 | 0.938 | 0.938 | 0.00343 | 3.14 | macro-F1 a 0.062 del mejor |
| 11 | anthropic / claude-haiku-5-5 · v1 | 3 | 0.918 | 0.943 | 0.00022 | 2.89 | macro-F1 a 0.082 del mejor |
| 12 | openai / gpt-4.1-mini · v1 | 1 | 0.908 | 0.859 | 0.00037 | 1.86 | macro-F1 a 0.092 del mejor |

Haiku 5.5 y `gpt-4.1-mini` con v4 empatan en macro-F1 y en action score; decide el costo. El detalle completo (accuracy, recall, Brier, desvíos) está en la tabla del README, generada con `runner.py --compare`.

### 4.2 Confirmación en holdout

```bash
.venv/bin/python evals/runner.py --provider anthropic --model haiku-5-5 --prompt v4 --split holdout --repeat 3
```

8 de 8 en las tres corridas: macro-F1 1.000, sin caída respecto de dev. Action score 0.896, Brier 0.012, USD 0.0005 por request.

**Por qué es una confirmación débil:**
- son 8 casos, 2 por clase; un error movería el macro-F1 más de 0.1;
- **ningún caso del holdout prueba las reglas nuevas de v4**: no hay bajas de suscripción ni emails de facturas. `acc-03` (email de inicio de sesión) ya era `account` en v3.

El holdout confirma que v4 **no rompió** nada fuera de dev, pero no prueba que la regla nueva generalice. Para eso hacen falta casos nuevos de baja y de email de facturas, escritos sin mirar los resultados. Queda como trabajo pendiente: agregarlos ahora, después de ver los resultados, repetiría el problema.

## 5. Lo que muestran los datos

1. **El salto lo explican las reglas, no el modelo.** Con v2 y v3, los tres modelos fallan `bil-03` y `bil-08`: el prompt les dice "cancelación → billing". Con v4, los tres llegan a 1.000. Un modelo no puede adivinar una regla de negocio que contradice su prompt.
2. **Sin v4, el resultado habría sido otro.** Aplicando el mismo criterio solo a v1–v3, gana Haiku 4.5 con v2 (empata en F1 con Haiku 4.5 v1, 0.948 vs 0.969, y lo supera en action score, 0.964 vs 0.885), a USD 0.0024 por request: casi 5 veces el ganador actual.
3. **Pocos ejemplos o reglas mejoran las acciones.** El action score pasa de 0.86–0.94 con v1 a 0.92–0.98 con v2–v4 en los tres modelos. Los ejemplos few-shot enseñan acciones concretas y verificables.
4. **El razonamiento (v3) no mejoró la clasificación.** v3 empata con v2 en macro-F1 en los tres modelos y cuesta alrededor de un 40 % más. Se mantiene en v4 por la seguridad (Fase 9), no por calidad.
5. **Varianza de Anthropic: baja.** El desvío de macro-F1 entre 3 corridas es 0.000 en 6 de 8 combinaciones, y 0.017–0.018 en las otras dos (un caso que va y viene). Confirma que el umbral de empate de 0.03 está bien elegido.
6. **Inventar políticas depende del prompt.** En `oth-01` (descuento por pago anual), v1 y v2 con OpenAI afirman que existen descuentos; con v4, los tres modelos derivan a una persona sin prometer nada.
7. **La confidence sigue sin servir para escalar.** Con v4 no hay errores en dev, así que no se puede medir. En la Fase 6, los modelos estaban tan seguros en sus errores como en sus aciertos.

### 5.1 Acciones que el puntaje no reconoce

ADR-023 pide revisar los fallos de acciones del ganador. En las 3 corridas de Haiku 5.5 + v4 hubo 5 fallos, cada uno en una sola corrida. Dos son de interés:

- **`oth-01` → "Informar planes o descuentos".** El dataset espera que se informe el descuento; v4 prohíbe afirmar que existe. **El dataset y el prompt se contradicen**: con la regla de no inventar políticas, la acción correcta es derivar a comercial. Se resuelve cambiando el intent esperado en el dataset (ADR-023 lo permite), pero eso cambia el sha256 y obliga a repetir la comparativa. Queda pendiente de una decisión humana, como el resto de las etiquetas.
- **`tec-03` → "Escalar a ingeniería o infraestructura".** Falla 3/3 en Haiku 4.5 y 1/3 en Haiku 5.5. Es un sinónimo que no está en las keywords o una acción que el modelo no propone; hay que mirarlo caso por caso.

## 6. Costo

| | USD |
|---|---|
| OpenAI v2–v4 (3 corridas) | 0.09 |
| Haiku 5.5 v1–v4 (12 corridas) | 0.14 |
| Haiku 4.5 v1–v4 (12 corridas) | 1.08 |
| Holdout (3 corridas) | 0.01 |
| **Total de la Fase 7** | **1.33** |

La estimación inicial era "menos de USD 1", corregida a "alrededor de USD 1"; v4 agregó una columna más. Haiku 4.5 es el 81 % del costo y no ganó.

## 7. Decisiones y trade-offs

| Decisión | ADR | Trade-off |
|---|---|---|
| Crear v4 después de ver dev, con confirmación en holdout | 027 | resultado en dev optimista vs. medir al modelo contra reglas que nadie le dio |
| Aplicar el criterio con un script | 022 | menos flexibilidad vs. una elección reproducible y sin sesgo |
| v4 como prompt predeterminado; el proveedor sigue siendo `mock` | 028, 012 | hay que pedir `--provider anthropic --model haiku-5-5` explícitamente vs. no gastar sin querer |

## 8. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `select.py` excluye una corrida "prompt distinto del actual" | el YAML cambió después de correr | es lo esperado: los prompts no se editan; crear una versión nueva |
| una corrida de Anthropic queda afuera por "1 corrida" | se corrió sin `--repeat 3` | repetirla con `--repeat 3` |
| `--model default` no es Haiku 5.5 | `default` en Anthropic es Haiku 4.5 | usar `--model haiku-5-5` |

## 9. Checklist de cierre

- [x] 4 prompts × 3 modelos en dev, Anthropic con 3 corridas
- [x] criterio aplicado por script, con tests
- [x] ganador confirmado en holdout, con sus limitaciones documentadas
- [x] prompt predeterminado actualizado
- [ ] casos nuevos que prueben las reglas de v4 (baja, email de facturas), escritos sin mirar resultados
- [ ] decisión humana sobre el intent esperado de `oth-01`

---

**Anterior:** [Capítulo 7 — Suite de evals](07-fase-6-evals.md) · **Siguiente:** Capítulo 9 — Guardrails (Fase 8, pendiente)
