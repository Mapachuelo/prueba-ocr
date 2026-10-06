# OCR PDF a Excel

Prueba de concepto: Web app para extraer tablas de PDF (OCR) y exportar a Excel (.xlsx y .xls), y viceversa.

## Stack

- **Backend:** FastAPI + Tesseract OCR + pdfplumber + openpyxl/xlwt
- **Frontend:** Nginx + HTML/CSS/JS vanilla
- **Contenedores:** Podman Pod (podman-play-kube)

> Nota: el motor OCR es **Tesseract** (instalado vía apt). El parser de cédulas
> colombianas está en `backend/src/cedula_extractor.py` y maneja los dos
> formatos de cédula (modelo antiguo `IDENTIFICACION PERSONAL` y modelo nuevo
> `NUIP` con código de barras/MRZ).

## Modos de OCR

| Modo | Cómo se usa | Descripción |
|---|---|---|
| **Local (sin IA)** | `mode=local` (default) | Tesseract + OpenCV. Perfil `OCR_PROFILE=legacy\|cand`; `cand` (default) agrega corrección de sombras, CLAHE y fusión de pasadas. |
| **IA local (VLM)** | `mode=ai` | Envía la imagen de la página a un servidor llama.cpp/OpenAI-compatible con el prompt OCR de `backend/src/prompts.py`; si falla, cae al modo local por página. |
| **Agente (offline)** | — | Ground truth de referencia (`data/ground_truth.*`) y reportes comparativos. |

Configura las credenciales del modo IA en el panel **"Configuración IA"** de la
web (primer uso crea usuario/contraseña). Todo se guarda **cifrado** en
`data/ai_settings.enc` (clave en `data/.secret_key`, permisos 600); la API key
nunca se devuelve al navegador.

Alternativa por variables de entorno: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`,
`LLM_TIMEOUT` (se usan si no hay configuración guardada).

## Requisitos

- Podman 4.x+

## Uso

```bash
# 1. Construir imágenes
./scripts/build.sh

# 2. Iniciar pod
./scripts/start.sh

# 3. Abrir en navegador
# http://localhost:8080

# 4. Detener
podman pod stop ocr-app

# 5. Eliminar pod
podman pod rm ocr-app
```

## Endpoints

| Ruta | Descripción |
|---|---|
| `POST /api/upload/pdf` | Subir PDF (`mode=local\|ai`), extraer tabla |
| `POST /api/upload/excel` | Subir Excel, leer datos |
| `POST /api/download/xlsx` | Descargar como XLSX |
| `POST /api/download/xls` | Descargar como XLS |
| `POST /api/download/csv` | Descargar como CSV (UTF-8 con BOM) |
| `POST /api/download/all` | Descargar ZIP con ambos (.xlsx + .xls) |
| `POST /api/download/pdf` | Descargar como PDF |
| `GET /api/health` | Health check |
| `GET /api/health/ai` | Estado del VLM local (`enabled`, `reachable`, `model`) |
| `GET /api/auth/status` | `{setup, authenticated}` |
| `POST /api/auth/setup` | Crea credenciales del panel (primer uso) |
| `POST /api/auth/login` / `logout` | Sesión del panel |
| `GET/PUT/DELETE /api/settings/ai` | Configuración IA cifrada (requiere sesión) |

## Verificación

```bash
# Procesa un PDF y genera data/verify_output.xlsx y data/verify_output.xls
./scripts/verify.sh ruta/al/documento.pdf

# Benchmark de calidad de extracción (relleno de campos por columna)
python3 scripts/benchmark.py ruta/al/documento.pdf --out data/

# Laboratorio OCR dentro del contenedor (perfiles legacy/cand, mide contra ground truth)
./scripts/ocr_lab.sh data/documento.pdf --pages all --profile cand

# Comparativo de modos contra data/ground_truth.json
podman run --rm -v "$PWD":/work:Z -w /work localhost/ocr-backend:latest \
  python3 scripts/compare_modes.py --gt data/ground_truth.json \
  --mode "local_cand=data/lab/cand_dpi200/rows.json" --out data/ocr_compare_report.md

# Mock OpenAI-compatible para probar el modo IA sin modelo real
python3 scripts/mock_llm.py --port 18081
```

Resultados de referencia: `data/ocr_quality_report.md` y `data/ocr_compare_report.md`.

## Notas

- Tesseract corre en CPU (sin GPU)
- Los archivos subidos y generados se guardan en `./data/`
- Para persistencia, ajusta `hostPath` en `pod.yaml` con ruta absoluta
- `data/.secret_key`, `data/auth.json` y `data/ai_settings.enc` son sensibles:
  si borras `.secret_key`, la configuración IA guardada queda ilegible
  (vuelve a guardarla desde el panel)
