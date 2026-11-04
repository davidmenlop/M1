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
- **Estado:** aceptada para OpenAI (pendiente Fase 3). **Matizada por ADR-016:** no aplica a `claude-haiku-4-5`, que no acepta el parámetro.
- **Contexto:** la tarea es clasificación y extracción, no generación creativa.
- **Decisión:** temperatura 0 en todos los proveedores, configurable por YAML.
- **Alternativas:** 0.2–0.7 para respuestas más naturales.
- **Consecuencias:** mayor determinismo y comparabilidad entre corridas; respuestas potencialmente más repetitivas.

## ADR-012 — `mock` como proveedor por defecto hasta la Fase 3

- **Fecha:** 2026-10-27
- **Estado:** aceptada
- **Contexto:** `.env.example` decía `DEFAULT_PROVIDER=openai`, pero el proveedor aún no existe. Copiar el ejemplo rompía la CLI en el primer uso.
- **Decisión:** `DEFAULT_PROVIDER=mock` y `default_provider: mock` en `providers.yaml` durante la Fase 2. Se vuelve a `openai` en la Fase 3.
- **Alternativas:** dejar `openai` y documentar `--provider mock` en cada comando; implementar OpenAI antes de tiempo.
- **Consecuencias:** el repo funciona desde un clon limpio sin credenciales. Hay que acordarse de cambiar el default en la Fase 3; queda marcado con un comentario en el YAML.

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

## ADR-016 — Temperatura configurable por modelo; omitida para `claude-haiku-4-5`

- **Fecha:** 2026-10-28
- **Estado:** aceptada (reemplaza el supuesto inicial de enviarla siempre)
- **Contexto:** la primera llamada real con `temperature` enviada por `extra_body` devolvió `400 invalid_request_error: temperature: Extra inputs are not permitted`. El modelo no acepta el campo.
- **Decisión:** `temperature` pasa a ser `float | null` en `providers.yaml`. Si es `null`, el proveedor no envía el campo. Para `claude-haiku-4-5` es `null`. Si un modelo sí lo acepta, se configura un número y se envía.
- **Alternativas:** reintentar sin temperatura por error (oculta el problema y duplica llamadas); forzar `temperature` en todos los modelos (rompe este); actualizar el SDK (no lo resuelve: el rechazo es del modelo, no del cliente).
- **Consecuencias:** **ADR-010 no se cumple para este proveedor**: el modelo elige su propia aleatoriedad, y dos corridas idénticas pueden dar salidas distintas. La comparativa de la Fase 7 tiene que tenerlo en cuenta, y las evals deben repetirse para medir varianza.

## ADR-017 — Verificación real: la llamada a la API se prueba antes de cerrar la fase

- **Fecha:** 2026-10-28
- **Estado:** aceptada
- **Contexto:** los tests con cliente falso no detectaron que el modelo rechaza `temperature`. Solo lo mostró la llamada real.
- **Decisión:** cada proveedor se considera verificado únicamente después de una llamada real exitosa, registrada en `metrics.jsonl`. Los tests con cliente falso validan la lógica, no el contrato con la API.
- **Alternativas:** confiar en el SDK y en los tests simulados (ya falló una vez).
- **Consecuencias:** la verificación real requiere clave y gasta tokens; se hace una vez por proveedor y por cambio de modelo.

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
