#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

if ! podman image exists localhost/ocr-backend:latest 2>/dev/null; then
    echo "ERROR: Imagen localhost/ocr-backend:latest no encontrada. Ejecuta scripts/build.sh primero."
    exit 1
fi

podman run --rm \
    -v "$PROJECT_DIR":/work:Z \
    -w /work \
    localhost/ocr-backend:latest \
    python3 scripts/ocr_lab.py "$@"
