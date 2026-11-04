# Capítulo 3 — CLI, mock y métricas (Fase 2)

> Primer flujo completo de punta a punta: una consulta entra por la CLI, pasa por un
> pipeline con reintento y fallback, sale como JSON validado y deja una línea de métricas.
> Todo sin API keys.

---

## 1. Objetivo

Cerrar el ciclo mínimo del servicio:

```
--query  →  prompt v1  →  MockProvider  →  parseo  →  Pydantic  →  (retry)  →  JSON  +  metrics.jsonl
```

Al terminar la fase:

- la CLI devuelve JSON válido con el contrato del Capítulo 2;
- cada request deja **una línea** en `data/metrics.jsonl` con tokens, latencia, costo e intentos;
- un output inválido del proveedor dispara **reintento con feedback**;
- si todos los intentos fallan, la CLI **no se cae**: devuelve una respuesta de fallback válida;
- el proveedor `mock` permite correr todo sin credenciales.

## 2. Resultado

```
src/
├── main.py                       # CLI (argparse)
├── config.py                     # .env + config/providers.yaml -> Settings / ModelConfig
├── prompts.py                    # carga y render de prompts/*.yaml
├── pipeline.py                   # extract_json, reintento, fallback, TriageResult
├── providers/
│   ├── base.py                   # LLMProvider (ABC), LLMResponse, errores
│   ├── mock_provider.py          # clasificador determinista por palabras clave
│   └── factory.py                # build_provider(nombre)
└── observability/
    ├── pricing.py                # compute_cost()
    └── metrics.py                # build_record() + append_metric() (JSONL)
prompts/
└── v1_zero_shot.yaml             # primer prompt versionado
tests/
└── test_pipeline.py              # 12 tests
data/
└── metrics.jsonl                 # versionado: evidencia de ejecución
```

## 3. Conceptos

### 3.1 Un pipeline, no un llamado

Llamar al modelo y devolver su texto es una línea. Un servicio es otra cosa: hay que decidir qué pasa cuando el modelo responde mal, cuando la red falla, cuando el JSON viene envuelto en prosa. El **pipeline** es el lugar donde viven esas decisiones, separado del proveedor y de la CLI.

```
TriagePipeline.run(query)
   ├── render(prompt)                       # system + user
   ├── for intento en 0..MAX_RETRIES:
   │     ├── provider.complete(...)         # ProviderError -> reintenta
   │     ├── extract_json(texto)            # ParseError   -> reintenta con feedback
   │     └── TriageResponse.model_validate  # ValidationError -> reintenta con feedback
   │     éxito -> return TriageResult(success=True)
   └── fallback                             # success=False, category=other, confidence=0
```

### 3.2 Abstracción de proveedor

`LLMProvider` define **una** operación: `complete(system, user, ...) -> LLMResponse`. El pipeline no sabe si hay un SDK de OpenAI, un HTTP directo o un diccionario de Python. Eso permite agregar Anthropic en la Fase 3 sin tocar `pipeline.py`.

Los errores también tienen contrato:

| Excepción | Significado | Tratamiento |
|---|---|---|
| `ProviderError` | fallo transitorio o del proveedor (red, 429, 5xx) | reintentable |
| `ProviderUnavailable` | proveedor desconocido o no implementado | no reintenta; error de configuración |

### 3.3 El mock no es un LLM

`MockProvider` clasifica por palabras clave normalizadas (sin tildes) y devuelve un JSON que cumple el contrato. Sirve para:

- validar el pipeline, el parseo, el reintento y las métricas **sin gastar** y **sin red**;
- que el corrector pueda correr el proyecto sin keys;
- simular fallas con `malformed_attempts=N` (las usan los tests).

**No sirve para medir calidad.** Su accuracy sobre los 8 ejemplos de la consigna es 100% porque las palabras clave se eligieron mirando esos ejemplos: es sobreajuste deliberado para el E2E. La medición real se hace en la Fase 7 con un dataset de 40 casos y un proveedor real.

### 3.4 Métricas: qué se registra y por qué

Una línea por **request** (no por intento), append-only, UTF-8, LF.

| Campo | Para qué sirve |
|---|---|
| `request_id` | correlacionar con logs |
| `query_sha256` + `query_chars` | auditar sin guardar el texto del cliente (privacidad) |
| `attempts`, `retries` | medir fragilidad del formato del modelo |
| `prompt_tokens`, `completion_tokens`, `total_tokens` | base del costo |
| `token_source` | `api` (lo informó el proveedor) o `estimated` (aproximado) |
| `latency_s` | latencia total del pipeline, incluidos reintentos |
| `cost_usd` | costo calculado con la tabla de `providers.yaml` |
| `success`, `error` | si hubo respuesta válida y por qué falló si no |

`token_source` es importante: el mock reporta tokens **estimados** (`caracteres / 4`). Si el costo se mezclara con tokens reales sin marcarlo, los números no serían auditables.

## 4. Paso a paso

### 4.1 Configuración: `config.py`

`load_settings()` lee `.env` (sin sobrescribir variables de entorno reales) y valida:

- `MAX_RETRIES >= 0` y `REQUEST_TIMEOUT_S > 0`;
- `LOG_LEVEL` válido;
- `METRICS_PATH` relativo se resuelve contra la **raíz del repo**, no contra el directorio desde donde se corre la CLI.

Esto último evita un bug típico: que el log quede en un lugar distinto según desde dónde se ejecute.

`load_model_config(provider)` lee el bloque `models.default` de `providers.yaml` y devuelve un `ModelConfig` inmutable. Si falta el bloque o el precio, falla con un mensaje que nombra el proveedor.

### 4.2 Prompt versionado: `prompts/v1_zero_shot.yaml`

El prompt vive en YAML, no en el código. El loader exige:

- exactamente un archivo `v1_*.yaml` (evita ambigüedades);
- las claves `version`, `technique`, `system`, `user_template`;
- que `version` coincida con el nombre del archivo;
- que existan los placeholders `{contract}` (en `system`) y `{query}` (en `user_template`).

El render usa `str.replace`, no `str.format`. Motivo: una consulta que contenga llaves (`{}`) rompería `format`. Con `replace` el texto del cliente se inserta tal cual.

```python
system = self.system.replace("{contract}", contract)
user = self.user_template.replace("{query}", query)
```

`{contract}` se reemplaza por el JSON Schema de `TriageResponse` (Capítulo 2, §6). Así el contrato vive en **un solo lugar**: si cambia el modelo Pydantic, cambia el prompt automáticamente.

**Decisión de diseño de v1:** es una línea base **sin** reglas de seguridad ni ejemplos. Si le agregáramos la defensa contra injection ahora, la comparación de la Fase 7 no sería limpia: estaríamos mezclando dos variables. Las defensas van en v3.

### 4.3 Proveedor: `providers/`

`base.py` define `LLMResponse` como dataclass inmutable con el texto, los tokens y su origen (`token_source`). Es el único tipo que cruza la frontera entre proveedor y pipeline.

`factory.py` mapea nombres a instancias. Hoy solo `mock`; `openai` y `anthropic` devuelven un error explícito que indica en qué fase llegan:

```
error: el proveedor 'openai' se implementa en la Fase 3; usá --provider mock por ahora
```

### 4.4 Pipeline: `pipeline.py`

**Extracción del JSON.** Los modelos no siempre devuelven JSON puro. `extract_json` tolera tres formas:

1. JSON puro;
2. JSON dentro de un bloque ` ```json ... ``` `;
3. JSON precedido o seguido de prosa (toma desde la primera `{` hasta la última `}`).

Si ninguna funciona, lanza `ParseError`. No intenta "arreglar" el JSON (no agrega comas ni cierra llaves): arreglar sintaxis silenciosamente oculta el problema real del modelo.

**Reintento con feedback.** Cuando la respuesta no sirve, el siguiente intento agrega al mensaje de usuario el error concreto:

```
Tu respuesta anterior no cumplió el contrato: category: Input should be 'billing', 'technical', 'account' or 'other'
Devolvé únicamente el objeto JSON corregido, sin texto adicional.
```

Esto es más útil que reintentar a ciegas: el modelo recibe **qué** falló. Se usa un solo turno de usuario (no historial de chat) para mantener el costo de cada intento acotado y predecible.

**Política de intentos.** Con `MAX_RETRIES=2` hay hasta **3 intentos** en total. El primero no cuenta como reintento. Los `ProviderError` también consumen intentos, pero no se reenvían como feedback de formato sino como error del proveedor.

**Fallback.** Si se agotan los intentos, el pipeline construye a mano:

```python
TriageResponse(
    answer=FALLBACK_ANSWER,        # "No pudimos procesar tu consulta automáticamente..."
    confidence=0.0,
    category=Category.OTHER,
    actions=["Escalar la consulta a un agente humano"],
)
```

El fallback **cumple el contrato**, así que el consumidor nunca recibe una forma distinta. `success=False` y `error` quedan registrados en métricas. Un fallo del modelo se convierte en trabajo para un humano, no en un crash.

**Contabilidad.** `_Usage` acumula tokens de **todos** los intentos. Un request con dos reintentos cuesta tres llamadas, y el costo registrado lo refleja.

### 4.5 Métricas: `observability/`

`build_record` arma el diccionario; `append_metric` lo escribe:

```python
with path.open("a", encoding="utf-8", newline="\n") as handle:
    handle.write(line + "\n")
```

- `"a"`: append. Nunca se reescribe el archivo.
- `newline="\n"`: fuerza LF en Windows, coherente con `.gitattributes`.
- `ensure_ascii=False` en la línea de métricas: el archivo es UTF-8 legible. (La CLI, en cambio, emite ASCII: ver ADR-008.)

Si la escritura falla (`OSError`), la CLI **imprime igual la respuesta**, registra el error y sale con código `1`. Perder una métrica no debe perder la respuesta al cliente.

### 4.6 CLI: `main.py`

```bash
python -m src.main --query "..."                 # JSON compacto en stdout
python -m src.main --query "..." --pretty        # JSON indentado
echo "..." | python -m src.main --query -        # desde stdin
python -m src.main --query "..." --provider mock --prompt v1
```

Contrato de salida de la CLI:

| Canal | Contenido |
|---|---|
| `stdout` | **solo** el JSON del contrato. Nada más. Un consumidor puede hacer `json.loads(stdout)` |
| `stderr` | logs (`INFO`, `WARNING` por reintento, `ERROR` por fallback) y errores de uso |

Códigos de salida:

| Código | Significado |
|---|---|
| `0` | respuesta emitida y métrica registrada (incluye fallback: el servicio funcionó) |
| `1` | respuesta emitida, pero la métrica no pudo escribirse |
| `2` | error de uso o configuración (consulta vacía, proveedor no disponible, prompt inexistente) |

El fallback sale con `0` a propósito: para el consumidor, el servicio respondió. La calidad se mide en métricas (`success=false`), no en el código de salida.

## 5. Verificación

### 5.1 Tests

```bash
.venv/bin/python tests/test_pipeline.py
.venv/bin/python tests/test_schemas.py
```

```
12/12 tests pasaron
10/10 tests pasaron
```

| Test | Garantiza |
|---|---|
| `test_extract_json_plain` | JSON puro se parsea |
| `test_extract_json_strips_fence` | bloques ` ```json ` se desenvuelven |
| `test_extract_json_finds_object_in_prose` | prosa alrededor no rompe el parseo |
| `test_extract_json_rejects_non_json` | texto sin objeto lanza `ParseError` |
| `test_mock_classifies_example_tickets` | los 8 ejemplos de la consigna se clasifican según su etiqueta |
| `test_pipeline_succeeds_on_first_attempt` | camino feliz: 1 intento, `token_source=estimated`, costo 0 |
| `test_retry_recovers_after_malformed_output` | una respuesta mala seguida de una buena → éxito en 2 intentos |
| `test_fallback_after_all_attempts_fail` | 3 respuestas malas → fallback válido con `success=False` |
| `test_cost_is_reproducible` | `1M` tokens de entrada a $0.40 + `0.5M` de salida a $1.60 = $1.20 |
| `test_metrics_append_jsonl` | dos appends = dos líneas JSON; crea carpetas faltantes; hash de 64 caracteres |
| `test_prompt_render_injects_contract_and_query` | no quedan placeholders sin reemplazar |
| `test_unknown_or_planned_provider_is_unavailable` | `openai`, `anthropic` y desconocidos no se construyen |

### 5.2 Ejecución end-to-end

```bash
.venv/bin/python -m src.main --query "Hola, me cobraron dos veces la suscripción de este mes, necesito que me reintegren uno de los cargos."
```

stdout:

```json
{"answer":"Gracias por escribirnos. Revisamos tu consulta sobre facturación y cobros y te respondemos a la brevedad.","confidence":0.95,"category":"billing","actions":["Verificar pagos y cargos del cliente","Iniciar reintegro si corresponde"]}
```

stderr:

```
INFO triage: request=1988ee7d... provider=mock attempts=1 success=True cost_usd=0.00000000 latency_s=0.0007
```

La línea correspondiente en `data/metrics.jsonl` (campos abreviados):

```json
{"ts":"2026-10-28T00:55:32+00:00","provider":"mock","model":"mock-1","prompt_version":"v1",
 "attempts":1,"retries":0,"success":true,"category":"billing","confidence":0.95,
 "prompt_tokens":494,"completion_tokens":63,"total_tokens":557,"token_source":"estimated",
 "latency_s":0.0007,"cost_usd":0.0,"error":null}
```

### 5.3 Casos de error

| Comando | Resultado |
|---|---|
| `--query "   "` | `error: la consulta está vacía`, código `2` |
| `--provider openai` | `error: ... se implementa en la Fase 3 ...`, código `2` |
| `--prompt v9` | `error: se esperaba un único archivo v9_*.yaml ...`, código `2` |
| `--query - --pretty` (desde stdin) | JSON indentado, código `0` |

Ninguno de los casos de error escribe métricas: no hubo request al pipeline.

## 6. Decisiones y trade-offs

| Decisión | Alternativa | Motivo | Consecuencia |
|---|---|---|---|
| Pipeline separado de la CLI | lógica en `main.py` | testear sin proceso ni `argparse` | un módulo más |
| Errores de proveedor y de formato separados | un solo `except` | reintentar distinto según la causa | más clases de error |
| Feedback del error en el reintento | reintento idéntico | el modelo recibe qué falló | prompt un poco más largo en reintentos |
| Un turno de usuario en el reintento | historial de chat | costo acotado y predecible | el modelo no ve su respuesta anterior |
| No "arreglar" JSON malformado | `json_repair` | el error real queda visible en métricas | más fallbacks si el modelo es sloppy |
| Fallback con `exit 0` | `exit 1` | el servicio sí respondió | la calidad se mide en métricas |
| `query_sha256` en vez de la consulta | guardar el texto | auditoría sin datos personales | no se puede reproducir una consulta desde el log |
| `DEFAULT_PROVIDER=mock` en Fase 2 | `openai` | el repo debe correr sin keys ni SDK | se cambia en la Fase 3 |
| Mock por palabras clave | mock aleatorio | resultados reproducibles para tests | su accuracy no representa a un LLM |

## 7. Errores comunes

| Síntoma | Causa | Fix |
|---|---|---|
| `error: ... implementa en la Fase 3` | `.env` con `DEFAULT_PROVIDER=openai` | poner `mock` o pasar `--provider mock` |
| `ModuleNotFoundError: src` | ejecutar fuera de la raíz del repo | `cd` a la raíz y usar `python -m src.main` |
| `hallados: 0` al cargar el prompt | versión inexistente | revisar `prompts/` y el valor de `--prompt` |
| El log queda en otro directorio | `METRICS_PATH` relativo mal interpretado | usar relativo a la raíz o absoluto |
| Muchas líneas `WARNING` en los tests | los tests de reintento loguean a propósito | normal; no es fallo |
| El JSON en consola tiene `\u00f3` | `ensure_ascii=True` | es el comportamiento esperado; `json.loads` lo decodifica |

## 8. Checklist de cierre

- [x] `src/main.py` acepta consulta por argumento y por stdin
- [x] JSON validado por el contrato en stdout; logs en stderr
- [x] proveedor `mock` sin credenciales ni red
- [x] prompt `v1` versionado en YAML, con render seguro
- [x] reintento con feedback de error, máximo `MAX_RETRIES`
- [x] fallback válido que nunca rompe el contrato
- [x] `data/metrics.jsonl` con una línea por request, append-only
- [x] costo reproducible desde `providers.yaml`
- [x] `token_source` distingue tokens reales de estimados
- [x] 12/12 tests de pipeline y 10/10 de contrato

## 9. Addendum: proveedor Anthropic

Se adelantó la parte de Anthropic de la Fase 3. OpenAI sigue pendiente.

- `src/providers/anthropic_provider.py` implementa `LLMProvider` sobre el SDK oficial.
- El cliente se **inyecta** (`AnthropicProvider(client=...)`): los tests usan un cliente falso y no tocan la red.
- `max_retries=0` en el cliente: la política de reintentos es solo la del pipeline (ADR-015).
- Errores clasificados en `ProviderError` (429, 5xx, timeout, conexión), `ProviderFatalError` (401, 403, 404, 400) y `ProviderUnavailable` (sin clave).
- Un error fatal no se convierte en fallback: se muestra como error de uso con código `2`, porque reintentar una clave inválida no sirve.
- La temperatura es configurable por modelo. En Anthropic está en `null` y no se envía (ADR-016; ver la corrección en §9.1).

```bash
.venv/bin/python -m src.main --query "me cobraron dos veces" --provider anthropic
# error: falta ANTHROPIC_API_KEY. Copiá .env.example a .env y completá la clave, o usá --provider mock
# exit=2, y no se escribe ninguna línea en metrics.jsonl
```

Tests del proveedor: `tests/test_anthropic_provider.py`, 13/13 con cliente falso.

### 9.1 Primera llamada real: lo que falló y lo que cambió

El primer intento con `temperature: 0.0` devolvió:

```
error: el proveedor 'anthropic' rechazó la solicitud: BadRequestError: Error code: 400 -
{'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'temperature: Extra inputs are not permitted'}}
```

Los tests simulados no lo detectaron, porque el cliente falso acepta cualquier argumento. Por eso se agregó ADR-017: un proveedor se considera verificado solo tras una llamada real.

El fix fue hacer la temperatura opcional por modelo y no enviarla cuando el modelo no la acepta (ADR-016). El error 400 se clasifica como fatal, así que no se reintenta: reintentarlo habría gastado llamadas sin cambiar nada.

> **Corrección (Fase 3, 2026-11-04).** El diagnóstico de arriba era incorrecto: el rechazo no es del modelo. El SDK 2.1.0 envía `anthropic-version: 2026-10-21`, y desde esa versión la API rechaza `temperature`, `top_p` y `top_k` en **todos** los modelos de Claude. El código ahora nunca envía muestreo a Anthropic y falla antes de llamar a la red si alguien lo configura. Detalle en el Capítulo 4, §5 y en ADR-016.

### 9.2 Prueba real exitosa

```bash
.venv/bin/python -m src.main --query "Me cobraron dos veces la suscripción" --provider anthropic --pretty
```

```
INFO httpx2: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
INFO triage: request=da8b8dba... provider=anthropic attempts=1 success=True cost_usd=0.00160800 latency_s=2.4814
```

Línea de `metrics.jsonl` (campos relevantes):

```json
{"provider":"anthropic","model":"claude-haiku-4-5","prompt_version":"v1","attempts":1,"success":true,
 "category":"billing","confidence":0.95,"prompt_tokens":603,"completion_tokens":201,"total_tokens":804,
 "token_source":"api","latency_s":2.4814,"cost_usd":0.001608,"error":null}
```

Lo que confirma esta corrida:

- `token_source` es `api`: los tokens son los que informó Anthropic, no una estimación.
- El costo sale de `providers.yaml` con los precios de referencia. Está calculado; **no está verificado contra la factura**. Los precios siguen pendientes de confirmar.
- La respuesta del modelo es mucho más larga que la del mock (201 tokens de salida). Esto va a pesar en el costo y en la latencia de la Fase 7, y es un punto a medir, no a suponer.

### 9.3 Pendientes que quedan

- Confirmar precios y ID del modelo en la página oficial antes de la comparativa.
- Medir la varianza: sin temperatura, dos corridas de la misma consulta pueden diferir. Se mide en la Fase 7.
- Revisar la extensión de `answer`: la respuesta real supera el texto de ejemplo del contrato; el límite de 800 caracteres todavía no se probó con ese volumen.

---

**Anterior:** [Capítulo 2 — El contrato](02-fase-1-contrato.md) · **Siguiente:** [Capítulo 4 — Multi-proveedor](04-fase-3-multi-proveedor.md)
