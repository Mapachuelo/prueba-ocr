import pdfplumber
from pdf2image import convert_from_path
from .cedula_extractor import extract_from_pdf_page


EXTRACTOR_VERSION = "cedula_v1"


def extract_table_from_pdf(pdf_path: str) -> dict:
    result = _try_text_based_pdf(pdf_path)
    if result["rows"]:
        return result
    return _extract_cedulas(pdf_path)


def _try_text_based_pdf(pdf_path: str) -> dict:
    headers, rows = [], []
    with pdfplumber.open(pdf_path) as pdf:
        text_content = any(page.extract_text() for page in pdf.pages)
        if not text_content:
            return {"headers": [], "rows": [], "extractor": EXTRACTOR_VERSION}
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue
                if not headers and table[0]:
                    headers = [str(c).strip() if c else "" for c in table[0]]
                    rows.extend(
                        [str(c).strip() if c else "" for c in row]
                        for row in table[1:]
                    )
                else:
                    rows.extend(
                        [str(c).strip() if c else "" for c in row]
                        for row in table
                    )
    if headers:
        max_cols = len(headers)
        rows = [row + [""] * (max_cols - len(row)) for row in rows]
    return {"headers": headers, "rows": rows, "extractor": "pdfplumber"}


def _extract_cedulas(pdf_path: str) -> dict:
    images = convert_from_path(pdf_path, dpi=200)
    headers = [
        "Página", "Cédula", "Apellidos", "Nombres",
        "Fecha_Nacimiento", "Lugar_Nacimiento",
        "RH", "Sexo", "Estatura",
        "Fecha_Expedición", "Lugar_Expedición",
        "OCR_Raw",
    ]
    rows = []
    raw_texts = []
    for page_num, img in enumerate(images, 1):
        try:
            data = extract_from_pdf_page(img, page_num)
            raw_ocr = data.get("_ocr_raw", "")
            raw_full = data.get("_ocr_full", "")
            rows.append([
                str(page_num),
                data.get("numero", ""),
                data.get("apellidos", ""),
                data.get("nombres", ""),
                data.get("fecha_nacimiento", ""),
                data.get("lugar_nacimiento", ""),
                data.get("rh", ""),
                data.get("sexo", ""),
                data.get("estatura", ""),
                data.get("fecha_expedicion", ""),
                data.get("lugar_expedicion", ""),
                raw_ocr[:300],
            ])
            raw_texts.append({"pagina": page_num, "ocr_raw": raw_ocr, "ocr_full": raw_full})
        except Exception as e:
            rows.append([str(page_num), f"ERROR: {e}", "", "", "", "", "", "", "", "", "", ""])
            raw_texts.append({"pagina": page_num, "ocr_raw": f"ERROR: {e}"})
    return {
        "headers": headers,
        "rows": rows,
        "extractor": EXTRACTOR_VERSION,
        "page_count": len(images),
        "raw_texts": raw_texts,
    }
