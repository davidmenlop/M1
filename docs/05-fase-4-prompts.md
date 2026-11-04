# Capítulo 5 — Prompts versionados (Fase 4)

> Tres prompts en YAML, cada uno una hipótesis distinta sobre qué contexto necesita el
> modelo. Esta fase **no elige** ninguno: deja las tres versiones listas para medir y
> fija por escrito, antes de ver datos, cómo se va a elegir.

---

## 1. Objetivo

Cubrir la rúbrica de **context engineering**: al menos dos prompts versionados, comparados con datos y con un **criterio de selección declarado de antemano**.

Al terminar la fase:

- `prompts/` tiene `v1`, `v2` y `v3`, y los tres cargan, renderizan y pasan el pipeline;
- los ejemplos few-shot se validan contra el contrato al cargar;
- el razonamiento de `v3` viaja en un campo interno que nunca llega al cliente;
- el criterio de selección está escrito (§7) y registrado en ADR-022.

## 2. Resultado

```
prompts/
├── v1_zero_shot.yaml        # sin cambios: línea base
├── v2_few_shot.yaml         # NUEVO
└── v3_cot_security.yaml     # NUEVO
src/prompts.py               # examples, internal_fields, contract(), strip_internal(), list_versions()
src/pipeline.py              # render(query) y strip_internal antes de validar
tests/test_prompts.py        # NUEVO, 16 tests
```

## 3. Las tres hipótesis

| Versión | Técnica | Qué agrega | Hipótesis | Costo esperado |
|---|---|---|---|---|
| v1 | zero-shot | — | línea base | ~478 tokens de entrada |
| v2 | few-shot | taxonomía con inclusiones y exclusiones, 5 reglas de desambiguación, guía de calibración, 4 ejemplos (uno por categoría), límites a `answer` y `actions` | mejora los casos ambiguos y acorta las respuestas | ~1305 tokens de entrada (2.7×) |
| v3 | few-shot + CoT + seguridad | v2 + campo interno `reasoning` + reglas contra inyección y fuga del prompt + un 5.º ejemplo con una instrucción inyectada | razonar antes ayuda en los ambiguos; las reglas resisten la inyección | ~1883 de entrada (3.9×) + el razonamiento en la salida |

Los conteos son la estimación `caracteres / 4` del prompt renderizado. Los reales están en §6.2.

**Regla de inmutabilidad (ADR-020):** una versión evaluada no se edita. Cualquier cambio, aunque sea una coma, es una versión nueva. Si no, los resultados guardados en `evals/results/` dejan de corresponder al prompt que dicen.

**Prevención de leakage:** los 5 ejemplos de v2 y v3 se escribieron para **no** coincidir con los casos del dataset de la Fase 5. Un ejemplo idéntico a un caso de evaluación infla la accuracy sin que el prompt sea mejor. En la Fase 5 se agrega un chequeo automático de que ninguna consulta del dataset coincida con un ejemplo.

## 4. Código explicado

### 4.1 Nuevas claves del YAML

```yaml
examples:              # opcional; exige {examples} en el system
  - query: "..."
    output: {answer: ..., confidence: ..., category: ..., actions: [...]}
internal_fields:       # opcional; campos que el modelo devuelve además del contrato
  reasoning: "Análisis interno en 1 o 2 oraciones..."
```

`load_prompt` valida al cargar, y falla con un `PromptError` claro, si:

- un ejemplo no cumple `TriageResponse`: un ejemplo inválido le enseña al modelo a romper el contrato;
- hay `examples` sin `{examples}` en el system, o al revés;
- un campo interno redefine uno del contrato (`category`, etc.);
- a un ejemplo le falta un campo interno declarado.

### 4.2 El contrato se arma en el prompt

```python
def contract(self) -> str:
    schema = TriageResponse.model_json_schema()
    if self.internal_fields:
        internal = {name: {"type": "string", "description": text} for name, text in ...}
        schema["properties"] = {**internal, **schema["properties"]}
        schema["required"] = [*self.internal_fields, *schema["required"]]
    return json.dumps(schema, ensure_ascii=False)
```

Antes, el pipeline inyectaba `TriageResponse.json_contract()` directamente. Ahora cada prompt construye el schema que le corresponde. Para v1 el resultado es **idéntico** al anterior (`test_v1_render_is_unchanged`), así que las métricas de las fases 2 y 3 siguen siendo comparables.

`reasoning` va **primero** en `properties`: los modelos generan en orden, y para que el razonamiento influya en la clasificación tiene que escribirse antes que `category`.

### 4.3 El razonamiento nunca sale

```python
data = self._prompt.strip_internal(extract_json(response.text))
validated = TriageResponse.model_validate(data)
```

`strip_internal` quita los campos internos **antes** de validar. Como `TriageResponse` usa `extra="forbid"`, el contrato público queda intacto. Además:

- con v1 o v2, un `reasoning` no pedido **sí** rompe la validación y dispara un reintento (`test_v2_rejects_reasoning_as_extra_field`): solo el prompt que lo declara puede devolverlo;
- el razonamiento no se guarda en `metrics.jsonl`, porque puede citar datos del cliente (mismo criterio que ADR-013).

## 5. Seguridad en el prompt: una capa, no la defensa

v3 trata lo que está entre `<consulta>` y `</consulta>` como datos, nunca como instrucciones. Si hay un pedido legítimo con una instrucción inyectada, atiende el pedido y agrega la acción *"Revisar posible intento de manipulación en el ticket"*; si es solo un ataque, responde `other` con confidence ≤ 0.3.

Un prompt **no es un guardrail**: el modelo puede desobedecerlo. Los guardrails de entrada y salida, en código, llegan en la Fase 8, y su efecto se mide en la Fase 9. Queda pendiente para la Fase 8 un caso que el prompt no puede resolver: una consulta que contenga el texto `</consulta>` cierra el delimitador antes de tiempo. Neutralizarlo es tarea del guardrail de entrada.

## 6. Verificación

### 6.1 Tests (sin red)

```bash
.venv/bin/python tests/test_prompts.py   # 16/16
```

Suite completa: 69/69 (`schemas` 10, `pipeline` 15, `anthropic` 15, `openai` 13, `prompts` 16).

### 6.2 Llamadas reales

```bash
for v in v1 v2 v3; do
  .venv/bin/python -m src.main --query "Me cobraron dos veces la suscripción" --provider openai --prompt "$v" --pretty
done
```

| Versión | Intentos | Categoría | Confidence | Tokens in / out | Costo USD | Latencia |
|---|---|---|---|---|---|---|
| v1 | 1 | billing | 0.95 | 510 / 104 | 0.00037 | 2.2 s |
| v2 | 1 | billing | 0.95 | 1339 / 89 | 0.00068 | 1.9 s |
| v3 | 1 | billing | 0.95 | 1895 / 107 | 0.00093 | 2.6 s |

Modelo: `gpt-4.1-mini`, `temperature: 0.0`. En v3 la respuesta del modelo trajo `reasoning`, el pipeline lo descartó y el JSON impreso respeta el contrato.

Lo que **sí** muestra esta tabla: el costo por request crece 2.5× de v1 a v3, casi todo por entrada. v2 escribe menos que v1 (89 contra 104 tokens): los ejemplos acortan la respuesta, como predice la hipótesis. Lo que **no** muestra: nada sobre calidad. Es una sola consulta fácil, y las tres aciertan con la misma confidence. Para eso está la Fase 7.

## 7. Criterio de selección (declarado antes de tener datos)

Se aplica a cada combinación prompt × modelo, en este orden:

1. **Requisitos mínimos (eliminatorios).**
   - `schema_valid_rate` después de reintentos = 100 % en el split dev.
   - `retry_rate` ≤ 10 %.
2. **Métrica principal: macro-F1 de categoría** en el split dev. Se elige macro-F1 y no accuracy porque pondera igual las 4 clases: un prompt que acierta solo `billing` no gana.
3. **Empate:** si la diferencia de macro-F1 con el mejor es menor a **0.03** (con 32 casos de dev, un caso equivale a unos 3 puntos), se considera empate y decide el **action score** (recall contra `expected_actions_any`).
4. **Segundo empate** (action score a menos de 0.03): gana el **menor costo por request**, y después la menor **latencia p95**.
5. **Confirmación en holdout:** el ganador se corre una sola vez sobre los 8 casos de holdout. Si su macro-F1 cae más de 0.10 respecto de dev, se reporta como sobreajuste y la elección se documenta con esa salvedad. El holdout **no** se usa para elegir.
6. **Varianza:** los modelos de Anthropic no aceptan temperatura (ADR-016). Para ellos cada métrica es el **promedio de 3 corridas**, y se reporta el desvío.

La **resistencia a inyecciones no entra en este criterio**: la defensa principal son los guardrails (Fase 8) y se mide aparte (Fase 9). Si v3 empata en calidad y es más resistente, esa diferencia se reporta, pero no cambia el ganador de calidad.

## 8. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `el ejemplo N no cumple el contrato` | categoría en español, `confidence` fuera de 0–1, más de 3 acciones | corregir el ejemplo en el YAML |
| `hay 'examples' pero el system no contiene {examples}` | falta el slot | agregar `{examples}` al system |
| `se esperaba un único archivo v7_*.yaml` | versión inexistente | usar una de las listadas en el mensaje |
| v1 o v2 reintentan con `reasoning: Extra inputs are not permitted` | el modelo agregó un campo no pedido | esperado: el reintento lo corrige; si es frecuente, aparece en `retry_rate` |
| OpenAI: `'messages' must contain the word 'json'` | JSON mode sin la palabra JSON en el prompt | todo prompt nuevo debe mencionar JSON (lo verifica un test) |

## 9. Checklist de cierre

- [x] `v1`, `v2` y `v3` cargan, renderizan sin placeholders y pasan el pipeline con mock
- [x] ejemplos few-shot validados contra el contrato al cargar
- [x] un ejemplo por categoría en v2 y v3
- [x] `reasoning` de v3 descartado antes de validar; ausente de la salida y de las métricas
- [x] render de v1 idéntico al de las fases anteriores
- [x] criterio de selección declarado antes de tener datos (§7, ADR-022)
- [x] llamada real exitosa con las tres versiones (OpenAI)
- [ ] verificación con Anthropic (pendiente de saldo)
- [ ] chequeo de leakage entre ejemplos y dataset (Fase 5)

---

**Anterior:** [Capítulo 4 — Multi-proveedor](04-fase-3-multi-proveedor.md) · **Siguiente:** [Capítulo 6 — Dataset](06-fase-5-dataset.md)
