# Capítulo 11 — Extras (Fase 10)

> La consigna pide al menos un extra entre FastAPI, caché con hash MD5, LLM-as-judge en
> runtime o comparativa de modelos. Acá van dos: la caché MD5, nueva, y la comparativa de
> modelos, armada con datos ya medidos.

---

## 1. Objetivo

- **Caché MD5:** no pagar dos veces por la misma consulta, sin servir respuestas viejas cuando cambia el modelo, el prompt o los guardrails.
- **Comparativa de modelos:** reunir en un solo lugar calidad, costo, latencia y seguridad de los tres modelos probados.
- FastAPI y LLM-as-judge quedan fuera: ver §5.

## 2. Resultado

```
src/cache.py                 # ResponseCache, cache_key (MD5), normalize_query
tests/test_cache.py          # 9 tests
data/cache/<md5>.json        # una entrada por respuesta (gitignored)
```

La CLI usa la caché por defecto (`--no-cache` para saltearla). Configuración en `.env`: `CACHE_ENABLED`, `CACHE_DIR`, `CACHE_TTL_S` (7 días por defecto).

## 3. Caché MD5

### 3.1 La clave

```python
material = {
    "query": normalize_query(query),      # NFKC, espacios colapsados, casefold
    "provider": ..., "model": model.id,
    "temperature": ..., "effort": ..., "max_tokens": ...,
    "prompt": prompt_fingerprint(prompt), # MD5 del prompt renderizado completo
    "guardrails": guardrails.sha256,      # reglas de config/guardrails.yaml
}
key = md5(json.dumps(material, sort_keys=True))
```

**Todo lo que puede cambiar la respuesta está en la clave.** Si se edita el prompt, se cambia de modelo o se tocan las reglas de los guardrails, la clave cambia y las entradas viejas simplemente no se usan; no hace falta invalidarlas a mano. Un test verifica que cada componente cambia la clave.

**La consulta se normaliza poco a propósito:** espacios, mayúsculas y formas Unicode equivalentes. "Me cobraron dos veces" y "  me COBRARON dos veces" comparten entrada; "me cobraron tres veces" no. Normalizar más (sinónimos, orden de palabras) aumentaría los aciertos a costa de devolver la respuesta de otra pregunta.

**MD5 no es seguridad acá.** Es una clave rápida y estable, como pide la consigna. Que alguien fabrique una colisión no sirve para nada: solo obtendría la respuesta de otra consulta con el mismo prompt, que no es un secreto.

### 3.2 Qué se guarda y qué no

| | ¿Se cachea? | Por qué |
|---|---|---|
| respuesta válida del modelo | sí, **después** del guardrail de salida | se sirve exactamente lo que se habría servido |
| fallback (el modelo falló) | no | sería guardar un error |
| consulta bloqueada en la entrada | no | ya no cuesta nada |
| la consulta en texto plano | **no** | privacidad: el nombre del archivo es el hash |

Cada entrada guarda la respuesta, la fecha, el costo y la latencia originales y los flags del guardrail de salida. En un acierto, la línea de `data/metrics.jsonl` registra `cache: "hit"`, costo 0 y `cache_saved_usd` con lo que habría costado: el ahorro queda auditable.

### 3.3 Dónde va en el pipeline

```
consulta ─▶ guardrail de entrada ─▶ ¿bloqueada? ─sí─▶ respuesta segura
                                         │ no
                                         ▼
                                 ¿está en la caché? ─sí─▶ respuesta cacheada (0 ms de modelo, USD 0)
                                         │ no
                                         ▼
                        prompt ─▶ modelo ─▶ Pydantic ─▶ guardrail de salida ─▶ se guarda
```

La entrada se revisa **antes** de la caché: un ataque bloqueado nunca toca el disco, y las métricas siempre registran los flags de entrada.

### 3.4 Robustez

- Escritura atómica (archivo temporal + `os.replace`): un corte no deja entradas a medio escribir.
- Entrada corrupta, vencida o que ya no valida contra el contrato: se trata como un fallo de caché y se vuelve a llamar al modelo.
- Disco no escribible: se registra un aviso y el request responde igual. La caché es una optimización, nunca un punto de falla.

### 3.5 El runner de evals no la usa

Las evals miden el modelo. Con caché, la segunda de 3 repeticiones mediría la caché: la varianza sería 0 y la latencia, 1 ms. `evals/runner.py` y `evals/adversarial.py` construyen el pipeline sin caché.

### 3.6 Verificación con el modelo real

```bash
python -m src.main --provider anthropic --model haiku-5-5 \
  --query "Desde ayer no puedo descargar la factura de octubre, me da error"
python -m src.main --provider anthropic --model haiku-5-5 \
  --query "  desde ayer NO puedo descargar la factura de octubre,   me da error"
```

| | `cache` | intentos | tokens | latencia | costo |
|---|---|---|---|---|---|
| 1.ª consulta | miss | 1 | 3.926 | 3,67 s | USD 0.00054 |
| 2.ª consulta (otro formato) | **hit** | 0 | 0 | **0,8 ms** | **USD 0** (`cache_saved_usd` 0.00054) |

**Lo que no se puede medir acá:** la tasa de aciertos depende de cuánto se repiten las consultas en el tráfico real. El dataset no tiene repeticiones, por construcción. En soporte, los aciertos vienen sobre todo de clientes que reenvían el mismo mensaje y de preguntas frecuentes con texto casi idéntico; consultas con datos propios (montos, fechas, nombres) rara vez se repiten.

## 4. Comparativa de modelos

Todos los números salen de corridas ya guardadas en `evals/results/`; esta sección no hizo llamadas nuevas. Calidad sobre los 32 casos de dev, con el mismo criterio de la Fase 7.

### 4.1 Con el prompt elegido (v4)

| | Haiku 5.5 | gpt-4.1-mini | Haiku 4.5 |
|---|---|---|---|
| macro-F1 | 1.000 | 1.000 | 1.000 |
| action score | 0.953 | 0.953 | 0.917 ¹ |
| Brier (menor es mejor) | 0.049 | **0.020** | 0.031 |
| USD por request | **0.00050** | 0.00105 | 0.00372 |
| **USD por 1.000 tickets** | **0.50** | 1.05 | 3.72 |
| latencia p50 / p95 | 1,8 s / 2,6 s | **1,4 s / 1,8 s** | 2,6 s / 3,2 s |
| defensa adversarial (sistema completo) | **100 %** | 90 % (`adv-08`) | no medida ² |
| corridas | 3 | 1 ³ | 3 |

¹ Ronda 1 de la Fase 7, con la acción esperada anterior de `oth-01`; el macro-F1 es comparable porque las etiquetas de dev no cambiaron.
² Excluido por costo desde la Fase 7 (ADR-029).
³ Limitación conocida: OpenAI con 1 corrida y Anthropic con 3 (Capítulo 8).

### 4.2 Sin ayuda del prompt (v1, zero-shot)

| | Haiku 4.5 | Haiku 5.5 | gpt-4.1-mini |
|---|---|---|---|
| macro-F1 | **0.969** | 0.908 | 0.908 |
| USD por request | 0.00170 | **0.00022** | 0.00037 |

### 4.3 Lectura

- **Con un buen prompt, los tres modelos clasifican igual de bien.** Las diferencias aparecen en lo demás: costo, latencia, seguridad y calibración.
- **Haiku 4.5 es el que mejor clasifica solo** (v1), pero con v4 esa ventaja desaparece y cuesta 7 veces más que Haiku 5.5. El prompt hizo el trabajo que el modelo caro hacía solo.
- **Haiku 5.5 es el más barato y el único que resistió los 10 ataques**, incluido el desvío de la clasificación que `gpt-4.1-mini` obedece siempre.
- **`gpt-4.1-mini` es el más rápido y el mejor calibrado** (Brier 0.020). Si la latencia importara más que el costo, o si `confidence` se usara para escalar, sería un candidato serio; pero el criterio fijado de antemano (ADR-022) decide por costo, y la seguridad confirma la elección.
- **Costo a escala:** para 100.000 tickets al mes, Haiku 5.5 cuesta unos USD 50; `gpt-4.1-mini`, USD 105; Haiku 4.5, USD 372. Con la caché, los reenvíos y las preguntas repetidas salen gratis.

## 5. Lo que no se hizo

- **FastAPI:** la consigna pide una CLI, y la CLI ya es el contrato. Un endpoint agrega servidor, puertos y dependencias para el corrector sin agregar evidencia nueva. Queda como trabajo futuro: el pipeline ya es una clase sin estado global, así que un `POST /triage` es una función de pocas líneas.
- **LLM-as-judge en runtime:** duplica costo y latencia de cada request, y el juez es otro modelo a evaluar y a proteger de inyecciones. Las evals ya usan criterios deterministas (ADR-023).

## 6. Decisiones y trade-offs

| Decisión | ADR | Trade-off |
|---|---|---|
| Clave MD5 con todo lo que cambia la respuesta | 033 | menos aciertos tras cada cambio de prompt o reglas vs. nunca servir una respuesta vieja |
| Normalización mínima de la consulta | 033 | menos aciertos vs. no devolver la respuesta de otra pregunta |
| Cachear después del guardrail de salida; no cachear fallback ni bloqueos | 033 | — |
| Sin caché en las evals | 033 | — |
| Comparativa con datos existentes | — | combina rondas distintas (aclarado en las notas) vs. no gastar más |

## 7. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `cache=hit` con una respuesta que ya no corresponde | se cambió algo que no está en la clave (por ejemplo, la lógica del pipeline) | `--no-cache` o borrar `data/cache/` |
| las evals dan varianza 0 | alguien conectó la caché al runner | el runner no debe usarla |

## 8. Checklist de cierre

- [x] caché MD5 con invalidación por clave, TTL, escritura atómica y tolerancia a fallos
- [x] métricas de acierto y ahorro en `data/metrics.jsonl`
- [x] verificada con el modelo real: 3,67 s → 0,8 ms, costo 0
- [x] 9 tests
- [x] comparativa de modelos: calidad, costo, latencia, calibración y seguridad

---

**Anterior:** [Capítulo 10 — Suite adversarial](10-fase-9-adversarial.md) · **Siguiente:** Capítulo 12 — Cierre (Fase 11, pendiente)
