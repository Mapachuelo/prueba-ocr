#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== Iniciando pod ocr-app ==="

# Verificar imágenes
for img in ocr-backend:latest ocr-frontend:latest; do
    if ! podman image exists "localhost/$img" 2>/dev/null; then
        echo "ERROR: Imagen localhost/$img no encontrada. Ejecuta scripts/build.sh primero."
        exit 1
    fi
done

# Eliminar pod existente si lo hay
if podman pod exists ocr-app 2>/dev/null; then
    echo "Pod ocr-app ya existe. Eliminando..."
    podman pod rm -f ocr-app
fi

# Iniciar pod
echo "Ejecutando: podman play kube pod.yaml"
podman play kube pod.yaml

echo ""
echo "=== Pod iniciado ==="
podman pod list
echo ""
echo "Accede a: http://localhost:8080"
