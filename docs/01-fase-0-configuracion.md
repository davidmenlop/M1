# Capítulo 1 — Configuración (Fase 0)

> El objetivo de esta fase no es programar: es que **cualquiera pueda reproducir
> el entorno** y que el repositorio no se contamine desde el primer commit.

---

## 1. Objetivo

Dejar el proyecto listo para recibir código:

- un intérprete de Python **fijado y correcto**;
- un entorno virtual aislado;
- dependencias **pinneadas**;
- higiene de Git (secretos y artefactos fuera del repo);
- configuración declarativa fuera del código;
- un primer commit que refleje todo eso.

No se escribe lógica de negocio en esta fase. Se prepara el terreno.

## 2. Resultado

```
.
├── .env.example            # variables documentadas, sin credenciales
├── .gitattributes          # normalización de fin de línea (Windows/macOS/Linux)
├── .gitignore              # .venv, secretos, caché
├── .python-version         # 3.14
├── config/
│   └── providers.yaml      # modelos, parámetros y precios
├── data/
│   └── .gitkeep            # metrics.jsonl se versiona más adelante
├── evals/
│   ├── .gitkeep
│   └── results/            # resultados de evals (se versionan: son evidencia)
├── prompts/                # vacío hasta el Capítulo 5
├── requirements.txt        # 5 dependencias directas pinneadas
├── src/
│   ├── __init__.py
│   ├── guardrails/
│   ├── observability/
│   └── providers/
└── tests/                  # aparece en el Capítulo 2
```

## 3. Conceptos

### 3.1 Intérprete global, entorno virtual y `uv`

Un **intérprete** es el binario de Python. Un **entorno virtual** (`venv`) es una carpeta (`.venv/`) que contiene enlaces a un intérprete y su propio `site-packages/`. Sirve para que las dependencias de este proyecto no choquen con las de otro.

No es una máquina virtual ni un contenedor: no hay sistema operativo ni kernel. Es una convención de rutas que `pip` y `uv` respetan.

**`uv`** es un gestor escrito en Rust que reemplaza `pyenv`, `python -m venv`, `pip`, `pip-tools` y `pipx`:

```bash
uv python list --only-installed   # intérpretes disponibles
uv venv --python 3.14             # crea .venv con ese intérprete
uv pip install -r requirements.txt
uv pip compile ...                # resuelve y pinnea versiones
```

No es obligatorio: `python -m venv` + `pip` funcionan igual. En este proyecto se usa porque **elimina la clase de error más probable**: invocar el intérprete equivocado.

### 3.2 Por qué Python 3.14 (y no 3.15 ni 3.12)

La decisión se tomó con datos de PyPI, no por preferencia. Se verificó, para `macosx arm64`, la existencia de **wheels** (paquetes binarios precompilados) por versión de Python:

| Paquete | 3.12 | 3.13 | 3.14 | 3.15 |
|---|---|---|---|---|
| `pydantic-core` | ✅ | ✅ | ✅ | ✅ |
| `jiter` (dep. de `openai`) | ✅ | ✅ | ✅ | ✅ |
| `PyYAML` | ✅ | ✅ | ✅ | ❌ (compila desde fuente) |
| `httptools` | ✅ | ✅ | ✅ | ✅ |
| `uvloop` | ❌ | ❌ | ❌ | ❌ |

- **3.15** funciona, pero `PyYAML` todavía no publica wheel `cp315`: obliga a compilar, lo que exige toolchain y puede fallar en CI o en la máquina del corrector.
- **3.14** tiene cobertura completa: cero compilaciones.
- **3.12** también sirve, pero no aporta nada frente a 3.14 y es más viejo.

> **Lección transferible:** "la última versión" no es automáticamente la mejor opción. La compatibilidad del ecosistema se verifica, no se asume.

### 3.3 Free-threaded: no

Python 3.14/3.15 tienen una variante *free-threaded* (`3.14t`) que desactiva el GIL. **No se usa**: este proyecto es I/O-bound (espera respuestas de APIs), no necesita paralelismo de CPU, y varias extensiones C no publican wheels `cp314t`. Se usa el build estándar.

### 3.4 La trampa del PATH

En esta máquina:

```bash
python3 -V   # Python 3.9.6  (/usr/bin/python3)
pip3 -V      # pip del Python 3.15 (/Library/Frameworks/.../3.15/bin/pip3)
```

`python3` y `pip3` apuntan a **intérpretes distintos**. Un `pip3 install` habría instalado en 3.15 mientras `python3` ejecutaba 3.9 — el bug clásico de "funciona en mi máquina".

Por eso: **nunca** se invoca `python3`/`pip3` globales. Se usa `.venv/bin/python` (o el venv activado).

### 3.5 Wheels y `requires-python`

Un wheel es un binario por plataforma y versión de Python (`cp314`, `win_amd64`, `arm64`). Si no existe para tu combinación, `pip`/`uv` bajan al código fuente (`.tar.gz`) y compilan. Por eso la matriz de la sección 3.2 importa: define si el install es instantáneo o frágil.

## 4. Paso a paso

### 4.1 Crear la estructura

```bash
mkdir -p config prompts src/providers src/guardrails src/observability evals/results data
touch src/__init__.py src/providers/__init__.py src/guardrails/__init__.py src/observability/__init__.py
touch evals/.gitkeep evals/results/.gitkeep data/.gitkeep
```

Los `__init__.py` convierten `src/` y sus subcarpetas en paquetes importables (`from src.schemas import ...`). Los `.gitkeep` existen porque **Git no versiona carpetas vacías**: sin ellos, `evals/results/` no existiría en un clon limpio y el runner fallaría al escribir.

### 4.2 `.python-version`

```
3.14
```

Lo lee `uv` para elegir intérprete. Se pinnea **minor**, no patch: así otra máquina con 3.14.5 también funciona. No es un archivo que entienda `python` por sí solo; es una convención de `uv`/`pyenv`.

### 4.3 `.gitignore`

```gitignore
.venv/
venv/
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/

.env
.env.local

data/cache/

.DS_Store
Thumbs.db
.vscode/
.idea/
```

Línea por bloque:

- `.venv/`, `venv/`: entornos locales. Se recrean con un comando; no se versionan.
- `__pycache__/`, `*.py[cod]`: bytecode compilado. Es específico del intérprete y del SO.
- `.pytest_cache/`, `.ruff_cache/`: artefactos de herramientas (aunque hoy no usemos ninguna).
- `.env`, `.env.local`: **credenciales**. Es la línea más importante del archivo.
- `data/cache/`: caché de respuestas (Fase 10). Es derivable, no es fuente.
- `.DS_Store`, `Thumbs.db`, `.vscode/`, `.idea/`: ruido de sistema y editores.

**Lo que NO se ignora (decisión):**

- `data/metrics.jsonl` — el checklist de entrega pide al menos una ejecución registrada. Se versiona con datos reales.
- `evals/results/` — los resultados de las comparativas son **evidencia** que respalda la elección del prompt.

### 4.4 `.gitattributes`

```
* text=auto eol=lf
*.jsonl text eol=lf
*.yaml text eol=lf
*.py text eol=lf
*.sh text eol=lf
*.ps1 text eol=crlf
```

En Windows, Git puede convertir `\n` en `\r\n` al hacer checkout. Un `dataset.jsonl` con CRLF hace que un parser ingenuo lea líneas con `\r` al final y falle al comparar strings. Este archivo fuerza **LF** en todos los archivos de datos y código, y deja CRLF solo para scripts de PowerShell.

Es barato ahora y evita un bug difícil de diagnosticar en la máquina del corrector.

### 4.5 `requirements.txt`

```
openai==3.37.0
anthropic==2.1.0
pydantic==2.14.1
PyYAML==6.0.3
python-dotenv==1.2.4
```

Cada dependencia tiene una razón:

| Paquete | Rol |
|---|---|
| `openai` | proveedor 1 |
| `anthropic` | proveedor 2 |
| `pydantic` | contrato y validación |
| `PyYAML` | prompts versionados en YAML |
| `python-dotenv` | carga de `.env` |

Lo que **no** está y por qué:

- `pytest`: el runner de evals es un script simple (lo exige la consigna). Los smoke tests usan `assert` puro.
- `tenacity`: el retry se implementa a mano (pocas líneas, sin magia, más fácil de explicar).
- `FastAPI`/`uvicorn`: solo si se hace el extra del Capítulo 11.
- `tiktoken`: los proveedores ya devuelven el conteo de tokens; no hace falta tokenizar localmente.

Los pins con `==` son lo que hace el install reproducible. `>=` deja que mañana entre una versión que rompe el contrato.

### 4.6 `.env.example`

```dotenv
# ==== Proveedores (al menos uno obligatorio) ====
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# ==== Servicio ====
DEFAULT_PROVIDER=mock
DEFAULT_PROMPT_VERSION=v1
MAX_RETRIES=2
REQUEST_TIMEOUT_S=30

# ==== Observabilidad ====
METRICS_PATH=data/metrics.jsonl
LOG_LEVEL=INFO
```

Reglas:

- **Nunca** valores reales. Este archivo se versiona.
- El `.env` real se crea copiando (`cp .env.example .env`) y queda ignorado.
- `DEFAULT_PROVIDER=mock` es el default **desde la Fase 2**: OpenAI y Anthropic todavía no están implementados, y copiar el `.env` con `openai` rompía la CLI. En la Fase 3 vuelve a `openai`. La CLI siempre puede overridearlo con `--provider`.
- `MAX_RETRIES=2` significa hasta 2 reintentos **después** del primer intento.
- `METRICS_PATH` permite apuntar a otro archivo en evals sin contaminar el log de uso normal.

### 4.7 `config/providers.yaml`

```yaml
# Precios en USD por 1M de tokens. VERIFICAR contra las páginas oficiales
# antes de la entrega y actualizar la fecha.
# Actualizado: 2026-10-22
default_provider: mock       # cambiar a openai en la Fase 3

providers:
  openai:
    models:
      default:
        id: gpt-4.1-mini          # confirmar ID vigente
        temperature: 0.0
        max_tokens: 700
        pricing:
          input_per_1m_usd: 0.40
          output_per_1m_usd: 1.60

  anthropic:
    models:
      default:
        id: claude-haiku-4-5      # confirmar ID vigente
        temperature: null         # rechazado por la API para este modelo (ADR-016)
        max_tokens: 700
        pricing:
          input_per_1m_usd: 1.00
          output_per_1m_usd: 5.00

  mock:
    models:
      default:
        id: mock-1
        temperature: 0.0
        max_tokens: 700
        pricing:
          input_per_1m_usd: 0.0
          output_per_1m_usd: 0.0
```

Por qué en YAML y no en `.py`:

- cambiar de modelo o de precio **no requiere tocar código**;
- el precio vive junto al modelo que lo usa;
- es auditable: se ve la fecha de actualización;
- el bloque `mock` con precio 0 permite que todo el pipeline corra sin gastar.

`temperature: 0.0` es la intención para clasificación y extracción (determinismo). **Excepción verificada:** `claude-haiku-4-5` rechaza el parámetro, así que su valor es `null` (ver Capítulo 3, §9.1 y ADR-016).

### 4.8 Crear el entorno e instalar

```bash
uv venv --python 3.14
source .venv/bin/activate
uv pip install -r requirements.txt
```

- `uv venv` crea `.venv/` reutilizando el 3.14.3 ya instalado por `uv`.
- `source` activa el entorno (en Windows: `.\.venv\Scripts\Activate.ps1`).
- `uv pip install` instala **dentro** del venv activo.

### 4.9 Git

```bash
git add -A
git commit -m "chore: setup inicial (Python 3.14, dependencias y estructura)"
git remote add origin https://github.com/<usuario>/<repo>.git
git push -u origin master
```

El repositorio debe ser **público** y autocontenido: es requisito de entrega.

## 5. Verificación

Estos son los checks que se corrieron para aprobar la fase:

```bash
python -V
python -c "import openai, anthropic, pydantic, yaml, dotenv; print('deps ok')"
git grep -nE "sk-ant|sk-proj|sk-[A-Za-z0-9]{20}" || echo "sin secretos"
git check-ignore -v .env
git ls-files
git log --oneline
```

Salida esperada (resumida):

```
Python 3.14.3
deps ok
sin secretos
.gitignore:8:.env	.env
.env.example
.gitattributes
.gitignore
.python-version
config/providers.yaml
data/.gitkeep
evals/.gitkeep
evals/results/.gitkeep
requirements.txt
src/__init__.py
src/guardrails/__init__.py
src/observability/__init__.py
src/providers/__init__.py
f0d3629 chore: setup inicial (Python 3.14, dependencias y estructura)
```

| Check | Criterio |
|---|---|
| 1 | `python -V` = 3.14.x |
| 2 | los 5 imports funcionan |
| 3 | no hay claves hardcodeadas |
| 4 | `.env` está ignorado |
| 5 | `.venv/`, `__pycache__/`, `.env` no aparecen en `git ls-files` |
| 6 | estructura completa |
| 7 | `.env.example` cubre todas las variables que leerá el código |
| 8 | todas las deps con `==` |
| 9 | un commit inicial, rama pusheada, repo público |

## 6. Decisiones y trade-offs

| Decisión | Alternativa descartada | Motivo | Consecuencia |
|---|---|---|---|
| Python 3.14 | 3.15, 3.12 | cobertura completa de wheels | sin compilaciones |
| `uv` | `venv` + `pip` | evita el intérprete equivocado, es rápido | el README documenta también el camino clásico |
| `requirements.txt` | `pyproject.toml` | es lo que pide la consigna | sin `uv run`; se invoca `python` del venv |
| `metrics.jsonl` versionado | ignorarlo | el checklist pide una ejecución registrada | el log crece en el repo; se acepta |
| `evals/results/` versionado | ignorarlo | es evidencia de la comparativa | diffs más grandes |
| Rama `master` | renombrar a `main` | ya estaba pusheada | ninguna funcional |
| `temperature: 0.0` | 0.7 | determinismo en clasificación | respuestas menos variadas |

## 7. Errores comunes

| Síntoma | Causa | Fix |
|---|---|---|
| `openai requires >=3.10` al instalar | se usó `python3` (3.9.6) del sistema | crear y activar el venv 3.14 |
| `pip3` instala pero `python3` no ve el paquete | `python3` y `pip3` apuntan a intérpretes distintos | usar `.venv/bin/python` |
| `uv run` pide un proyecto | no hay `pyproject.toml` | usar `python` del venv, o `uv run --no-project` |
| `uvicorn[standard]` falla | `uvloop` no tiene wheels para 3.14/3.15 | instalar `uvicorn` pelado |
| El dataset tiene `\r` al final | CRLF por Windows | `.gitattributes` con `eol=lf` |
| Un clon no tiene `evals/results/` | carpeta vacía no versionada | `.gitkeep` |
| Aparece una clave en el historial | `.env` commiteado | rotar la clave, `git rm --cached .env`, `.gitignore` |
| El repo pesa 200 MB | `.venv/` commiteado | `git rm -r --cached .venv` |

## 8. Checklist de cierre

- [x] `.python-version` = 3.14
- [x] `.venv` creado y funcional con 3.14.3
- [x] 5 dependencias pinneadas e instaladas
- [x] `.env.example` documentado, sin valores
- [x] `.gitignore` cubre secretos, venv y caché
- [x] `.gitattributes` fuerza LF en datos y código
- [x] estructura de carpetas versionada
- [x] `config/providers.yaml` con 3 proveedores y precios
- [x] un commit inicial, repositorio público y sincronizado

---

**Anterior:** [Capítulo 0 — Introducción](00-introduccion.md) · **Siguiente:** [Capítulo 2 — El contrato](02-fase-1-contrato.md)
