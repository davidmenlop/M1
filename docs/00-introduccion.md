# Capítulo 0 — Introducción

> Antes de escribir una línea de código: qué problema resolvemos, qué contrato
> exponemos y con qué criterios vamos a decir que funciona.

---

## 1. El problema

Nubbix es un SaaS de gestión para pymes de LATAM con **12.000 clientes**. Su mesa de soporte recibe **~400 tickets por día**. El **60%** son consultas repetitivas de cuatro tipos:

| Categoría | Ejemplos |
|---|---|
| Facturación (`billing`) | doble cobro, factura faltante, cambio de plan |
| Técnico (`technical`) | error 500, integración caída, sincronización rota |
| Cuenta (`account`) | agregar usuario, cambiar email de administrador |
| Otros (`other`) | descuentos, planes enterprise, consultas comerciales |

El equipo de nivel 1 está saturado: el **tiempo de primera respuesta llegó a 9 horas**. El costo no es solo operativo; es churn.

## 2. La misión

Automatizar el **primer nivel** de soporte con un servicio que:

1. recibe una consulta en **texto libre**;
2. la **clasifica** en una de cuatro categorías;
3. propone una **respuesta** al cliente;
4. sugiere **acciones** concretas para el agente humano;
5. lo hace con **calidad medible**, **costo controlado** y **resistencia a abuso**.

El servicio no reemplaza al agente: lo prepara. La salida está pensada para que un humano la revise y actúe.

## 3. El contrato

Todo el proyecto gira alrededor de esta forma, que **no cambia**:

```json
{
  "answer": "Revisamos el cargo duplicado y procesamos el reintegro en 48 h.",
  "confidence": 0.86,
  "category": "billing",
  "actions": ["Verificar pagos duplicados", "Solicitar reintegro"]
}
```

- `category ∈ {billing, technical, account, other}`
- `actions` es una lista de acciones sugeridas **para el agente humano**, no para el cliente.
- `confidence` es una estimación calibrada, y vamos a medir si efectivamente lo está.

Ese contrato es el que consumirá el sistema de tickets de Nubbix. Si cambia, se rompe la integración. Por eso se define **antes** de elegir proveedor, prompt o framework.

## 4. Qué se evalúa

La corrección es por rúbrica, con tres niveles (Excelente / Satisfactorio / Insuficiente). Aprueba con 70/100; **81+ supera lo esperado**.

| Categoría | Qué mira |
|---|---|
| Funcionalidad y contrato JSON | multi-proveedor, Pydantic, retry, casos borde |
| Suite de evals y dataset | ≥30 casos, runner automatizado, reporte claro |
| Context engineering y prompting | prompts versionados, comparativa empírica, elección con datos |
| Seguridad y guardrails | injection/jailbreak, suite adversarial |
| Observabilidad y métricas | JSONL con tokens, latencia y costo auditables |
| Repositorio, README y extras | modularidad, documentación ejecutable, al menos un extra |

**Estrategia del proyecto:** asegurar las seis categorías y llevar a "Excelente" las tres más baratas de demostrar con evidencia: **evals**, **context engineering** y **observabilidad**.

## 5. Principios de ingeniería

1. **Contrato primero.** El esquema de salida se fija y se valida antes de integrar un LLM.
2. **Prompts como código.** Versionados en YAML, comparados con datos, nunca hardcodeados.
3. **Evals sobre intuición.** Una técnica de prompting se elige porque ganó, no porque suena mejor.
4. **Seguridad en capas.** Un solo guardrail se evade; entrada y salida se complementan.
5. **Observabilidad auditable.** Cualquiera debe poder recalcular el costo de una request.
6. **Reproducibilidad.** Un clon limpio se instala y corre sin preguntar nada.
7. **Complejidad en el prompt y en las evals, no en la arquitectura.** El runner es un script, no un framework.

## 6. Arquitectura objetivo

```
consulta (texto libre)
        │
        ▼
┌──────────────────┐
│ guardrail entrada│──bloqueo──▶ respuesta segura (category=other, confidence=0)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐      ┌──────────────────────────────────┐
│ prompt YAML      │─────▶│ provider: openai | anthropic | mock │
└──────────────────┘      └───────────────┬──────────────────┘
                                          │ texto crudo
                                          ▼
                              ┌───────────────────────┐
                              │ parseo + Pydantic     │
                              └───────┬───────────────┘
                                      │ inválido
                                      ├──▶ retry con feedback del error (máx. 2)
                                      │ válido
                                      ▼
                              ┌───────────────────────┐
                              │ guardrail de salida   │
                              └───────┬───────────────┘
                                      ▼
                    JSON {answer, confidence, category, actions}
                                      │
                                      ▼
                    data/metrics.jsonl (tokens, latencia, costo)
```

Cada caja es un módulo con una responsabilidad. Ninguna conoce los detalles internos de otra: el proveedor no sabe de Pydantic, el guardrail no sabe de HTTP, la CLI no sabe de SDKs.

## 7. Requisitos previos

- Python **3.14** (gestionado por `uv`; ver Capítulo 1).
- `uv` instalado.
- Git.
- Opcional para la entrega: cuenta en OpenAI y Anthropic. El proyecto corre sin claves con `--provider mock`.

## 8. Cómo leer este manual

- Si venís a **instalar y correr**: Capítulo 1 → README final (Capítulo 12).
- Si venís a **entender el diseño**: Capítulos 2–4.
- Si venís a **defender decisiones**: Apéndice A y Capítulo 8.
- Si venís a **revisar seguridad**: Capítulos 9 y 10.

## 9. Alcance

Este manual documenta el **Módulo 1**. No incluye RAG, fine-tuning ni despliegue en producción: esas son fases posteriores del programa. Cuando una decisión se toma pensando en el Módulo 2, se indica explícitamente.

---

**Siguiente:** [Capítulo 1 — Configuración](01-fase-0-configuracion.md)
