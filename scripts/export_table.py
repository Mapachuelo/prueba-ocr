#!/usr/bin/env python3
"""Exporta filas (ground truth o resultados) a .xlsx, .xls y .csv.

Se ejecuta dentro del contenedor (ver scripts/ocr_lab.sh para el patrón).

Uso:
    python3 scripts/export_table.py data/ground_truth.json --out data/
"""
import argparse
import csv
import json
from pathlib import Path

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


def load_rows(path: Path):
    data = json.loads(path.read_text())
    rows = []
    if isinstance(data, dict) and "pages" in data:
        for page, fields in data["pages"].items():
            row = {"pagina": int(page)}
            row.update(fields)
            rows.append(row)
    elif isinstance(data, dict) and "rows" in data:
        headers = data.get("headers", [])
        for i, values in enumerate(data["rows"]):
            row = {"pagina": i + 1}
            if headers[:1] == ["Página"]:
                row["pagina"] = int(values[0])
                values = values[1:]
            for field, value in zip(FIELDS, values):
                row[field] = value
            rows.append(row)
    elif isinstance(data, list):
        rows = data
    else:
        raise SystemExit(f"Formato no reconocido: {path}")
    rows.sort(key=lambda r: int(r.get("pagina", 0)))
    return rows


def to_matrix(rows):
    matrix = []
    for row in rows:
        matrix.append([str(row.get("pagina", ""))] + [str(row.get(f, "") or "") for f in FIELDS])
    return matrix


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", default="data")
    ap.add_argument("--name", default=None)
    args = ap.parse_args()

    src = Path(args.input)
    rows = load_rows(src)
    matrix = to_matrix(rows)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.name or src.stem

    csv_path = out_dir / f"{stem}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADERS)
        writer.writerows(matrix)

    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "datos"
    ws.append(HEADERS)
    for row in matrix:
        ws.append(row)
    xlsx_path = out_dir / f"{stem}.xlsx"
    wb.save(xlsx_path)

    import xlwt
    wbx = xlwt.Workbook()
    wsx = wbx.add_sheet("datos")
    for c, header in enumerate(HEADERS):
        wsx.write(0, c, header)
    for r, row in enumerate(matrix, start=1):
        for c, value in enumerate(row):
            wsx.write(r, c, value)
    xls_path = out_dir / f"{stem}.xls"
    wbx.save(str(xls_path))

    print(f"{len(rows)} filas exportadas:")
    print(f"  {csv_path}")
    print(f"  {xlsx_path}")
    print(f"  {xls_path}")


if __name__ == "__main__":
    main()
