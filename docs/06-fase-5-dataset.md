# Capítulo 6 — Dataset de evaluación (Fase 5)

> 40 casos con etiqueta esperada, divididos en dev y holdout, con una guía de etiquetado
> y una revisión humana caso por caso. El borrador lo propone el asistente; la etiqueta
> correcta la decide una persona.

---

## 1. Objetivo

Construir la vara con la que se van a medir los prompts y los modelos en las fases 6 y 7:

- **≥ 30 casos** etiquetados (la consigna); acá, 40;
- balance entre las 4 categorías y casos borde que pongan a prueba las reglas;
- **split dev / holdout** para no sobreajustar la elección al mismo set con el que se itera;
- **ground truth humano**: ningún caso entra a una eval sin que una persona lo valide.

## 2. Resultado

```
evals/
├── dataset.jsonl            # 40 casos
├── guia-de-etiquetado.md    # criterios para decidir la etiqueta
├── dataset.py               # carga, validación, leakage, resumen
├── validate_dataset.py      # CLI: estructura, balance, duplicados, leakage
└── review_labels.py         # CLI interactiva de revisión humana
tests/test_dataset.py        # 21 tests
```

## 3. Composición

| Categoría | Casos regulares | Casos borde | Total | Holdout |
|---|---|---|---|---|
| billing | 8 | 3 | 11 | 2 |
| technical | 8 | 2 | 10 | 2 |
| account | 8 | 1 | 9 | 2 |
| other | 8 | 2 | 10 | 2 |
| **total** | 32 | 8 | **40** | **8** |

Dificultad: 17 `easy`, 16 `medium`, 7 `hard`. Los 8 casos borde (`edge-01` a `edge-08`) cubren:

| Caso | Qué prueba |
|---|---|
| edge-01 | ambigüedad billing/technical (compensación por una caída), en minúsculas y sin tildes |
| edge-02 | consulta fuera de alcance |
| edge-03 | typos, sin mayúsculas, signos repetidos |
| edge-04 | portugués |
| edge-05 | ticket largo con contexto irrelevante; habla de facturas, pero falla el producto |
| edge-06 | amenaza legal |
| edge-07 | instrucción inyectada dentro de un ticket legítimo |
| edge-08 | sin información ("Ayuda urgente!!!") |

Además, varios casos regulares están puestos para probar una regla de desempate: `tec-06` (reporte con facturas → technical), `acc-04` (permiso para ver facturación → account), `bil-08` (email de facturas → billing), `acc-08` (eliminar la cuenta → account) y `oth-08` (precio para 10 usuarios → other).

El holdout tiene 2 casos por categoría y una mezcla de dificultades. **No se usa para elegir**: solo confirma al ganador (ADR-022).

## 4. Formato de un caso

```json
{
  "id": "acc-04",
  "split": "dev",
  "input": "Mi contador entra pero no ve el módulo de facturación, ¿le falta algún permiso?",
  "expected_category": "account",
  "proposed_category": "account",
  "difficulty": "hard",
  "tags": ["permisos"],
  "rationale": "Menciona facturación, pero lo que necesita es un permiso: account (regla 1).",
  "expected_actions": [
    {"intent": "Revisar el rol y los permisos del usuario", "keywords": ["rol", "permiso", "perfil", "acceso"]},
    {"intent": "Asignar el permiso correspondiente", "keywords": ["asign", "otorg", "habilit", "agreg"]}
  ],
  "answer_keywords": ["permiso"],
  "label_status": "draft",
  "validated_by": null,
  "review_note": null
}
```

- `expected_category` es la etiqueta vigente; `proposed_category` es el borrador y no se edita. La diferencia entre las dos mide cuánto corrigió la revisión humana.
- `expected_actions` son **intents** con keywords (ADR-023). Una acción del modelo cumple un intent si contiene alguna de sus keywords, comparadas en minúsculas y sin tildes. El *action score* de un caso es la fracción de intents cumplidos.
- `rationale` explica la etiqueta con la regla de la guía que aplica. Es lo que la persona revisa.

## 5. La guía de etiquetado

`evals/guia-de-etiquetado.md` define la etiqueta correcta. Su pregunta central es *qué tiene que resolver soporte para que el cliente quede conforme*, y suma 7 reglas de desempate. La guía tiene **más reglas que los prompts** (por ejemplo, la del email de facturas). Es intencional: el dataset mide si el modelo infiere la regla, no si la copia del prompt.

## 6. Revisión humana

```bash
.venv/bin/python evals/review_labels.py
```

```
========================================================================================
[2/40]  bil-02  ·  split dev  ·  dificultad easy
----------------------------------------------------------------------------------------
  Necesito la factura de octubre en PDF y no la encuentro en el panel.
----------------------------------------------------------------------------------------
Categoría propuesta:  BILLING   (estado: draft)
Por qué: Pide un comprobante ya emitido.
Acciones esperadas:   Ubicar y enviar la factura

[Enter] aceptar · b/t/a/o cambiar · d disputa · s saltar · q salir >
```

- Cada decisión se guarda **al instante** y con escritura atómica: se puede cortar con `q` o Ctrl+C y retomar después.
- Cambiar la categoría deja una nota automática, *"revisar expected_actions"*, porque las acciones se redactaron para la categoría anterior.
- `--all` vuelve a revisar todo; `--id acc-04` revisa un caso puntual.
- Sin una terminal interactiva (por ejemplo, desde un pipe) se niega a correr con código 2. Se probó con una pseudo-terminal (pty) sobre una copia del dataset: aceptar, cambiar con nota, disputar y saltar quedaron guardados como se esperaba.

> **Actualización (Fase 7, ADR-029):** el dataset pasó a 46 casos (32 dev / 14 holdout) con 6 casos nuevos de holdout para las reglas de baja y email, validados por la misma persona, y `oth-01` cambió su acción esperada a "Derivar al equipo comercial". Lo que sigue describe el dataset de 40 casos de esta fase.

**Resultado de la revisión (2026-11-04):** 40/40 casos validados, con 95 % de acuerdo con el borrador. Se cambiaron dos casos de `billing` a `account`: `bil-03` (dar de baja la suscripción: *"es la finalización del servicio, la cuenta se daría de baja"*) y `bil-08` (email de facturas: *"deben actualizar la información de la cuenta"*). La guía de etiquetado se actualizó (reglas 3 y 4) para reflejar esas decisiones. **Consecuencia:** v2 y v3 ubican la cancelación en billing, así que contradicen la etiqueta humana en `bil-03`. Como los prompts son inmutables (ADR-020), se resuelve en la Fase 7.

## 7. Validación

```bash
.venv/bin/python evals/validate_dataset.py           # errores -> exit 1
.venv/bin/python evals/validate_dataset.py --strict  # además exige 0 draft y 0 disputed
```

Qué verifica:

- campos obligatorios, tipos, valores permitidos y ningún campo desconocido;
- `validated` exige `validated_by`; `disputed` exige `review_note`;
- keywords en minúsculas y sin tildes (si no, nunca coincidirían);
- 32 dev / 8 holdout; ≥ 8 casos y ≥ 1 en holdout por categoría;
- **casi duplicados** dentro del dataset (Jaccard de tokens ≥ 0.8);
- **leakage** contra los ejemplos few-shot de todos los prompts: idénticos o con Jaccard ≥ 0.5.

Resultado sobre el borrador: estructura OK, sin leakage. La similitud máxima entre un caso y un ejemplo de prompt es 0.25 (`bil-02` contra el ejemplo de la factura), y entre dos casos, 0.25.

## 8. Decisiones y trade-offs

| Decisión | ADR | Trade-off |
|---|---|---|
| Acciones como intents con keywords | 023 | puntaje reproducible y sin costo vs. no captura sinónimos que no estén en la lista |
| Borrador del asistente + validación humana obligatoria | 024 | rapidez vs. riesgo de anclaje en la propuesta |
| Dataset escrito a mano, no extraído de tickets reales | 025 | sin datos personales vs. menos realismo |

## 9. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `keywords con mayúsculas o tildes` | `"facturación"` en vez de `"facturacion"` | escribirlas normalizadas |
| `split holdout: 7 casos, se esperan 8` | se movió un caso de split | devolverlo o mover otro |
| `categoría account: 7 casos, mínimo 8` | la revisión reetiquetó casos | agregar un caso o rebalancear |
| `leakage: X se parece al ejemplo N de vK` | caso parecido a un ejemplo few-shot | reescribir el caso (los prompts no se editan, ADR-020) |
| `la revisión es interactiva` | se corrió sin terminal (por ejemplo, desde un pipe) | correrlo en una terminal |

## 10. Checklist de cierre

- [x] 40 casos, 32 dev / 8 holdout, ≥ 8 por categoría, 2 por categoría en holdout
- [x] 8 casos borde con tags
- [x] guía de etiquetado con reglas de desempate
- [x] validador con chequeo de leakage y duplicados
- [x] herramienta de revisión probada sobre una copia
- [x] 90/90 tests
- [x] **40/40 casos validados por una persona** (`validate_dataset.py --strict` en verde)

---

**Anterior:** [Capítulo 5 — Prompts versionados](05-fase-4-prompts.md) · **Siguiente:** [Capítulo 7 — Suite de evals](07-fase-6-evals.md)
