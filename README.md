# OCR PDF a Excel

Prueba de concepto: Web app para extraer tablas de PDF (OCR) y exportar a Excel, y viceversa.

## Stack

- **Backend:** FastAPI + EasyOCR + pdfplumber + openpyxl
- **Frontend:** Nginx + HTML/CSS/JS vanilla
- **Contenedores:** Podman Pod (podman-play-kube)

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
| `POST /api/download/pdf` | Descargar como PDF |
| `GET /api/health` | Health check |

## Notas

- EasyOCR corre en CPU (sin GPU)
- Los archivos subidos y generados se guardan en `./data/`
- Para persistencia, ajusta `hostPath` en `pod.yaml` con ruta absoluta
