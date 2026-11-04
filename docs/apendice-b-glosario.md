# Apéndice B — Glosario

> Términos que aparecen en el manual, en el orden en que conviene entenderlos.

---

## LLM y prompting

**LLM (Large Language Model).** Modelo entrenado para predecir el siguiente token. Se consume por API, no se entrena en este proyecto.

**Token.** Unidad mínima de texto que procesa el modelo. No equivale a una palabra: en español suele ser 1 palabra ≈ 1–2 tokens. Todo costo se calcula por tokens.

**Prompt.** Entrada que recibe el modelo. Se divide en **system** (rol e instrucciones persistentes) y **user** (la consulta).

**System prompt.** Instrucciones de mayor jerarquía. Es también el objetivo típico de un ataque de exfiltración.

**Context engineering.** Diseño deliberado de todo lo que entra en la ventana de contexto: instrucciones, ejemplos, taxonomía, formato de salida y reglas de seguridad. El prompting es una parte.

**Zero-shot.** Pedir la tarea sin ejemplos.

**Few-shot.** Incluir ejemplos resueltos en el prompt para fijar formato y criterio.

**Chain-of-thought (CoT).** Pedir al modelo que razone paso a paso antes de responder. Mejora tareas complejas; agrega tokens y latencia, y puede filtrar el razonamiento si no se aísla.

**Structured output.** Forzar que la salida respete un esquema (JSON Schema). Reduce el parseo frágil.

**Temperatura.** Parámetro de aleatoriedad. `0.0` ≈ determinista; valores altos aumentan variedad y riesgo.

## Contrato y validación

**Contrato.** Forma externa garantizada del servicio: `{answer, confidence, category, actions}`. Si cambia, rompe a los consumidores.

**Pydantic.** Librería de validación de datos en Python. Convierte diccionarios en objetos tipados y lanza `ValidationError` cuando no cumplen.

**JSON Schema.** Especificación que describe la forma de un JSON (tipos, campos requeridos, rangos). Se genera desde Pydantic y se inyecta en el prompt.

**Validador `before` / `after`.** En Pydantic v2, `mode="before"` corre antes de la coerción de tipos (sirve para normalizar); el modo por defecto corre después (recibe el valor ya tipado).

**`extra="forbid"`.** Configuración que rechaza claves no declaradas. Convierte una desviación del modelo en un error detectable.

**Retry.** Segundo (o tercer) intento cuando la respuesta no parsea o no valida. El reintento útil incluye el error como feedback.

**Fallback.** Respuesta segura construida localmente cuando todos los intentos fallan. Mantiene el contrato hacia afuera.

## Evaluación

**Dataset de evaluación.** Conjunto de casos con etiqueta esperada. Acá: ≥30 casos (objetivo: 40), balanceados por categoría, más casos borde.

**Ground truth.** La etiqueta correcta de un caso, definida por un humano con una guía de etiquetado.

**Accuracy.** Proporción de aciertos. Engañosa si las clases están desbalanceadas.

**Macro-F1.** Promedio del F1 por clase, sin ponderar por frecuencia. Castiga que una clase minoritaria vaya mal. Es la métrica principal de clasificación acá.

**Matriz de confusión.** Tabla de esperado vs predicho. Muestra **qué** se confunde con qué (p. ej. `billing` → `technical`), no solo cuántos aciertos hay.

**Jaccard / recall de acciones.** Similitud entre el set de acciones esperadas y el devuelto. Mide si las acciones útiles aparecen, no el texto exacto.

**Calibración.** Grado en que `confidence` coincide con la tasa real de acierto. Un modelo que dice 0.9 y acierta el 60% está mal calibrado.

**Brier score.** Error cuadrático medio entre la confianza declarada y el resultado (0/1). Más bajo es mejor.

**Retry rate.** Proporción de requests que necesitaron reintento. Mide fragilidad del formato, no calidad semántica.

**LLM-as-judge.** Usar un modelo para puntuar respuestas abiertas. Útil para calidad de `answer`; se valida contra una muestra humana.

## Seguridad

**Prompt injection.** Instrucción maliciosa embebida en los datos del usuario que intenta cambiar el comportamiento del sistema ("ignorá tus instrucciones...").

**Jailbreak.** Intento de saltar las políticas del modelo mediante role-play, codificación o pretextos.

**Exfiltración de system prompt.** Ataque que busca que el modelo revele sus instrucciones internas.

**Guardrail.** Control que inspecciona y bloquea/modifica entrada o salida. Se aplica en capas: uno solo es evadible.

**Moderación.** Clasificación de contenido dañino (violencia, datos personales, etc.) antes o después del LLM.

**Falso positivo.** Caso legítimo bloqueado por un guardrail. Se mide sobre el dataset benigno: un guardrail que bloquea todo no sirve.

## Operación y métricas

**Latencia p50 / p95.** Percentiles de tiempo de respuesta. El promedio oculta la cola; p95 refleja la experiencia de los usuarios lentos.

**Costo estimado.** `tokens_prompt × precio_input + tokens_completion × precio_output`, con la tabla de precios versionada. Debe ser reproducible por un tercero.

**JSONL.** Archivo con un JSON por línea. Append-only: se agrega al final, nunca se reescribe. Es el formato de `metrics.jsonl` y del dataset.

**Rate limit.** Límite de requests por minuto que impone el proveedor. Se maneja con backoff exponencial y jitter.

**Backoff exponencial.** Esperar 1s, 2s, 4s... entre reintentos. El **jitter** agrega aleatoriedad para evitar que varios clientes reintenten a la vez.

**Idempotencia.** Propiedad por la que repetir una operación no cambia el resultado. Relevante para reintentos.

## Entorno

**Intérprete.** El binario de Python que ejecuta el código. Puede haber varios instalados.

**`venv` / entorno virtual.** Carpeta con un intérprete enlazado y su propio `site-packages/`. Aísla dependencias por proyecto. No es una VM ni un contenedor.

**`uv`.** Gestor de Python y paquetes escrito en Rust. Crea entornos, instala, resuelve y pinnea versiones.

**Wheel.** Paquete binario precompilado para una combinación de plataforma y versión de Python (`cp314`, `arm64`). Evita compilar.

**Pin.** Fijar una versión exacta (`==`) para que la instalación sea reproducible.

**Free-threaded (`3.14t`).** Build de Python sin GIL. No se usa acá: el proyecto es I/O-bound y faltan wheels.

**CLI.** Interfaz de línea de comandos. Es el punto de entrada del servicio en este módulo.

---

**Volver al índice:** [README del manual](README.md)
