#!/usr/bin/env python3
"""Laboratorio de OCR local (sin IA).

Se ejecuta DENTRO del contenedor podman (ver scripts/ocr_lab.sh).
Compara perfiles contra data/ground_truth.json si existe.

Uso:
    ./scripts/ocr_lab.sh data/documento.pdf --pages 1-5 --profile cand --out data/lab
"""
import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "backend"))

FIELDS = [
    "numero", "apellidos", "nombres", "fecha_nacimiento", "lugar_nacimiento",
    "rh", "sexo", "estatura", "fecha_expedicion", "lugar_expedicion",
]
HEADERS = [
    "Página", "Cédula", "Apellidos", "Nombres",
    "Fecha_Nacimiento", "Lugar_Nacimiento",
    "RH", "Sexo", "Estatura",
    "Fecha_Expedición", "Lugar_Expedición",
]


def parse_pages(spec: str, total: int):
    if spec == "all":
        return list(range(1, total + 1))
    pages = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            pages.update(range(int(start), int(end) + 1))
        else:
            pages.add(int(part))
    return sorted(p for p in pages if 1 <= p <= total)


def normalize(value: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFD", (value or "").strip().upper())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def load_ground_truth(path: Path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError:
        return {}
    if isinstance(data, dict) and "pages" in data:
        data = data["pages"]
    if isinstance(data, list):
        return {str(i + 1): item for i, item in enumerate(data)}
    return {str(k): v for k, v in data.items()} if isinstance(data, dict) else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", help="PDF a procesar")
    ap.add_argument("--pages", default="all", help="1-5, 3,7, all")
    ap.add_argument("--profile", default=None, help="legacy | cand")
    ap.add_argument("--dpi", type=int, default=None)
    ap.add_argument("--out", default="data/lab")
    args = ap.parse_args()

    if args.profile:
        os.environ["OCR_PROFILE"] = args.profile
    if args.dpi:
        os.environ["OCR_DPI"] = str(args.dpi)

    from pdf2image import convert_from_path
    from src.cedula_extractor import extract_from_pdf_page
    from src.ocr_engine import active_profile

    pdf_path = Path(args.pdf)
    if not pdf_path.is_absolute():
        pdf_path = PROJECT_DIR / pdf_path

    t0 = time.time()
    images = convert_from_path(str(pdf_path), dpi=int(os.environ.get("OCR_DPI", "200")))
    pages = parse_pages(args.pages, len(images))
    rows = []
    for num in pages:
        data = extract_from_pdf_page(images[num - 1], num)
        row = {"pagina": num}
        for field in FIELDS:
            row[field] = data.get(field, "")
        row["_ocr_raw"] = data.get("_ocr_raw", "")
        rows.append(row)
    elapsed = time.time() - t0

    profile = active_profile()
    out_dir = (PROJECT_DIR / args.out / f"{profile}_dpi{os.environ.get('OCR_DPI', '200')}")
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    with (out_dir / "rows.csv").open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADERS + ["OCR_Raw"])
        for row in rows:
            writer.writerow(
                [row["pagina"]] + [row[f] for f in FIELDS] + [row["_ocr_raw"][:200]]
            )

    print(f"Perfil: {profile} | dpi: {os.environ.get('OCR_DPI', '200')} | "
          f"páginas: {len(rows)} | tiempo: {elapsed:.1f}s "
          f"({elapsed / max(len(rows), 1):.1f}s/pág)")
    print(f"Artefactos: {out_dir}")

    gt = load_ground_truth(PROJECT_DIR / "data" / "ground_truth.json")
    if not gt:
        print("\n(no hay data/ground_truth.json: se omite comparación)")
        return

    print(f"\n  {'Campo':20s} {'ok':>4s}/{'gt':>4s}  {'%':>4s}")
    print("  " + "-" * 36)
    totals = {"ok": 0, "total": 0}
    for field in FIELDS:
        ok = 0
        total = 0
        for row in rows:
            expected = gt.get(str(row["pagina"]), {})
            value = expected.get(field)
            if value is None or normalize(value) == "":
                continue
            total += 1
            if normalize(row[field]) == normalize(value):
                ok += 1
        totals["ok"] += ok
        totals["total"] += total
        pct = ok * 100 // total if total else 0
        print(f"  {field:20s} {ok:>4d}/{total:>4d}  ({pct:>3d}%)")
    pct = totals["ok"] * 100 // totals["total"] if totals["total"] else 0
    print(f"  {'TOTAL':20s} {totals['ok']:>4d}/{totals['total']:>4d}  ({pct:>3d}%)")


if __name__ == "__main__":
    main()
