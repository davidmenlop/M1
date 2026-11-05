# Apéndice A — Registro de decisiones (ADR)

> Cada decisión técnica con su contexto, alternativas y consecuencias.
> Formato: **ADR-NNN**. Una decisión no se borra: se reemplaza por otra ADR.

---

## ADR-001 — Python 3.14

- **Fecha:** 2026-10-22
- **Estado:** aceptada
- **Contexto:** hay que fijar la versión de intérprete para un proyecto con `pydantic-core` (Rust), `jiter` (Rust) y `PyYAML` (C).
- **Decisión:** usar Python 3.14 (3.14.3), build estándar con GIL.
- **Alternativas:** 3.15 (sin wheel de `PyYAML`), 3.12 (compatible pero más viejo), 3.14t free-threaded (extensiones sin wheels `cp314t`).
- **Consecuencias:** instalación sin compilaciones; el `.python-version` pinnea minor, no patch.

## ADR-002 — `uv` como gestor de entorno

- **Fecha:** 2026-10-22
- **Estado:** aceptada
- **Contexto:** en la máquina, `python3` apunta a 3.9.6 y `pip3` al 3.15. Ese desajuste produce instalaciones invisibles.
- **Decisión:** crear y poblar el venv con `uv`, manteniendo `venv` + `pip` como camino alternativo documentado.
- **Alternativas:** `python -m venv` + `pip` (funciona, pero deja el error del intérprete a criterio del operador); Poetry/Conda (una herramienta más para un módulo que no la necesita).
- **Consecuencias:** un comando crea el entorno correcto; no se agrega `pyproject.toml`, así que no se usa `uv run`.

## ADR-003 — `requirements.txt` como fuente de dependencias

- **Fecha:** 2026-10-22
- **Estado:** aceptada
- **Contexto:** la consigna exige `requirements.txt`; `pyproject.toml` sería más idiomático para `uv`.
- **Decisión:** `requirements.txt` con pins exactos (`==`), sin `pyproject.toml`.
- **Alternativas:** `pyproject.toml` + `uv.lock`; ambos archivos duplicando dependencias.
- **Consecuencias:** el README y el corrector usan el camino estándar; se pierde `uv run` y el lockfile.

## ADR-004 — `actions` como `list[str]`

- **Fecha:** 2026-10-22
- **Estado:** aceptada
- **Contexto:** el contrato pide "una lista de acciones sugeridas para el agente humano"; no especifica forma interna.
- **Decisión:** `list[str]`, 1 a 3, con vocabulario sugerido en el prompt.
- **Alternativas:** objetos `{type, detail, requires_human}` (más útiles, más frágiles de parsear y de puntuar).
- **Consecuencias:** parseo robusto y scoring simple; si el Módulo 2 necesita estructura, se versiona el contrato.

## ADR-005 — Validación estricta, sin corrección silenciosa

- **Fecha:** 2026-10-22
- **Estado:** aceptada
- **Contexto:** el modelo puede devolver campos extra, `confidence` fuera de rango o categorías inexistentes.
- **Decisión:** `extra="forbid"`; `confidence` fuera de [0,1] falla (no se clampea); categoría desconocida falla.
- **Alternativas:** `extra="ignore"` (tolera `reasoning`), clamp de confianza, mapeo de sinónimos en español.
- **Consecuencias:** las desviaciones se detectan y disparan retry; la calibración no se falsea. El pipeline debe limpiar campos internos antes de validar.

## ADR-006 — Truncar `actions` a 3

- **Fecha:** 2026-10-22
- **Estado:** aceptada
- **Contexto:** un modelo puede devolver 4 o 5 acciones correctas.
- **Decisión:** conservar las 3 primeras, sin fallar.
- **Alternativas:** fallar y reintentar (más estricto, más costo y latencia); aceptar todas (rompe el contrato).
- **Consecuencias:** no se gasta un retry por un exceso trivial; se pierde información. Se monitorea la distribución de `len(actions)`.

## ADR-007 — `metrics.jsonl` y `evals/results/` versionados

- **Fecha:** 2026-10-22
- **Estado:** aceptada
- **Contexto:** el checklist exige una ejecución registrada y el README debe mostrar resultados de evals.
- **Decisión:** versionar `data/metrics.jsonl` (al menos una línea real) y `evals/results/*.json`.
- **Alternativas:** ignorarlos y commitear solo ejemplos (`*.example.jsonl`), que no cumplen literalmente el checklist.
- **Consecuencias:** el log crece en el repo y los diffs incluyen datos; a cambio, la evidencia es verificable.

## ADR-008 — Dos serializaciones: ASCII para CLI, UTF-8 para prompt

- **Fecha:** 2026-10-22
- **Estado:** aceptada
- **Contexto:** Windows usa cp1252 en consola; un `print` con tildes puede lanzar `UnicodeEncodeError`. Pero dentro del prompt las tildes deben ser legibles.
- **Decisión:** `to_json()` con `ensure_ascii=True`; `json_contract()` con `ensure_ascii=False`.
- **Alternativas:** UTF-8 en todo (rompe consolas Windows viejas); ASCII en todo (degrada la legibilidad del prompt).
- **Consecuencias:** dos métodos con propósitos distintos; documentado en el Capítulo 2.

## ADR-009 — `MockProvider` desde la Fase 2

- **Fecha:** 2026-10-22
- **Estado:** aceptada
- **Contexto:** el corrector puede no tener API keys y el entorno de evaluación podría no tener red.
- **Decisión:** implementar un proveedor determinista `mock` que cumpla el mismo contrato, y usarlo como camino por defecto para tests y evals de humo.
- **Alternativas:** exigir keys para correr cualquier cosa.
- **Consecuencias:** el repo se instala y corre sin credenciales; las evals reales siguen requiriendo keys.

## ADR-010 — `temperature: 0.0`

- **Fecha:** 2026-10-22
- **Estado:** aceptada para OpenAI (verificada con llamada real en la Fase 3). **No aplica a Anthropic** (ADR-016): su API rechaza la temperatura en todos los modelos.
- **Contexto:** la tarea es clasificación y extracción, no generación creativa.
- **Decisión:** temperatura 0 en todos los proveedores, configurable por YAML.
- **Alternativas:** 0.2–0.7 para respuestas más naturales.
- **Consecuencias:** mayor determinismo y comparabilidad entre corridas; respuestas potencialmente más repetitivas.

## ADR-012 — `mock` como proveedor por defecto

- **Fecha:** 2026-10-27 · **Revisada:** 2026-11-04
- **Estado:** aceptada (revisada en la Fase 3)
- **Contexto:** `.env.example` decía `DEFAULT_PROVIDER=openai`, pero el proveedor aún no existía. Copiar el ejemplo rompía la CLI en el primer uso. La versión original de esta ADR preveía volver a `openai` en la Fase 3.
- **Decisión:** `mock` queda como default **de forma permanente**. Los proveedores reales se eligen con `--provider openai|anthropic` o con `DEFAULT_PROVIDER` en el `.env` local.
- **Alternativas:** volver a `openai` en la Fase 3, como se planeó (un clon limpio sin clave falla en el primer comando del README).
- **Consecuencias:** `git clone` → instalar → `python -m src.main --query ...` funciona sin credenciales, que es lo que evalúa la rúbrica de reproducibilidad. Quien tenga claves cambia una variable.

## ADR-013 — Métricas con hash de la consulta, no con el texto

- **Fecha:** 2026-10-27
- **Estado:** aceptada
- **Contexto:** `metrics.jsonl` se versiona en el repositorio público. Las consultas de clientes pueden contener datos personales.
- **Decisión:** registrar `query_sha256` y `query_chars`. El texto no se persiste.
- **Alternativas:** guardar la consulta completa (útil para depurar, riesgoso en un repo público); guardar un prefijo truncado (filtra información parcial).
- **Consecuencias:** se puede verificar que dos requests son la misma consulta, pero no reproducirla desde el log. Para reproducir un caso se usa el dataset de evals, no las métricas.

## ADR-014 — Reintento con feedback en un solo turno

- **Fecha:** 2026-10-27
- **Estado:** aceptada
- **Contexto:** cuando la salida no cumple el contrato, hay que volver a pedirla. Existen dos formas: añadir el intento fallido y el error como historial de chat, o repetir el mensaje original con el error al final.
- **Decisión:** repetir el mensaje de usuario original y agregar el error de validación al final. Un solo turno, sin historial.
- **Alternativas:** historial multi-turno (el modelo ve su error y lo corrige mejor, pero el costo crece con cada intento y depende de la API).
- **Consecuencias:** costo de cada intento acotado y comparable entre proveedores. Si las evals muestran que el feedback no mejora el `retry_rate`, se revisa.

## ADR-015 — Reintentos en un solo lugar: se desactivan los del SDK

- **Fecha:** 2026-10-28
- **Estado:** aceptada
- **Contexto:** el SDK de Anthropic reintenta por defecto (2 veces) ante 429 y 5xx. Esos reintentos ocurren dentro de una sola llamada: no aparecen en `attempts` ni en el costo de `metrics.jsonl`.
- **Decisión:** `anthropic.Anthropic(max_retries=0)`. La única política de reintentos es la del pipeline, que sí se registra.
- **Alternativas:** dejar el reintento del SDK (menos código, métricas incompletas); sumar ambos (reintentos multiplicados y costo oculto).
- **Consecuencias:** el costo y el número de intentos reflejan lo que realmente se envió. Los errores se clasifican en tres grupos: `ProviderError` (reintentable), `ProviderFatalError` (clave inválida, modelo inexistente, request mal formada; no se reintenta) y `ProviderUnavailable` (sin clave, detectado antes de llamar).

## ADR-016 — Anthropic no envía parámetros de muestreo

- **Fecha:** 2026-10-28 · **Corregida:** 2026-11-04
- **Estado:** aceptada (corrige el diagnóstico original)
- **Contexto:** la primera llamada real con `temperature` devolvió `400 invalid_request_error: temperature: Extra inputs are not permitted`. El diagnóstico original fue que *`claude-haiku-4-5` no acepta el parámetro*. **Era incorrecto.** El SDK 2.1.0 envía `anthropic-version: 2026-10-21` (`anthropic/_constants.py`), y desde esa versión de la API `temperature`, `top_p` y `top_k` devuelven 400 en **todos** los modelos de Claude. Por eso el SDK tampoco los expone como parámetros.
- **Decisión:** `AnthropicProvider` nunca envía muestreo. Si `providers.yaml` configura una `temperature` para Anthropic, el proveedor falla con `ProviderFatalError` **antes** de llamar a la red, con un mensaje que explica el motivo. En los modelos que piensan (Haiku 5.5), la variabilidad y el costo se controlan con `effort` (ADR-019).
- **Alternativas:** ignorar en silencio la temperatura configurada (oculta la diferencia entre lo que dice el YAML y lo que se envía); fijar el SDK a una versión anterior (contradice tener deps actuales y solo posterga el problema).
- **Consecuencias:** **ADR-010 no se cumple para Anthropic**: no hay forma de pedir temperatura 0 con esta API. Dos corridas idénticas pueden dar salidas distintas; las evals de la Fase 7 deben repetirse para medir la varianza. OpenAI (`gpt-4.1-mini`) sí acepta `temperature: 0.0`, lo que vuelve más determinista esa columna de la comparativa.

## ADR-017 — Verificación real: la llamada a la API se prueba antes de cerrar la fase

- **Fecha:** 2026-10-28
- **Estado:** aceptada
- **Contexto:** los tests con cliente falso no detectaron que la API rechaza `temperature`. Solo lo mostró la llamada real. Y aun con la llamada real, la causa se atribuyó mal al modelo (ADR-016): un error se verifica contra la documentación, no solo contra el mensaje.
- **Decisión:** cada proveedor se considera verificado únicamente después de una llamada real exitosa, registrada en `metrics.jsonl`. Los tests con cliente falso validan la lógica, no el contrato con la API.
- **Alternativas:** confiar en el SDK y en los tests simulados (ya falló una vez).
- **Consecuencias:** la verificación real requiere clave y gasta tokens; se hace una vez por proveedor y por cambio de modelo.

## ADR-018 — OpenAI con Chat Completions y JSON mode

- **Fecha:** 2026-11-04
- **Estado:** aceptada
- **Contexto:** la Fase 3 necesita un segundo proveedor real con el mismo contrato. El SDK `openai==3.37.0` ofrece Chat Completions, con `response_format` para JSON mode y JSON Schema estricto.
- **Decisión:** `chat.completions.create` con `response_format={"type": "json_object"}`, `max_completion_tokens` (no el obsoleto `max_tokens`) y `temperature` solo si no es `null`. `max_retries=0` en el cliente, igual que en Anthropic (ADR-015). El schema lo sigue validando Pydantic.
- **Alternativas:** `json_schema` estricto (garantiza el schema, pero acopla el proveedor al contrato y hace que la comparativa con Anthropic sea desigual); sin JSON mode (más reintentos por texto alrededor del JSON).
- **Consecuencias:** OpenAI siempre devuelve JSON parseable; los errores posibles quedan en el nivel del schema (campos faltantes o valores inválidos), que el pipeline ya reintenta con feedback. La comparación entre proveedores es justa: los dos reciben el mismo prompt y pasan por la misma validación.

## ADR-019 — Varios modelos por proveedor; Haiku 5.5 con `effort: low`

- **Fecha:** 2026-11-04
- **Estado:** aceptada; **Haiku 5.5 sin verificar con llamada real** (la cuenta de Anthropic no tenía saldo)
- **Contexto:** `claude-haiku-4-5` es de la generación anterior. El Haiku actual, `claude-haiku-5-5`, cuesta $0.10 / $0.50 por 1M tokens, 10 veces menos. A diferencia de 4.5, piensa por defecto con `effort: medium`, y el thinking consume `max_tokens` y se factura como salida.
- **Decisión:** `providers.yaml` admite varios modelos por proveedor, elegidos con `--model <clave>` (por defecto, `default`). Se agrega `anthropic.haiku-5-5` con `effort: low` (clasificación simple) y `max_tokens: 2000` para dejar margen al thinking. `default` sigue siendo Haiku 4.5 hasta que la Fase 7 decida con datos.
- **Alternativas:** reemplazar 4.5 por 5.5 directamente (se pierde la comparación); desactivar el thinking (posible en Haiku 5.5 con effort ≤ high, pero `low` deja que el modelo decida y suele ser suficiente).
- **Consecuencias:** la comparativa de la Fase 7 puede incluir 3 modelos reales sin tocar código. `effort` es un campo nuevo del contrato `LLMProvider.complete`: Anthropic lo envía como `output_config.effort` y OpenAI como `reasoning_effort`.

## ADR-020 — Prompts inmutables con ejemplos validados al cargar

- **Fecha:** 2026-11-04
- **Estado:** aceptada
- **Contexto:** la comparativa de la Fase 7 guarda resultados por versión de prompt. Si un YAML se edita después de evaluarlo, el resultado ya no corresponde al prompt. Además, un ejemplo few-shot que viola el contrato le enseña al modelo a violarlo.
- **Decisión:** una versión evaluada no se edita; cualquier cambio es una versión nueva. `load_prompt` valida cada ejemplo contra `TriageResponse` y falla al cargar si alguno no cumple.
- **Alternativas:** editar en el lugar y confiar en git para saber qué se evaluó (frágil: los resultados no guardan el hash del prompt); no validar los ejemplos (el error aparece como peor accuracy, sin causa visible).
- **Consecuencias:** pueden acumularse versiones; es el precio de que cada número sea trazable. Un ejemplo mal escrito se detecta antes de gastar una sola request.

## ADR-021 — El razonamiento de CoT va en un campo interno que se descarta

- **Fecha:** 2026-11-04
- **Estado:** aceptada
- **Contexto:** chain-of-thought requiere que el modelo escriba su razonamiento, pero el contrato es `extra="forbid"` y el cliente no debe verlo. La Fase 1 ya lo anticipaba.
- **Decisión:** el prompt declara `internal_fields` (`reasoning`), que se agregan **primero** al JSON Schema inyectado. El pipeline los quita antes de validar. No se guardan en `metrics.jsonl`.
- **Alternativas:** razonamiento en texto libre antes del JSON (rompe JSON mode de OpenAI y obliga a un parseo más laxo); relajar `extra="forbid"` (abre el contrato a cualquier campo); thinking nativo del modelo (no existe en `gpt-4.1-mini` y haría la técnica desigual entre proveedores).
- **Consecuencias:** la técnica es idéntica en todos los proveedores y el contrato público no cambia. El razonamiento cuesta tokens de salida y no queda registrado para depurar; si hace falta, se agrega a los resultados de evals (que no contienen datos de clientes), no a las métricas.

## ADR-022 — Criterio de selección de prompt declarado antes de medir

- **Fecha:** 2026-11-04
- **Estado:** aceptada
- **Contexto:** la rúbrica exige elegir el prompt con datos y con un criterio fijado de antemano. Elegir después de ver los números invita a justificar el resultado preferido.
- **Decisión:** requisitos mínimos (schema 100 %, `retry_rate` ≤ 10 %) → macro-F1 en dev → si la diferencia es < 0.03, action score → si sigue < 0.03, costo por request y latencia p95. Confirmación única en holdout (caída > 0.10 = sobreajuste reportado). Anthropic: promedio de 3 corridas. La resistencia a inyecciones se reporta aparte (Fase 9). Detalle en el Capítulo 5, §7.
- **Alternativas:** accuracy como métrica principal (engañosa con clases desbalanceadas); un puntaje ponderado único (los pesos serían arbitrarios y se podrían ajustar a posteriori).
- **Consecuencias:** el resultado de la Fase 7 queda determinado por los datos, incluso si gana el prompt más simple. El umbral de 0.03 refleja que con 32 casos un acierto mueve unos 3 puntos: diferencias menores son ruido.

## ADR-023 — Acciones esperadas como intents con keywords

- **Fecha:** 2026-11-04
- **Estado:** aceptada
- **Contexto:** las acciones del modelo son texto libre ("Verificar los cobros del cliente"), así que compararlas por igualdad exacta daría casi siempre 0. La guía inicial hablaba de `expected_actions_any` sin definir cómo se comparaba.
- **Decisión:** cada caso lista *intents* (lo que un buen agente haría), cada uno con keywords normalizadas (minúsculas, sin tildes). Un intent se cumple si alguna acción del modelo contiene alguna de sus keywords. El *action score* de un caso es intents cumplidos / intents esperados.
- **Alternativas:** LLM-as-judge (captura sinónimos, pero cuesta, varía entre corridas y hay que validarlo a su vez); embeddings (agrega una dependencia y un umbral arbitrario); igualdad exacta (inútil con texto libre).
- **Consecuencias:** el puntaje es gratis, determinista y auditable. Puede dar falsos negativos si el modelo usa un sinónimo que no está en la lista: los fallos se revisan en la Fase 7 y, si hace falta, se amplían las keywords (lo que cambia el dataset, no los prompts). El action score es un desempate (ADR-022), no la métrica principal.

## ADR-024 — Borrador del asistente, etiqueta de una persona

- **Fecha:** 2026-11-04
- **Estado:** aceptada
- **Contexto:** si el mismo asistente que escribe los prompts también fija las etiquetas, la eval mide cuánto coincide el modelo con el asistente, no con el negocio.
- **Decisión:** el asistente propone el borrador (`proposed_category`, `rationale`); una persona confirma o corrige cada caso con `review_labels.py`. Solo los casos `validated` entran a las evals. Se reporta la tasa de acuerdo entre el borrador y la revisión.
- **Alternativas:** etiquetado 100 % humano desde cero (más lento); usar el borrador sin revisión (sesgo circular).
- **Consecuencias:** riesgo de **anclaje**: la persona tiende a aceptar lo que ve. Para mitigarlo, cada caso muestra el motivo y la regla aplicada, para que se pueda discutir, y existe el estado `disputed`. Una tasa de acuerdo del 100 % no prueba que el borrador sea perfecto: puede ser anclaje.

## ADR-025 — Dataset sintético, escrito a mano

- **Fecha:** 2026-11-04
- **Estado:** aceptada
- **Contexto:** no hay tickets reales de Nubbix disponibles, y el repositorio es público.
- **Decisión:** casos escritos a mano a partir de situaciones típicas de un SaaS de gestión para pymes de LATAM, incluidos los casos borde que pide la guía.
- **Alternativas:** tickets reales anonimizados (más realistas, pero no existen y anonimizar bien es difícil); generarlos con un LLM (tienden a ser homogéneos y "de libro").
- **Consecuencias:** sin datos personales en el repo. El dataset es más limpio que el soporte real: las métricas son una cota optimista, y así se reporta.

## ADR-026 — Resultados de evals autocontenidos y separados de las métricas de producción

- **Fecha:** 2026-11-04
- **Estado:** aceptada
- **Contexto:** la comparativa de la Fase 7 se va a leer y defender después de correrla. Un número sin el prompt, el dataset y el código exactos que lo produjeron no es evidencia. Además, el pipeline ya escribe `data/metrics.jsonl` en cada request de la CLI.
- **Decisión:** cada corrida guarda un JSON en `evals/results/` (versionado) con el sha256 del prompt, el sha256 del dataset, el commit y si el árbol estaba sucio, la configuración del modelo, las métricas y cada caso. El runner **no** escribe en `metrics.jsonl`. Ante un error fatal, aborta sin guardar. Solo cuentan como evidencia las corridas con `dirty: false`.
- **Alternativas:** escribir también en `metrics.jsonl` (mezcla tráfico de evals con tráfico real); guardar solo el resumen (no se pueden revisar los errores caso por caso); guardar resultados parciales (se confunden con corridas completas).
- **Consecuencias:** ~50 KB por corrida en git. Un resultado se puede invalidar comparando hashes si el prompt o el dataset cambiaron. Las dos primeras corridas de la Fase 6 se descartaron y repitieron por haberse hecho con el runner sin commitear.

## ADR-027 — Prompt v4 creado después de ver dev, con confirmación obligatoria en holdout

- **Fecha:** 2026-11-04
- **Estado:** aceptada
- **Contexto:** la revisión humana pasó `bil-03` (baja de la suscripción) y `bil-08` (email de facturas) a `account`. v2 y v3 dicen lo contrario y los tres modelos fallan `bil-03` con v1. Los prompts son inmutables (ADR-020), así que corregirlo exige una versión nueva, creada después de ver resultados en dev.
- **Decisión:** v4 = v3 + la taxonomía y las reglas de desempate de la guía de etiquetado validada, y la regla de no inventar descuentos ni promociones. Mismos ejemplos, mismo campo interno y misma sección de seguridad que v3 (un test lo verifica), para que la diferencia se atribuya solo a las reglas. Entra a la comparativa con el mismo criterio (ADR-022). Si gana, su resultado en dev se reporta como optimista y la elección depende de que no caiga más de 0.10 en holdout.
- **Alternativas:** editar v3 (rompe la trazabilidad de los resultados ya guardados); dejar el conflicto y aceptar el error (mide al modelo contra una regla que nadie le dio); agregar ejemplos parecidos a `bil-03` (sería entrenar con el examen).
- **Consecuencias:** las reglas salen de la guía, no de los errores observados, pero se eligieron sabiendo cuáles casos fallaban: hay riesgo de sobreajuste a dev. El holdout tiene solo 8 casos, así que es una confirmación débil y así se reporta.

## ADR-028 — Haiku 5.5 con v4 como combinación elegida; v4 como prompt predeterminado

- **Fecha:** 2026-11-04
- **Estado:** aceptada
- **Contexto:** la Fase 7 corrió 4 prompts × 3 modelos en dev y aplicó el criterio de ADR-022 con `evals/select.py`.
- **Decisión:** gana `claude-haiku-5-5` con v4: macro-F1 1.000 (3 corridas), empatado con `gpt-4.1-mini` + v4 en F1 y action score, y a la mitad de costo (USD 0.0005 por request). Confirmado en holdout: 8/8 en la ronda 1 y 14/14 en la ronda 2, que incluye casos de las reglas nuevas (ADR-029). `DEFAULT_PROMPT_VERSION` pasa a v4. El proveedor predeterminado sigue siendo `mock` (ADR-012): usar el ganador exige `--provider anthropic --model haiku-5-5`.
- **Alternativas:** `gpt-4.1-mini` + v4 (mismo resultado, el doble de costo, menor latencia: 1.75 s vs 2.79 s de p95; sería la elección si la latencia importara más que el costo, pero el criterio fijado no lo dice); Haiku 4.5 + v2 (el ganador sin v4; casi 5 veces más caro); cambiar la clave `default` de Anthropic a Haiku 5.5 (rompería el significado de las corridas ya guardadas con `model_key: default`).
- **Consecuencias:** el resultado en dev es optimista (ADR-027). El holdout de la ronda 1 no probaba las reglas nuevas; el de la ronda 2 sí, y v3 falla 3 de esos 6 casos mientras v4 los acierta (ADR-029). Con 0 errores, la calibración de `confidence` no se puede evaluar.

## ADR-029 — Holdout ampliado con casos de las reglas de v4; ronda 2 sin Haiku 4.5

- **Fecha:** 2026-11-04
- **Estado:** aceptada
- **Contexto:** la ronda 1 de la Fase 7 dejó dos problemas. El holdout de 8 casos no tenía bajas de suscripción ni emails de facturas, así que no probaba las reglas de v4. Y `oth-01` esperaba "Informar planes o descuentos", que contradice la regla de v4 de no afirmar políticas comerciales. Además, Haiku 4.5 fue el 81 % del costo de la ronda (USD 1.08) y no ganó.
- **Decisión:** (1) por decisión humana, `oth-01` espera solo "Derivar al equipo comercial"; (2) el asistente escribe 6 casos nuevos de holdout a partir de la guía de etiquetado, sin correrlos, incluidos contrastes (`bil-09`: baja + cobro → billing; `bil-10`: mail + CUIT → billing); una persona los valida antes de evaluar; (3) el holdout pasa de 8 a 14 casos; (4) la comparativa se repite completa solo con `gpt-4.1-mini` y Haiku 5.5: el usuario excluyó Haiku 4.5 por costo.
- **Alternativas:** dejar el holdout como estaba (la confirmación no probaba nada); mover casos de dev a holdout (cambia la base de la selección); seguir con Haiku 4.5 (unos USD 0.80 más por ronda, para un modelo que no ganó).
- **Consecuencias:** cambia el sha256 del dataset y `select.py` descarta toda la ronda 1. La ronda 2 cuesta USD 0.28 y elige lo mismo. Los casos nuevos se escribieron conociendo v4, pero no se corrieron hasta después de la validación humana; el diagnóstico con v3 (falla 3 de 6) muestra que exigen las reglas. Para usar Haiku 4.5 de nuevo hace falta revisar esta decisión.

## ADR-011 — Rama `master`

- **Fecha:** 2026-10-22
- **Estado:** aceptada
- **Contexto:** el repositorio ya se creó y pusheó como `master`.
- **Decisión:** no renombrar a `main`.
- **Alternativas:** `git branch -M main` + cambiar el default en GitHub.
- **Consecuencias:** ninguna funcional; se documenta para evitar confusión en comandos del README.

---

## Plantilla para nuevas decisiones

```markdown
## ADR-NNN — Título

- **Fecha:** YYYY-MM-DD
- **Estado:** propuesta | aceptada | reemplazada por ADR-NNN
- **Contexto:** qué problema obliga a decidir.
- **Decisión:** qué se elige.
- **Alternativas:** qué se descartó y por qué.
- **Consecuencias:** qué se gana, qué se pierde, qué queda pendiente.
```
