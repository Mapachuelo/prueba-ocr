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
| `POST /api/upload/pdf` | Subir PDF, extraer tabla |
| `POST /api/upload/excel` | Subir Excel, leer datos |
| `POST /api/download/xlsx` | Descargar como XLSX |
| `POST /api/download/xls` | Descargar como XLS |
| `POST /api/download/all` | Descargar ZIP con ambos (.xlsx + .xls) |
| `POST /api/download/pdf` | Descargar como PDF |
| `GET /api/health` | Health check |

## Verificación

```bash
# Procesa un PDF y genera data/verify_output.xlsx y data/verify_output.xls
./scripts/verify.sh ruta/al/documento.pdf

# Benchmark de calidad de extracción (relleno de campos por columna)
python3 scripts/benchmark.py ruta/al/documento.pdf --out data/
```

## Notas

- Tesseract corre en CPU (sin GPU)
- Los archivos subidos y generados se guardan en `./data/`
- Para persistencia, ajusta `hostPath` en `pod.yaml` con ruta absoluta
