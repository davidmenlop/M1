# Capítulo 2 — El contrato (Fase 1)

> Antes de hablar con un LLM, definimos exactamente qué forma tiene una respuesta
> válida. El modelo se adapta al contrato; el contrato no se adapta al modelo.

---

## 1. Objetivo

Implementar `src/schemas.py`: el modelo Pydantic que define, valida y serializa la salida del servicio.

Al terminar la fase:

- el contrato `{answer, confidence, category, actions}` existe en código;
- hay reglas explícitas de normalización y de rechazo;
- el contrato se puede exportar como **JSON Schema** para inyectarlo en el prompt;
- hay 10 tests ejecutables sin framework.

## 2. Por qué el contrato primero

Tres razones concretas:

1. **Estabilidad para el consumidor.** El sistema de tickets de Nubbix va a leer este JSON. Si el esquema cambia a mitad del proyecto, se rompe la integración y hay que rehacer el dataset y las evals.
2. **Detección de errores del modelo.** Sin validación, una respuesta con `confidence: "alta"` o `category: "ventas"` pasa silenciosamente y contamina las métricas.
3. **Base del retry.** El mecanismo de reintento necesita un error **estructurado** para reenviárselo al modelo. `ValidationError` de Pydantic da exactamente eso: campo, valor y motivo.

El contrato es, en los hechos, la API del servicio.

## 3. El contrato

```json
{
  "answer": "Revisamos el cargo duplicado y procesamos el reintegro en 48 h.",
  "confidence": 0.86,
  "category": "billing",
  "actions": ["Verificar pagos duplicados", "Solicitar reintegro"]
}
```

| Campo | Tipo | Regla |
|---|---|---|
| `answer` | `str` | 1–800 caracteres, no vacío ni solo espacios |
| `confidence` | `float` | 0.0 ≤ x ≤ 1.0, estricto |
| `category` | enum | `billing`, `technical`, `account`, `other` |
| `actions` | `list[str]` | 1–3 items, sin vacíos ni duplicados |

Regla transversal: **ningún campo extra**. `{..., "reasoning": "..."}` es inválido.

## 4. Decisiones de diseño

### 4.1 `actions` como `list[str]`, no como objetos

Alternativa descartada: `[{"type": "refund", "detail": "...", "requires_human": true}]`.

| Criterio | `list[str]` | objetos |
|---|---|---|
| Parseo por el modelo | simple | más propenso a errores |
| Scoring en evals | Jaccard/recall directo | requiere matching por campo |
| Utilidad para el agente | alta si el texto es concreto | mayor, pero rígida |
| Riesgo de romper el contrato | bajo | alto |

Se eligió `list[str]` y se compensa con un **vocabulario sugerido en el prompt** (Capítulo 5). Si en el Módulo 2 se necesita estructura, se versiona el contrato.

### 4.2 `confidence` estricta, sin clamp

Si el modelo devuelve `1.2`, **falla**. No lo recortamos a `1.0`.

Motivo: la confianza se va a evaluar con calibración (Brier score, Capítulo 7). Clampear un valor inválido falsearía la medición y ocultaría que el modelo no respeta el contrato. Mejor fallar y reintentar.

### 4.3 `extra="forbid"`

Cualquier clave fuera del contrato invalida la respuesta. Esto convierte una desviación del modelo en un error detectable, en lugar de un campo que viaja sin que nadie lo mire.

**Consecuencia para el Capítulo 5:** si el prompt de chain-of-thought devuelve un campo `reasoning`, el pipeline debe **removerlo antes de validar**. La decisión está registrada en el Apéndice A.

### 4.4 Normalizar antes de rechazar

El contrato es estricto en **forma**, tolerante en **ruido**:

- `" BILLING "` → `billing` (se normaliza);
- `"Facturación"` → **inválido** (no se traduce; eso lo debe resolver el prompt);
- `"  Verificar   pagos "` → `"Verificar pagos"` (se canoniza);
- `["a", "A", "a"]` → `["a"]` (se deduplica).

El límite es deliberado: se corrige formato, no semántica.

### 4.5 Truncar a 3 acciones

Si el modelo devuelve 4, se conservan las 3 primeras. No se reintenta por un exceso trivial.

Trade-off: se pierde información y se oculta un pequeño desvío. Se mitiga midiendo `retry_rate` y revisando la distribución de `len(actions)` en las evals.

## 5. El código, bloque por bloque

### 5.1 Cabecera y constantes (líneas 1–11)

```python
"""Contrato de salida del servicio de triage: {answer, confidence, category, actions}."""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_ANSWER_CHARS = 800
MAX_ACTIONS = 3
```

- **Línea 3** — `from __future__ import annotations`: las anotaciones se tratan como strings (PEP 563). Permite `list[str]` sin costo en runtime y evita problemas de referencias. Pydantic las resuelve igual.
- **Línea 6** — `StrEnum` (3.11+): los miembros **son** strings. `Category.BILLING == "billing"` es `True` y `json.dumps` no necesita conversión.
- **Línea 8** — solo lo necesario de Pydantic v2.
- **Líneas 10–11** — constantes de negocio. Se usan tanto en `Field` como en el validador: **una sola fuente de verdad**. Si mañana el límite cambia, cambia en un lugar.

`800` no es arbitrario: una respuesta de soporte debe caber en un email corto. Un límite alto invita al modelo a divagar.

### 5.2 `Category` (líneas 14–18)

```python
class Category(StrEnum):
    BILLING = "billing"
    TECHNICAL = "technical"
    ACCOUNT = "account"
    OTHER = "other"
```

- Hereda de `StrEnum`, no de `Enum`: el valor ya es `str`, así que `model_dump()` y el JSON Schema producen `"billing"` directamente.
- Estos cuatro valores **son** el contrato. Agregar uno cambia el JSON Schema y, por lo tanto, el prompt.
- No incluye sinónimos en español: la traducción es responsabilidad del prompt, no del esquema.

### 5.3 Configuración del modelo (líneas 21–26)

```python
class TriageResponse(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )
```

- **`extra="forbid"`** (23): rechaza claves desconocidas. Ver §4.3.
- **`frozen=True`** (24): prohíbe reasignar atributos (`r.answer = "..."` lanza error) y hace la instancia hashable.
  **Matiz:** no congela en profundidad. La lista `actions` sigue siendo mutable:
  `r.actions.append("x")` funciona. Es inmutabilidad de atributos, no de contenido.
- **`str_strip_whitespace=True`** (25): recorta espacios al inicio y fin de **todos** los `str` antes de validar. Aplica a `answer` y a cada item de `actions`.

### 5.4 Campos (líneas 28–49)

```python
answer: str = Field(
    ...,
    min_length=1,
    max_length=MAX_ANSWER_CHARS,
    description="Respuesta sugerida para el cliente, en español, concreta y accionable.",
)
```

- `Field(...)` con `Ellipsis` = **obligatorio**. Usar `Field` en lugar de solo la anotación permite declarar restricciones y descripción.
- En `str`, `min_length`/`max_length` son **caracteres** → `minLength`/`maxLength` en el schema.
- `description` **no es un comentario**: viaja al JSON Schema y de ahí al prompt. Es lo que el LLM lee sobre cada campo.

```python
confidence: float = Field(
    ...,
    ge=0.0,
    le=1.0,
    description="Confianza calibrada en la clasificación y en la respuesta (0 a 1).",
)
```

- `ge`/`le` = greater/less or equal → `minimum`/`maximum`.
- Validación estricta (§4.2).

```python
category: Category = Field(..., description="Categoría principal del ticket.")
```

- Usa el enum: Pydantic valida por valor y genera un `$ref` a `$defs.Category` en el schema.

```python
actions: list[str] = Field(
    ...,
    min_length=1,
    max_length=MAX_ACTIONS,
    description="Acciones concretas para el agente humano (1 a 3).",
)
```

- En una lista, `min_length`/`max_length` son **cantidad de items** (`minItems`/`maxItems`), no longitud de cada string.
- Cada acción no tiene tope de caracteres: se controla por prompt. Si hiciera falta, se cambiaría a `list[Annotated[str, Field(max_length=...)]}`.

### 5.5 Validador de `answer` (líneas 51–56)

```python
@field_validator("answer")
@classmethod
def _answer_has_content(cls, value: str) -> str:
    if not value.strip():
        raise ValueError("answer no puede estar vacio ni contener solo espacios")
    return value.strip()
```

- Sin `mode`, corre **después** de la coerción y de `str_strip_whitespace`: recibe un `str` ya limpio. Si el tipo fuera inválido, Pydantic habría fallado antes y este código no se ejecutaría.
- `@classmethod` es obligatorio en Pydantic v2.
- `if not value.strip()` detecta `""` y `"   "`. Es **parcialmente redundante** (con `str_strip_whitespace`, `"   "` ya queda `""` y `min_length=1` falla), pero produce un mensaje explícito y no depende de un detalle de configuración.
- `raise ValueError(...)` → Pydantic lo envuelve en `ValidationError`. Ese texto es el que el retry reenvía al modelo en el Capítulo 3.
- `return value.strip()`: defensa en profundidad.

### 5.6 Validador de `category` (líneas 58–63)

```python
@field_validator("category", mode="before")
@classmethod
def _normalize_category(cls, value: object) -> object:
    if isinstance(value, str):
        return value.strip().lower()
    return value
```

- **`mode="before"`**: corre **antes** de la conversión al enum y recibe el valor crudo, por eso el tipo es `object`.
- Sin esto, `" BILLING "` fallaría por espacios y mayúsculas. Se normalizan variaciones **de formato**, no de idioma.
- Si no es `str` (`null`, número), se devuelve intacto para que Pydantic emita **su** error de tipo, que es más preciso.

### 5.7 Validador de `actions` (líneas 65–83)

```python
@field_validator("actions", mode="before")
@classmethod
def _normalize_actions(cls, value: object) -> object:
    if not isinstance(value, list):
        return value
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        text = " ".join(item.split())
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned[:MAX_ACTIONS]
```

Línea por línea:

- `if not isinstance(value, list): return value` — si el modelo devuelve un string (`"hacer X; hacer Y"`), **no lo partimos**. Lo devolvemos y Pydantic falla. Splitear comas generaría acciones falsas y silenciosas.
- `" ".join(item.split())` — `split()` sin argumentos colapsa cualquier whitespace (espacios, tabs, saltos). `join(" ")` lo rearma canónico: `"  Verificar\n pagos "` → `"Verificar pagos"`. Normalizar antes de deduplicar evita duplicados que difieren solo en espacios.
- `if not isinstance(item, str): continue` — descarta items no-string. Es **salvataje tolerante**: se rescatan 2 acciones buenas de 3 antes que descartar todo. Si todas son inválidas, `cleaned` queda vacío → falla `min_length=1` → retry. Trade-off: puede ocultar un error; se mitiga midiendo `retry_rate`.
- `text.casefold()` — más agresivo que `lower()` para deduplicar (maneja Unicode, p. ej. `ß` vs `ss`). Se compara con la clave normalizada pero **se guarda el texto original**, preservando la capitalización.
- `cleaned[:MAX_ACTIONS]` — trunca a 3 (§4.5). El orden de aparición se preserva.
- Como la lista se trunca antes de la validación, `max_length=3` nunca puede fallar; el que sí puede fallar es `min_length=1`.

### 5.8 Serialización (líneas 85–93)

```python
def to_dict(self) -> dict:
    return self.model_dump(mode="json")
```

- `mode="json"` convierte el enum a `"billing"` y garantiza tipos JSON-native (nada de `Category`, `datetime` ni `Decimal`). Es lo que se escribe en `metrics.jsonl`.

```python
def to_json(self) -> str:
    return json.dumps(self.to_dict(), ensure_ascii=True, separators=(",", ":"))
```

- `ensure_ascii=True`: `"Facturación"` → `"Facturaci\u00f3n"`. Evita `UnicodeEncodeError` en consolas Windows con cp1252. Quien parsee el JSON recupera el texto original.
- `separators=(",", ":")`: sin espacios → una línea compacta. Es lo que permite "un JSON por invocación" y líneas limpias en JSONL.

```python
@classmethod
def json_contract(cls, indent: int | None = None) -> str:
    return json.dumps(cls.model_json_schema(), ensure_ascii=False, indent=indent)
```

- `model_json_schema()` genera JSON Schema (draft 2020-12) con `required`, `$defs` y `additionalProperties: false`.
- `ensure_ascii=False`: acá sí queremos UTF-8 legible, porque este string se inyecta en el prompt; el modelo debe leer "español", no `espa\u00f1ol`.
- `indent=None` da una línea; `indent=2` da algo revisable a ojo.

### 5.9 Lo que deliberadamente no tiene

- **Sin `schema_version`**: el contrato es literalmente `{answer, confidence, category, actions}`; un campo extra lo violaría.
- **Sin `ActionItem` estructurado**: decisión de §4.1.
- **Sin parsing de texto**: extraer JSON de un bloque markdown o de un mensaje del LLM va en `validation.py`/`pipeline.py` (Capítulo 3), no acá. Este módulo solo define la **forma final**.

## 6. JSON Schema generado

`TriageResponse.json_contract(indent=2)` produce (resumido):

```json
{
  "$defs": {
    "Category": {
      "enum": ["billing", "technical", "account", "other"],
      "title": "Category",
      "type": "string"
    }
  },
  "additionalProperties": false,
  "properties": {
    "answer":     { "maxLength": 800, "minLength": 1, "type": "string" },
    "confidence": { "maximum": 1.0, "minimum": 0.0, "type": "number" },
    "category":   { "$ref": "#/$defs/Category" },
    "actions":    { "items": { "type": "string" }, "maxItems": 3, "minItems": 1, "type": "array" }
  },
  "required": ["answer", "confidence", "category", "actions"],
  "type": "object"
}
```

Este es el bloque que el prompt le muestra al modelo. Por eso las `description` importan y por eso `additionalProperties: false` aparece explícito.

## 7. Tests

Archivo: `tests/test_schemas.py`. Script con `assert`, sin pytest.

```bash
.venv/bin/python tests/test_schemas.py
```

Salida:

```
ok   test_actions_are_capped_at_three
ok   test_actions_are_cleaned_and_deduplicated
ok   test_category_is_normalized
ok   test_json_is_ascii_safe_and_matches_contract
ok   test_rejects_blank_answer
ok   test_rejects_empty_actions
ok   test_rejects_extra_fields
ok   test_rejects_out_of_range_confidence
ok   test_rejects_unknown_category
ok   test_valid_payload

10/10 tests pasaron
```

| Test | Qué garantiza |
|---|---|
| `test_valid_payload` | el caso feliz valida y el enum queda como `Category` |
| `test_category_is_normalized` | `"  BILLING "` → `billing` |
| `test_actions_are_cleaned_and_deduplicated` | colapsa espacios, descarta vacíos, deduplica case-insensitive |
| `test_actions_are_capped_at_three` | 4 acciones → 3 |
| `test_rejects_out_of_range_confidence` | `-0.1` y `1.1` fallan |
| `test_rejects_unknown_category` | `"ventas"` falla |
| `test_rejects_extra_fields` | `reasoning` extra falla |
| `test_rejects_blank_answer` | `"   "` falla |
| `test_rejects_empty_actions` | `["", "  "]` falla tras limpiar |
| `test_json_is_ascii_safe_and_matches_contract` | la salida es ASCII y tiene exactamente 4 claves |

El runner de tests es intencionalmente simple: recorre las funciones `test_*`, captura `AssertionError` e imprime un resumen. No es el runner de evals (ese llega en el Capítulo 7 y mide el sistema, no el esquema).

## 8. Consecuencias para las próximas fases

1. **Retry con feedback.** `ValidationError` provee el mensaje que se reenvía al modelo. El pipeline debe capturarlo y construir el turno de reparación (Capítulo 3).
2. **Stripping de campos internos.** Con `extra="forbid"`, cualquier `reasoning` o `explanation` debe eliminarse **antes** de validar (Capítulo 5).
3. **Fallback.** Si tras los reintentos no hay respuesta válida, se devuelve un objeto construido a mano (`category=other`, `confidence=0.0`, `actions=["escalar_a_humano"]`) y se registra `success=false`. El contrato nunca se rompe hacia afuera.
4. **Scoring.** `actions` como strings permite medir Jaccard/recall contra un set esperado sin lógica de matching compleja (Capítulo 7).
5. **Métricas.** `to_dict()` es la fuente del campo `category` y `confidence` que se registra en `metrics.jsonl`.

## 9. Errores comunes

| Síntoma | Causa | Fix |
|---|---|---|
| `ValidationError` por `reasoning` | prompt CoT devuelve campo extra | removerlo antes de validar |
| `confidence` rechazada con `1.0` | llega como string `"1.0"` | Pydantic lax lo coacciona; si no, el prompt debe pedir número |
| `actions` rechazadas | el modelo devolvió un string | el prompt debe pedir array; no splitear en el validador |
| `answer` vacío | el modelo devolvió solo espacios | retry con feedback |
| El JSON de salida tiene tildes escapadas | `ensure_ascii=True` | es correcto para CLI; usar `model_dump()` si se necesita texto plano |
| `r.actions.append(...)` no falla | `frozen` no es profundo | no mutar listas; si importa, usar `tuple` |

## 10. Checklist de cierre

- [x] `Category` con los 4 valores del contrato
- [x] `TriageResponse` con los 4 campos obligatorios
- [x] `extra="forbid"`, `frozen=True`, strip de whitespace
- [x] normalización de `category` y `actions`
- [x] truncado a 3 acciones
- [x] `confidence` estricta 0–1
- [x] serialización ASCII y JSON Schema exportable
- [x] 10/10 tests pasando

---

**Anterior:** [Capítulo 1 — Configuración](01-fase-0-configuracion.md) · **Siguiente:** [Capítulo 3 — CLI y mock](03-fase-2-cli-y-mock.md)
