#!/usr/bin/env python3
"""Benchmark de extracción de cédulas desde un PDF escaneado.

Mide cuántos campos se completan por página y genera los Excel (.xlsx/.xls).

Uso:
    python scripts/benchmark.py <ruta-al-pdf> [--out DIR]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from pdf2image import convert_from_path
from openpyxl import Workbook
import xlwt

from src.cedula_extractor import extract_from_pdf_page

FIELDS = [
    "numero", "apellidos", "nombres", "fecha_nacimiento", "lugar_nacimiento",
    "rh", "sexo", "estatura", "fecha_expedicion", "lugar_expedicion",
]
HEADERS = [
    "Página", "Cédula", "Apellidos", "Nombres",
    "Fecha_Nacimiento", "Lugar_Nacimiento",
    "RH", "Sexo", "Estatura",
    "Fecha_Expedición", "Lugar_Expedición",
    "OCR_Raw",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", help="PDF escaneado de cédulas")
    ap.add_argument("--out", default=None, help="Directorio de salida para los Excel")
    args = ap.parse_args()

    print(f"Procesando {args.pdf} ...")
    t0 = time.time()
    images = convert_from_path(args.pdf, dpi=200)
    rows = []
    for page_num, img in enumerate(images, 1):
        data = extract_from_pdf_page(img, page_num)
        rows.append([
            str(page_num),
            data.get("numero", ""), data.get("apellidos", ""), data.get("nombres", ""),
            data.get("fecha_nacimiento", ""), data.get("lugar_nacimiento", ""),
            data.get("rh", ""), data.get("sexo", ""), data.get("estatura", ""),
            data.get("fecha_expedicion", ""), data.get("lugar_expedicion", ""),
            data.get("_ocr_raw", "")[:900],
        ])
    elapsed = time.time() - t0

    print(f"\nPáginas: {len(rows)} | tiempo: {elapsed:.1f}s\n")
    print(f"  {'Campo':20s} {'#':>3s}/{'total':>3s}  {'%':>4s}")
    print("  " + "-" * 36)
    for h, i in zip(HEADERS, range(len(HEADERS))):
        if h in ("OCR_Raw", "Página"):
            continue
        n = sum(1 for r in rows if r[i].strip())
        pct = n * 100 // max(len(rows), 1)
        print(f"  {h:20s} {n:>3d}/{len(rows):>3d}  ({pct:>3d}%)")

    print("\n  Detalle por página:")
    for r in rows:
        extra = []
        for h, v in zip(HEADERS, r):
            if h in ("Página", "OCR_Raw") or not v.strip():
                continue
            extra.append(f"{h}:{v.strip()[:18]}")
        print(f"    Pag {r[0]:>3}: {', '.join(extra) if extra else '(sin datos)'}")

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        wb = Workbook()
        ws = wb.active
        ws.append(HEADERS)
        for row in rows:
            ws.append(row)
        wb.save(out / "tabla.xlsx")
        wbx = xlwt.Workbook()
        wxs = wbx.add_sheet("Sheet1")
        for c, h in enumerate(HEADERS):
            wxs.write(0, c, h)
        for ri, row in enumerate(rows, start=1):
            for ci, v in enumerate(row):
                wxs.write(ri, ci, v)
        wbx.save(out / "tabla.xls")
        print(f"\nExcel generados en: {out}")


if __name__ == "__main__":
    main()
