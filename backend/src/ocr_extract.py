import os

import pdfplumber
from pdf2image import convert_from_path
from .cedula_extractor import extract_from_pdf_page
from .ocr_engine import active_profile


EXTRACTOR_VERSION = "cedula_v2_tesseract"
EXTRACTOR_AI = "cedula_v3_vlm"
OCR_DPI = int(os.environ.get("OCR_DPI", "200"))

CEDULA_FIELDS = [
    "numero", "apellidos", "nombres", "fecha_nacimiento", "lugar_nacimiento",
    "rh", "sexo", "estatura", "fecha_expedicion", "lugar_expedicion",
]
CEDULA_HEADERS = [
    "Página", "Cédula", "Apellidos", "Nombres",
    "Fecha_Nacimiento", "Lugar_Nacimiento",
    "RH", "Sexo", "Estatura",
    "Fecha_Expedición", "Lugar_Expedición",
    "OCR_Raw",
]


def extract_table_from_pdf(pdf_path: str, mode: str = "local") -> dict:
    if mode == "ai":
        try:
            from .ai_ocr import is_configured
            if is_configured():
                return _extract_cedulas_ai(pdf_path)
        except Exception:
            pass
    result = _try_text_based_pdf(pdf_path)
    if result["rows"]:
        result.setdefault("ai_used", False)
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


def _local_row(page_num: int, data: dict) -> list:
    return [
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
        data.get("_ocr_raw", "")[:900],
    ]


def _extract_cedulas(pdf_path: str) -> dict:
    images = convert_from_path(pdf_path, dpi=OCR_DPI)
    rows = []
    raw_texts = []
    for page_num, img in enumerate(images, 1):
        try:
            data = extract_from_pdf_page(img, page_num)
            rows.append(_local_row(page_num, data))
            raw_texts.append({
                "pagina": page_num,
                "ocr_raw": data.get("_ocr_raw", ""),
                "ocr_full": data.get("_ocr_full", ""),
            })
        except Exception as e:
            rows.append([str(page_num), f"ERROR: {e}", "", "", "", "", "", "", "", "", "", ""])
            raw_texts.append({"pagina": page_num, "ocr_raw": f"ERROR: {e}"})
    return {
        "headers": CEDULA_HEADERS,
        "rows": rows,
        "extractor": f"{EXTRACTOR_VERSION}_{active_profile()}",
        "page_count": len(images),
        "raw_texts": raw_texts,
        "ai_used": False,
    }


def _extract_cedulas_ai(pdf_path: str) -> dict:
    from .ai_ocr import ocr_page

    images = convert_from_path(pdf_path, dpi=OCR_DPI)
    rows = []
    raw_texts = []
    ai_used = False
    for page_num, img in enumerate(images, 1):
        fields = None
        try:
            fields = ocr_page(img)
        except Exception:
            fields = None
        if fields:
            ai_used = True
            rows.append([str(page_num)] + [fields.get(f, "") for f in CEDULA_FIELDS] + [""])
            raw_texts.append({"pagina": page_num, "mode": "ai"})
            continue
        try:
            data = extract_from_pdf_page(img, page_num)
            rows.append(_local_row(page_num, data))
            raw_texts.append({
                "pagina": page_num,
                "mode": "local",
                "ocr_raw": data.get("_ocr_raw", ""),
                "ocr_full": data.get("_ocr_full", ""),
            })
        except Exception as e:
            rows.append([str(page_num), f"ERROR: {e}", "", "", "", "", "", "", "", "", "", ""])
            raw_texts.append({"pagina": page_num, "ocr_raw": f"ERROR: {e}"})
    return {
        "headers": CEDULA_HEADERS,
        "rows": rows,
        "extractor": EXTRACTOR_AI if ai_used else EXTRACTOR_VERSION,
        "page_count": len(images),
        "raw_texts": raw_texts,
        "ai_used": ai_used,
    }
