# Guía de etiquetado — dataset de triage Nubbix

Esta guía define la **etiqueta correcta** (ground truth) de cada caso de `evals/dataset.jsonl`.
La aplica una persona, no un modelo. Si un caso no se puede resolver con estas reglas,
se marca **en disputa** con una nota: no se fuerza una etiqueta.

## 1. Pregunta guía

> ¿Qué tiene que resolver el equipo de soporte para que este cliente quede conforme?

Se etiqueta por **la necesidad**, no por las palabras. Un ticket que dice "factura" puede
ser `technical` (la emisión falla) o `account` (le falta un permiso para verla).

## 2. Categorías

| Categoría | Incluye | No incluye |
|---|---|---|
| `billing` | dinero de un cliente que **ya paga**: cobros duplicados o incorrectos, reintegros, facturas (emisión, datos fiscales, descarga), medios de pago, aumentos, renovación | precios consultados antes de contratar (`other`); baja del servicio y datos de la cuenta, incluido el email de facturas (`account`) |
| `technical` | algo del producto no funciona: errores, caídas, lentitud, integraciones, importaciones, notificaciones, reportes con datos incorrectos, API | contraseña, 2FA o permisos (`account`) |
| `account` | identidad, acceso y datos de la cuenta: usuarios, roles y permisos, contraseña, 2FA, bloqueos, emails registrados (de acceso o de facturas), **baja de la suscripción y eliminación de la cuenta** | — |
| `other` | todo lo demás: pre-venta, planes y precios antes de contratar, demos, sugerencias, partners, documentación de cumplimiento, consultas fuera de alcance o sin información | — |

## 3. Reglas de desempate

1. **Dinero primero:** si un problema técnico causó un cobro incorrecto o el cliente pide compensación, `billing`.
2. **"No puedo entrar":** error del sistema o sitio caído → `technical`; contraseña, código o permisos → `account`.
3. **Finalización del servicio:** dar de baja la suscripción o eliminar la cuenta → `account`. No es un error de facturación sino el fin del servicio. *(Decisión de la revisión humana, 2026-11-04; reemplaza la regla del borrador, que separaba la baja como billing.)*
4. **Email:** cambiar un email registrado en la cuenta, sea de acceso o destinatario de facturas → `account` (es información de la cuenta); notificaciones que no llegan → `technical`. *(Decisión de la revisión humana, 2026-11-04.)*
5. **Precios:** cliente actual que reclama lo que paga → `billing`; alguien que pregunta cuánto cuesta → `other`.
6. **Instrucciones inyectadas:** se ignoran para etiquetar. La etiqueta es la del pedido legítimo; si no hay pedido legítimo, `other`.
7. **Idioma:** se etiqueta igual sin importar el idioma del ticket.

## 4. Campos que revisa la persona

| Campo | Qué se valida |
|---|---|
| `expected_category` | la etiqueta, según esta guía |
| `difficulty` | `easy` (una lectura alcanza), `medium` (requiere una regla de §3), `hard` (dos categorías plausibles o ruido que distrae) |
| `expected_actions` | cada *intent* es algo que un buen agente haría; las `keywords` (minúsculas, sin tildes) detectan ese intent en la respuesta del modelo. Basta una keyword |
| `answer_keywords` | términos que una buena respuesta al cliente debería mencionar. Puede estar vacío |

`proposed_category` es el borrador original y **no se edita**: sirve para medir cuánto
cambió la revisión humana (tasa de acuerdo).

## 5. Estados

- `draft`: propuesto, sin revisar. **El runner no lo usa.**
- `validated`: una persona confirmó o corrigió la etiqueta (`validated_by` obligatorio).
- `disputed`: la persona no está segura (`review_note` obligatoria). No se usa hasta resolverse.

## 6. Cómo revisar

```bash
.venv/bin/python evals/review_labels.py          # interactivo, en una terminal
.venv/bin/python evals/validate_dataset.py --strict
```

Para corregir acciones o keywords, editá `evals/dataset.jsonl` a mano y volvé a correr el validador.
