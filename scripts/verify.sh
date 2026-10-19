#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_DIR/data"
PDF_PATH="${1:?Uso: verify.sh <ruta-al-pdf>}"
BASE_URL="${OCR_BASE_URL:-http://localhost:8081}"
OCR_USER="${OCR_USER:-admin}"
OCR_PASS="${OCR_PASS:?Define OCR_PASS con la contraseña del usuario}"
COOKIE="$(mktemp)"
trap 'rm -f "$COOKIE"' EXIT

echo "============================================"
echo "VERIFICACIÓN: Extracción de cédulas a Excel"
echo "PDF: $PDF_PATH"
echo "============================================"

echo "[0/5] Iniciando sesión..."
LOGIN_CODE=$(curl -s -o /dev/null -w "%{http_code}" -c "$COOKIE" \
    -X POST "$BASE_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -H "X-Requested-With: XMLHttpRequest" \
    -d "{\"username\":\"$OCR_USER\",\"password\":\"$OCR_PASS\"}")
if [ "$LOGIN_CODE" != "200" ]; then
    echo "ERROR: login falló ($LOGIN_CODE). Revisa OCR_USER/OCR_PASS."
    exit 1
fi

cp "$PDF_PATH" "$DATA_DIR/uploads/verify_input.pdf"
echo "[1/5] PDF copiado al volumen"

echo "[2/5] Procesando con OCR..."
RESP_JSON=$(curl -s --max-time 600 -b "$COOKIE" \
    -H "X-Requested-With: XMLHttpRequest" \
    -X POST \
    -F "file=@$DATA_DIR/uploads/verify_input.pdf" \
    "$BASE_URL/api/upload/pdf")
echo "$RESP_JSON" > "$DATA_DIR/verify_response.json"
SESSION_ID=$(echo "$RESP_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null || echo "")
echo "  Session: $SESSION_ID"

echo "[3/5] Descargando XLSX..."
curl -s -b "$COOKIE" -H "X-Requested-With: XMLHttpRequest" \
    -X POST "$BASE_URL/api/download/xlsx" \
    -H "Content-Type: application/json" \
    -d "{\"session_id\": \"$SESSION_ID\"}" \
    -o "$DATA_DIR/verify_output.xlsx"
echo "  Guardado: data/verify_output.xlsx"

echo "[4/5] Descargando XLS..."
curl -s -b "$COOKIE" -H "X-Requested-With: XMLHttpRequest" \
    -X POST "$BASE_URL/api/download/xls" \
    -H "Content-Type: application/json" \
    -d "{\"session_id\": \"$SESSION_ID\"}" \
    -o "$DATA_DIR/verify_output.xls"
echo "  Guardado: data/verify_output.xls"

echo ""
echo "[5/5] RESUMEN DE EXTRACCIÓN:"
echo "============================================"
python3 -c "
import json
from collections import defaultdict

with open('$DATA_DIR/verify_response.json') as f:
    data = json.load(f)

n = len(data['rows'])
non_empty = defaultdict(int)
for row in data['rows']:
    for h, v in zip(data['headers'], row):
        if v.strip():
            non_empty[h] += 1

print(f'  Total páginas en PDF: {n}')
print(f'  Extractor: {data.get(\"extractor\", \"?\")}')
print()
print(f'  {\"Campo\":30s} {\"#\":>3s}/{\"total\":>4s}  {\"%\":>4s}')
print(f'  {\"-\"*45}')
for h in data['headers']:
    if h in ('OCR_Raw', 'Página'): continue
    pct = non_empty[h] * 100 // n
    print(f'  {h:30s} {non_empty[h]:>3d}/{n:>4d}  ({pct:>3d}%)')

print()
print('  CÉDULAS EXTRAÍDAS:')
for row in data['rows']:
    p, c = row[0], row[1]
    extra = []
    if row[2]: extra.append(f'A:{row[2][:20]}')
    if row[3]: extra.append(f'N:{row[3][:20]}')
    if row[4]: extra.append(f'FN:{row[4]}')
    if row[5]: extra.append(f'LN:{row[5]}')
    if row[6]: extra.append(f'RH:{row[6]}')
    if row[7]: extra.append(f'S:{row[7]}')
    if row[8]: extra.append(f'Est:{row[8]}')
    if row[9]: extra.append(f'FE:{row[9]}')
    if row[10]: extra.append(f'LE:{row[10]}')
    line = f'    Pag {p:>2}: Cédula={\"\" if not c else c:11s}'
    if extra:
        line += ' | ' + ', '.join(extra)
    print(line)
" 2>&1

echo ""
echo "============================================"
echo "Archivos generados:"
echo "  - data/verify_response.json"
echo "  - data/verify_output.xlsx"
echo "  - data/verify_output.xls"
echo ""
echo "Para verificar: abre data/verify_output.xlsx y"
echo "compara con las imágenes del PDF original."
echo "============================================"
