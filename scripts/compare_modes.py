#!/usr/bin/env python3
"""Compara resultados de OCR (uno o varios modos) contra data/ground_truth.json.

Se ejecuta dentro del contenedor. Acepta JSON en formato ground truth
({"pages": {...}}), filas del laboratorio (lista de dicts) o respuesta de la app
({"headers": [...], "rows": [[...]]}).

Uso:
    python3 scripts/compare_modes.py --gt data/ground_truth.json \
        --mode "local_legacy=data/lab/legacy_dpi200/rows.json" \
        --mode "ia=data/uploads/<sid>.json" \
        --out data/ocr_compare_report.md
"""
import argparse
import json
import unicodedata
from pathlib import Path

FIELDS = [
    "numero", "apellidos", "nombres", "fecha_nacimiento", "lugar_nacimiento",
    "rh", "sexo", "estatura", "fecha_expedicion", "lugar_expedicion",
]
TOTAL_PAGES = 42


def normalize(value) -> str:
    text = unicodedata.normalize("NFD", str(value or "").strip().upper())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def load_pages(path: Path) -> dict:
    data = json.loads(path.read_text())
    pages = {}
    if isinstance(data, dict) and "pages" in data:
        for page, fields in data["pages"].items():
            pages[int(page)] = {f: fields.get(f, "") for f in FIELDS}
    elif isinstance(data, dict) and "rows" in data:
        headers = data.get("headers", [])
        for i, values in enumerate(data["rows"]):
            page = i + 1
            if headers[:1] == ["Página"]:
                try:
                    page = int(values[0])
                except (ValueError, IndexError):
                    page = i + 1
                values = values[1:]
            pages[page] = {f: (values[j] if j < len(values) else "") for j, f in enumerate(FIELDS)}
    elif isinstance(data, list):
        for item in data:
            page = int(item.get("pagina", len(pages) + 1))
            pages[page] = {f: item.get(f, "") for f in FIELDS}
    else:
        raise SystemExit(f"Formato no reconocido: {path}")
    return pages


def metrics(result: dict, truth: dict) -> dict:
    per_field = {f: {"ok": 0, "total": 0, "filled": 0} for f in FIELDS}
    for page, expected in truth.items():
        got = result.get(page, {})
        for f in FIELDS:
            value = expected.get(f, "")
            if value:
                per_field[f]["total"] += 1
                if normalize(got.get(f)) == normalize(value):
                    per_field[f]["ok"] += 1
            if normalize(got.get(f)):
                per_field[f]["filled"] += 1
    return per_field


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gt", default="data/ground_truth.json")
    ap.add_argument("--mode", action="append", required=True, help="nombre=archivo.json")
    ap.add_argument("--out", default="data/ocr_compare_report.md")
    args = ap.parse_args()

    truth = load_pages(Path(args.gt))
    modes = []
    for spec in args.mode:
        name, _, path = spec.partition("=")
        modes.append((name, load_pages(Path(path))))

    lines = ["# Reporte comparativo OCR", ""]
    lines.append(f"Referencia (modo 3, agente): `{args.gt}` — {len(truth)} páginas con datos.")
    lines.append("")
    lines.append("Precisión = celdas correctas / celdas con dato en la referencia (normalizado, sin tildes).")
    lines.append("Cobertura = celdas con valor extraído / páginas totales.")
    lines.append("")
    header = "| Campo | " + " | ".join(f"{n} (prec. / cobertura)" for n, _ in modes) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(modes) + 1))

    all_metrics = []
    for name, pages in modes:
        all_metrics.append(metrics(pages, truth))

    for f in FIELDS:
        cells = []
        for m in all_metrics:
            data = m[f]
            pct = data["ok"] * 100 // data["total"] if data["total"] else 0
            cov = data["filled"] * 100 // TOTAL_PAGES
            cells.append(f"{data['ok']}/{data['total']} ({pct}%) / {cov}%")
        lines.append(f"| {f} | " + " | ".join(cells) + " |")

    totals = []
    for m in all_metrics:
        ok = sum(m[f]["ok"] for f in FIELDS)
        total = sum(m[f]["total"] for f in FIELDS)
        filled = sum(m[f]["filled"] for f in FIELDS)
        pct = ok * 100 // total if total else 0
        totals.append(f"{ok}/{total} ({pct}%) / {filled * 100 // (TOTAL_PAGES * len(FIELDS))}%")
    lines.append("| **TOTAL** | " + " | ".join(totals) + " |")
    lines.append("")
    lines.append("> Modo 2 (VLM local): ejecutar la app con `mode=ai` y añadir ")
    lines.append("> `--mode \"ia=data/uploads/<session_id>.json\"` cuando el modelo real esté disponible.")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"Reporte escrito en {out}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
