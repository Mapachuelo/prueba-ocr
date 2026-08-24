#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Construyendo backend ==="
podman build -t ocr-backend:latest "$PROJECT_DIR/backend"

echo ""
echo "=== Construyendo frontend ==="
podman build -t ocr-frontend:latest "$PROJECT_DIR/frontend"

echo ""
echo "=== Imágenes construidas ==="
podman images --filter reference="localhost/ocr-*"
