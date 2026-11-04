# Capítulo 4 — Multi-proveedor (Fase 3)

> Dos proveedores reales detrás de la misma interfaz, con el mismo prompt, la misma
> validación y la misma política de reintentos. Cambiar de proveedor o de modelo es un
> flag, no un cambio de código.

---

## 1. Objetivo

Cumplir el requisito de **abstracción multi-proveedor real** de la rúbrica de Funcionalidad:

```
--provider openai|anthropic|mock  --model <clave>
        │
        ▼
 build_provider(name) ──► LLMProvider.complete(system, user, model, temperature, max_tokens, timeout_s, effort)
        │                         │
        ▼                         ├── OpenAIProvider    → chat.completions.create
 TriagePipeline (sin cambios)     ├── AnthropicProvider → messages.create
                                  └── MockProvider      → determinista, sin red
```

Al terminar la fase:

- OpenAI y Anthropic implementan `LLMProvider`; el pipeline no importa ningún SDK;
- los dos clasifican errores igual: reintentable, fatal o no disponible;
- `providers.yaml` admite **varios modelos por proveedor**, elegidos con `--model`;
- cada proveedor está verificado con una llamada real (ADR-017), o queda marcado como no verificado.

## 2. Resultado

```
src/providers/
├── base.py                 # LLMProvider: + effort opcional; temperature: float | None
├── factory.py              # registro PROVIDERS = {mock, openai, anthropic}
├── openai_provider.py      # NUEVO
├── anthropic_provider.py   # nunca envía muestreo; effort → output_config
└── mock_provider.py        # misma firma
src/config.py               # load_model_config(provider, model_key), available_models()
src/main.py                 # flag --model
config/providers.yaml       # anthropic.haiku-5-5
tests/test_openai_provider.py   # NUEVO, 13 tests con cliente falso
```

## 3. Conceptos

**Interfaz estrecha.** `LLMProvider.complete` recibe texto y parámetros, y devuelve `LLMResponse(text, prompt_tokens, completion_tokens, token_source)`. Todo lo específico de un SDK (nombres de parámetros, formato de mensajes, clases de error) queda dentro del proveedor.

**Parámetros opcionales = "no enviar".** `temperature` y `effort` aceptan `None`. `None` no significa "valor por defecto del proveedor" escrito por nosotros: significa *no mandar el campo*. Así el YAML dice exactamente qué viaja en la request.

**Tres clases de error** (ADR-015):

| Excepción | Cuándo | Qué hace el pipeline |
|---|---|---|
| `ProviderError` | 429, 5xx, timeout, conexión, 409 | reintenta |
| `ProviderFatalError` | 400, 401, 403, 404, 422, temperatura inválida | corta; la CLI sale con código 2 |
| `ProviderUnavailable` | proveedor desconocido o sin clave | se detecta antes de llamar |

## 4. Paso a paso

### 4.1 OpenAI

`src/providers/openai_provider.py` replica la estructura de Anthropic:

- `_client_from_env()` lee `OPENAI_API_KEY` y crea `openai.OpenAI(max_retries=0)`;
- el cliente es **inyectable** (`OpenAIProvider(client=...)`), para testear sin red;
- la request usa `chat.completions.create` con:

```python
params = {
    "model": model,
    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    "max_completion_tokens": max_tokens,
    "response_format": {"type": "json_object"},
    "timeout": timeout_s,
}
if temperature is not None:
    params["temperature"] = temperature
if effort is not None:
    params["reasoning_effort"] = effort
```

Por qué cada línea:

- `max_completion_tokens` reemplaza al antiguo `max_tokens` y funciona también con modelos de razonamiento.
- `response_format: json_object` (JSON mode) garantiza que la salida sea JSON parseable. No garantiza el schema: eso lo sigue haciendo Pydantic (ADR-018). JSON mode exige que el prompt mencione "JSON"; el `v1` ya lo hace.
- `choice.message.content or ""`: si el contenido viene vacío, el pipeline lo trata como JSON inválido y reintenta, en vez de romper con `None`.

### 4.2 Factory como registro

```python
PROVIDERS = {"mock": MockProvider, "openai": OpenAIProvider, "anthropic": AnthropicProvider}
```

Agregar un proveedor es una línea. El mensaje de error de un nombre desconocido lista las opciones a partir del mismo diccionario, así que nunca queda desactualizado.

### 4.3 Varios modelos por proveedor

```yaml
anthropic:
  models:
    default:
      id: claude-haiku-4-5
      temperature: null
      max_tokens: 700
      pricing: {input_per_1m_usd: 1.00, output_per_1m_usd: 5.00}
    haiku-5-5:
      id: claude-haiku-5-5
      temperature: null
      effort: low
      max_tokens: 2000
      pricing: {input_per_1m_usd: 0.10, output_per_1m_usd: 0.50}
```

```bash
python -m src.main --query "..." --provider anthropic --model haiku-5-5
```

`load_model_config` valida la clave y lista las opciones si no existe. `effort` es opcional y solo acepta `low | medium | high | xhigh | max`. Precios de Anthropic verificados contra la tabla oficial (2026-11-04); el de Haiku 5.5 aplica a prompts de hasta 100K tokens.

## 5. La corrección de la temperatura

En la Fase 2 se concluyó que *`claude-haiku-4-5` no acepta `temperature`*. Al revisar el SDK:

```bash
grep -n API_VERSION .venv/lib/python3.14/site-packages/anthropic/_constants.py
# 7:ANTHROPIC_API_VERSION = "2026-10-21"
```

Desde la versión `2026-10-21`, la API rechaza `temperature`, `top_p` y `top_k` en **todos** los modelos de Claude. El SDK ni siquiera los expone como parámetros; por eso en la Fase 2 se enviaban por `extra_body`.

Lo que cambió en el código:

```python
if temperature is not None:
    raise ProviderFatalError(
        "la API de Anthropic (versión 2026-10-21) rechaza 'temperature' en todos "
        "los modelos; poné 'temperature: null' en config/providers.yaml"
    )
```

Falla **antes** de llamar a la red: una configuración imposible no debe gastar una request para descubrirlo. La lección quedó en ADR-017: un error de la API se verifica contra la documentación, no solo contra el mensaje.

## 6. Verificación

### 6.1 Tests (sin red)

```bash
.venv/bin/python tests/test_schemas.py            # 10/10
.venv/bin/python tests/test_pipeline.py           # 15/15
.venv/bin/python tests/test_anthropic_provider.py # 15/15
.venv/bin/python tests/test_openai_provider.py    # 13/13
```

Tests nuevos destacados:

- `test_request_shape` (OpenAI): mensajes, `max_completion_tokens`, JSON mode, temperatura y timeout.
- `test_configured_temperature_fails_before_calling_api` (Anthropic): el cliente falso no registra ninguna llamada.
- `test_effort_sent_as_output_config` y `test_thinking_blocks_are_ignored_in_text` (Anthropic): soporte de Haiku 5.5.
- `test_pipeline_retries_on_invalid_json_then_succeeds` (OpenAI): JSON válido pero schema incompleto → reintento con feedback.

### 6.2 Llamadas reales

**OpenAI — verificado.**

```bash
.venv/bin/python -m src.main --query "Me cobraron dos veces la suscripción" --provider openai --pretty
```

```
INFO httpx2: HTTP Request: POST https://api.openai.com/v1/chat/completions "HTTP/1.1 200 OK"
INFO triage: request=594337a3... provider=openai attempts=1 success=True cost_usd=0.00032560 latency_s=2.6252
```

```json
{
  "answer": "Lamentamos el inconveniente. Revisaremos el cobro duplicado de su suscripción y gestionaremos el reintegro correspondiente lo antes posible.",
  "confidence": 0.95,
  "category": "billing",
  "actions": [
    "Verificar los movimientos de facturación del cliente",
    "Confirmar si hubo un cobro duplicado",
    "Procesar el reintegro o ajuste necesario"
  ]
}
```

**Anthropic — bloqueado por saldo.** Las dos llamadas (Haiku 4.5 y Haiku 5.5) devolvieron:

```
error: el proveedor 'anthropic' rechazó la solicitud: BadRequestError: Error code: 400 -
{'type': 'error', 'error': {'type': 'invalid_request_error',
 'message': 'Your credit balance is too low to access the Anthropic API. ...'}}
```

El manejo de errores se comportó como se diseñó: 400 fatal, sin reintentos, sin traceback y **sin escribir una línea de métricas**. Haiku 4.5 ya estaba verificado en la Fase 2 (Capítulo 3, §9.2), y el cambio de esta fase solo quita un campo que nunca se enviaba con `null`. **Haiku 5.5 queda sin verificar** hasta cargar crédito.

### 6.3 Primera comparación (una sola consulta, no es una eval)

| Proveedor | Modelo | Tokens in / out | Costo USD | Latencia |
|---|---|---|---|---|
| openai | gpt-4.1-mini | 510 / 76 | 0.00033 | 2.6 s |
| anthropic | claude-haiku-4-5 | 603 / 201 | 0.00161 | 2.5 s |
| anthropic | claude-haiku-5-5 | — | — | pendiente |

Con una consulta no se concluye nada sobre calidad. Sí muestra algo para la Fase 7: Haiku 4.5 escribe casi 3 veces más tokens de salida para la misma tarea, y en esta tarea el costo lo domina la salida.

## 7. Decisiones y trade-offs

| Decisión | ADR | Trade-off |
|---|---|---|
| JSON mode en OpenAI, no schema estricto | 018 | comparativa justa entre proveedores vs. menos reintentos en OpenAI |
| Anthropic nunca envía muestreo | 016 | sin temperatura 0; la varianza se mide |
| Varios modelos por proveedor, `--model` | 019 | un nivel más en el YAML vs. comparativas sin tocar código |
| `mock` sigue como default | 012 | hay que pasar `--provider` para usar uno real vs. clon limpio sin claves |

## 8. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `falta OPENAI_API_KEY` | no hay `.env` o la variable está vacía | copiar `.env.example` y completarla |
| `rechaza 'temperature' en todos los modelos` | `temperature` con número en un modelo de Anthropic | `temperature: null` |
| `'anthropic' no tiene el modelo 'x'` | clave de `--model` inexistente | usar una de las listadas en el mensaje |
| `credit balance is too low` | cuenta de Anthropic sin saldo | cargar crédito en la consola de Anthropic |
| `unrecognized arguments` al usar `$args` en zsh | zsh no divide variables en palabras | escribir los flags explícitos o usar un array |

## 9. Checklist de cierre

- [x] `OpenAIProvider` implementa `LLMProvider`, con cliente inyectable y `max_retries=0`
- [x] errores de OpenAI y Anthropic clasificados igual
- [x] factory como registro; mensaje de error con opciones
- [x] `--model` y varios modelos por proveedor en `providers.yaml`
- [x] Anthropic: muestreo nunca enviado; `effort` soportado
- [x] 53/53 tests sin red
- [x] OpenAI verificado con llamada real y línea en `metrics.jsonl`
- [ ] Haiku 5.5 verificado con llamada real (bloqueado: saldo de Anthropic)
- [ ] precio de `gpt-4.1-mini` confirmado en la página oficial de OpenAI

---

**Anterior:** [Capítulo 3 — CLI y mock](03-fase-2-cli-y-mock.md) · **Siguiente:** [Capítulo 5 — Prompts versionados](05-fase-4-prompts.md)
