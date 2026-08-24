import re
import numpy as np
from PIL import Image

_ocr = None

COLOMBIAN_CITIES = {
    "CALI", "MEDELLIN", "BOGOTA", "BOGOTÁ", "BARRANQUILLA", "CARTAGENA",
    "BUCARAMANGA", "PEREIRA", "MANIZALES", "IBAGUE", "IBAGUÉ", "VILLAVICENCIO",
    "SANTA MARTA", "CUCUTA", "CÚCUTA", "PASTO", "NEIVA", "ARMENIA", "POPAYAN",
    "POPAYÁN", "TUNJA", "FLORENCIA", "YOPAL", "RIOHACHA", "VALLEDUPAR",
    "MONTERIA", "MONTERÍA", "SINCELEJO", "QUIBDO", "QUIBDÓ", "MOCOA",
    "LETICIA", "INIRIDA", "INÍRIDA", "PUERTO CARREÑO", "SAN JOSE DEL GUAVIARE",
    "MITU", "MITÚ",
}

MONTHS = {
    "ENE": "ENE", "FEB": "FEB", "MAR": "MAR", "ABR": "ABR",
    "MAY": "MAY", "JUN": "JUN", "JUL": "JUL", "AGO": "AGO",
    "SEP": "SEP", "OCT": "OCT", "NOV": "NOV", "DIC": "DIC",
}

MONTH_FULL = {
    "ENERO": "ENE", "FEBRERO": "FEB", "MARZO": "MAR", "ABRIL": "ABR",
    "MAYO": "MAY", "JUNIO": "JUN", "JULIO": "JUL", "AGOSTO": "AGO",
    "SEPTIEMBRE": "SEP", "OCTUBRE": "OCT", "NOVIEMBRE": "NOV", "DICIEMBRE": "DIC",
}

REMOVE_CHARS = re.compile(r"[^A-ZÁÉÍÓÚÑ0-9\s/()=:,.ºÑñ-]")
SPACES = re.compile(r"\s+")
CITY_DEPTO = re.compile(r"([A-ZÁÉÍÓÚÑ]{4,})\s*\(([A-ZÁÉÍÓÚÑ\s]+)\)")
DATE_RE = re.compile(
    r"(\d{1,2})\s*[-–—/]\s*([A-Za-z]{3,9})\s*[-–—/]\s*(\d{2,4})"
)


def _get_ocr():
    global _ocr
    if _ocr is None:
        from paddleocr import PaddleOCR
        import logging
        logging.getLogger("ppocr").setLevel(logging.ERROR)
        _ocr = PaddleOCR(
            use_angle_cls=True,
            lang="en",
            use_gpu=False,
            show_log=False,
        )
    return _ocr


def extract_from_image(pil_image: Image.Image, dpi: int = 200) -> dict:
    img_np = np.array(pil_image.convert("RGB"))
    ocr = _get_ocr()
    try:
        raw = ocr.ocr(img_np, cls=True)
    except Exception:
        return _empty_result("ocr_error")

    if not raw:
        return _empty_result("no_result")

    entries = raw
    while isinstance(entries, list) and len(entries) == 1 and isinstance(entries[0], (list, tuple)) and not isinstance(entries[0][0], (int, float)):
        entries = entries[0]

    if not entries:
        return _empty_result("no_entries")

    lines_map = {}
    for bbox, (text, conf) in entries:
        y_center = (bbox[0][1] + bbox[2][1]) / 2
        row_key = int(round(y_center / 22) * 22)
        if row_key not in lines_map:
            lines_map[row_key] = []
        lines_map[row_key].append((bbox[0][0], text.strip(), conf))

    lines = []
    for row_key in sorted(lines_map.keys()):
        words = sorted(lines_map[row_key], key=lambda x: x[0])
        line_text = " ".join(w[1] for w in words)
        if line_text:
            lines.append(line_text)

    combined = "\n".join(lines)

    barcode = _parse_barcode(combined)
    cedula = _extract_cedula(combined, barcode)
    apellidos = _extract_field(combined, "APELLIDOS", ["NOMBRES", "FECHA", "LUGAR"])
    nombres = _extract_field(combined, "NOMBRES", ["FECHA", "LUGAR", "APELLIDOS"])
    fecha_nac = _extract_fecha_nac(combined)
    lugar_nac = _extract_lugar(combined, "NACIMIENTO")
    rh, sexo, est = _extract_rh_sexo_est(combined)
    sexo = sexo or barcode.get("sexo", "")
    fecha_exp, lugar_exp = _extract_expedicion(combined)

    mrz = _parse_mrz(combined)
    if not apellidos and mrz.get("apellidos"):
        apellidos = mrz["apellidos"]
    if not nombres and mrz.get("nombres"):
        nombres = mrz["nombres"]
    if not fecha_nac and mrz.get("fecha_nac"):
        fecha_nac = mrz["fecha_nac"]
    if not sexo and mrz.get("sexo"):
        sexo = mrz["sexo"]
    if not cedula and mrz.get("cedula"):
        cedula = mrz["cedula"]

    return {
        "_ocr_raw": combined[:600],
        "numero": cedula,
        "apellidos": apellidos,
        "nombres": nombres,
        "fecha_nacimiento": _clean_fecha(fecha_nac),
        "lugar_nacimiento": _clean_lugar(lugar_nac),
        "rh": rh,
        "sexo": sexo,
        "estatura": _clean_estatura(est),
        "fecha_expedicion": _clean_fecha(fecha_exp),
        "lugar_expedicion": _clean_lugar(lugar_exp),
    }


def _empty_result(reason: str = "") -> dict:
    return {
        "_ocr_raw": "",
        "numero": "", "apellidos": "", "nombres": "",
        "fecha_nacimiento": "", "lugar_nacimiento": "",
        "rh": "", "sexo": "", "estatura": "",
        "fecha_expedicion": "", "lugar_expedicion": "",
    }


def extract_from_pdf_page(pil_image: Image.Image, page_num: int, dpi: int = 200) -> dict:
    result = extract_from_image(pil_image, dpi)
    result["pagina"] = page_num
    return result


def _parse_barcode(text: str) -> dict:
    result = {"cedula": "", "sexo": "", "fecha": ""}
    all_nums = re.findall(r"\d{6,12}", text)
    for n in all_nums:
        if _is_date(n):
            result["fecha"] = n
    sex_m = re.search(r"[-–—\s]([MF])[-–—\s]", text, re.IGNORECASE)
    if sex_m:
        result["sexo"] = sex_m.group(1).upper()
    ced_nums = [n for n in all_nums if not _is_date(n) and not _is_prefix(n)
                and len(n) >= 6]
    if ced_nums:
        result["cedula"] = max(ced_nums, key=lambda n: len(n.lstrip("0")))
    elif all_nums:
        result["cedula"] = max(all_nums, key=len)
    return result


def _is_date(s: str) -> bool:
    return (len(s) == 8 and s[:4].isdigit() and 2000 <= int(s[:4]) <= 2030
            and 1 <= int(s[4:6]) <= 12 and 1 <= int(s[6:8]) <= 31)


def _is_prefix(s: str) -> bool:
    return (len(s) == 7 and (s.startswith("44") or s.startswith("19")))


def _is_valid_cedula(s: str) -> bool:
    if not s or len(s) < 6 or len(s) > 11:
        return False
    if s.startswith("44") and len(s) == 7:
        return False
    if s.startswith("190") and 6 <= len(s) <= 8:
        return False
    return True


def _extract_cedula(text: str, barcode: dict) -> str:
    for pattern in [
        r"(?:N[UÚ]MERO|No\.?|CEDULA|N[°º])\s*[:\-]?\s*([\d\s.]{7,16})",
        r"(?:CEDULA\s+DE\s+CIUDADANIA)\s*[\s\S]{0,20}?(\d[\d\s.]{6,14})",
        r"NUIP\s*[:\-]?\s*([\d\s.,]{7,16})",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            n = re.sub(r"\D", "", m.group(1))
            if _is_valid_cedula(n):
                return n
    nums = re.findall(r"\b(\d[\d\s.]{6,15})\b", text)
    for n in nums:
        cleaned = re.sub(r"\D", "", n)
        if _is_valid_cedula(cleaned):
            return cleaned
    if barcode.get("cedula") and _is_valid_cedula(barcode["cedula"].lstrip("0")):
        return barcode["cedula"]
    all_nums = re.findall(r"\d{6,11}", text)
    for n in sorted(all_nums, key=len, reverse=True):
        if _is_valid_cedula(n.lstrip("0")):
            return n.lstrip("0") or n
    return ""


def _extract_field(text: str, label: str, stop_words: list) -> str:
    upper = text.upper()
    idx = upper.find(label)
    if idx < 0:
        return ""
    rest = upper[idx + len(label):].strip().lstrip(":- ")
    for sw in stop_words:
        si = rest.find(sw)
        if si > 0:
            rest = rest[:si]
    stop_kw = {"CEDULA DE CIUDADANIA", "REPUBLICA DE COLOMBIA", "POWERED BY",
               "SCANNED WITH", "CAMSCANNER", "NÚMERO", "NUMERO", "No.",
               "INDICE", "REGISTRADOR", "FECHA DE NACIMIENTO",
               "LUGAR DE NACIMIENTO", "ESTATURA", "G.S.", "FECHA Y LUGAR",
               "EXPEDICION", "EXPEDICIÓN", "IDENTIFICACION PERSONAL"}
    for sw in stop_kw:
        si = rest.find(sw)
        if 0 < si < 60:
            rest = rest[:si]
    rest = SPACES.sub(" ", REMOVE_CHARS.sub(" ", rest)).strip().upper()
    words = rest.split()
    result = " ".join(w for w in words if len(w) > 1 or w in "ÁÉÍÓÚÑáéíóúñ")
    noise = sum(1 for c in result if not c.isalpha() and c != " ")
    alpha = sum(1 for c in result if c.isalpha())
    if result and len(result) > 1 and alpha > 0 and noise < alpha:
        if not any(sw in result for sw in stop_kw):
            return result
    return ""


def _extract_fecha_nac(text: str) -> str:
    idx = text.upper().find("NACIMIENTO")
    snippet = text[max(0, idx - 10):idx + 100] if idx >= 0 else text[:300]
    for m in DATE_RE.finditer(snippet):
        date = _parse_date_match(m)
        if date:
            return date
    for m in DATE_RE.finditer(text):
        date = _parse_date_match(m)
        if date:
            return date
    return ""


def _parse_date_match(match) -> str:
    day, month_str, year = match.group(1), match.group(2).upper()[:3], match.group(3)
    month = MONTHS.get(month_str) or MONTH_FULL.get(month_str)
    if not month and month_str.isdigit():
        mn = int(month_str)
        if 1 <= mn <= 12:
            month = list(MONTHS.values())[mn - 1]
    if month and 1 <= int(day) <= 31:
        day = day.zfill(2)
        if len(year) == 2:
            year = "20" + year if int(year) < 30 else "19" + year
        return f"{day}-{month}-{year}"
    return ""


def _extract_lugar(text: str, keyword: str) -> str:
    idx = text.upper().find(keyword)
    if idx < 0:
        return ""
    rest = text[idx + len(keyword):].strip().lstrip(":- ")[:80]
    for sw in ["G.S.", "ESTATURA", "SEXO", "RH", "FECHA", "EXPEDIC", "LUGAR"]:
        si = rest.upper().find(sw)
        if si > 0:
            rest = rest[:si]
    rest = SPACES.sub(" ", REMOVE_CHARS.sub(" ", rest)).strip()
    return rest


def _extract_rh_sexo_est(text: str) -> tuple:
    rh, sexo, est = "", "", ""
    idx = -1
    for kw in ["ESTATURA", "G.S.", "SEXO", "RH"]:
        p = text.upper().find(kw)
        if p >= 0:
            idx = p
            break
    if idx < 0:
        return ("", "", "")
    snippet = text[max(0, idx - 30):idx + 120]
    m_rh = re.search(
        r"\b(O\s*[+]|A\s*[+]|B\s*[+]|AB\s*[+]|O\s*[-]|A\s*[-]|B\s*[-]|AB\s*[-])",
        snippet, re.IGNORECASE
    )
    if m_rh:
        rh = m_rh.group(1).replace(" ", "")
    m_sex = re.search(r"\b([MF])\b", snippet, re.IGNORECASE)
    if m_sex:
        sexo = m_sex.group(1).upper()
    m_est = re.search(r"(\d{2,3}(?:[.,]\d{0,2})?)", snippet)
    if m_est:
        val = m_est.group(1).replace(",", ".")
        try:
            if 30 <= float(val) <= 250:
                est = val.split(".")[0]
        except ValueError:
            pass
    return (rh, sexo, est)


def _extract_expedicion(text: str) -> tuple:
    idx = text.upper().find("EXPEDIC")
    if idx < 0:
        return ("", "")
    snippet = text[idx:idx + 120]
    m = DATE_RE.search(snippet)
    if m:
        date = _parse_date_match(m)
        rest = snippet.split(m.group(0))[-1].strip()[:60]
        rest = SPACES.sub(" ", REMOVE_CHARS.sub(" ", rest)).strip()
        place = rest.split("INDICE")[0].split("REGI")[0].strip()
        return (date, place)
    return ("", "")


def _parse_mrz(text: str) -> dict:
    result = {"cedula": "", "apellidos": "", "nombres": "", "fecha_nac": "", "sexo": ""}
    name_lines = []
    doc_nums = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or "<" not in line:
            continue
        if re.search(r"[A-Z]+<+[A-Z]", line):
            name_lines.append(line)
        nums = re.findall(r"(\d{6,12})", line)
        for n in nums:
            if not _is_date(n) and not _is_prefix(n):
                doc_nums.append(n)
        date_m = re.search(r"(\d{6})(\d)?.", line)
        if date_m and not result["fecha_nac"]:
            d = date_m.group(1)
            yy, mm, dd = d[:2], d[2:4], d[4:6]
            if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31:
                yy_f = "20" + yy if int(yy) < 60 else "19" + yy
                month = list(MONTHS.values())[int(mm) - 1]
                result["fecha_nac"] = f"{dd}-{month}-{yy_f}"
        sex_m = re.search(r"\d{7}([MF])", line, re.IGNORECASE)
        if sex_m and not result["sexo"]:
            result["sexo"] = sex_m.group(1).upper()
    if name_lines and not result["nombres"]:
        full = " ".join(name_lines).replace("<", " ").strip()
        full = SPACES.sub(" ", full).strip()
        parts = full.split()
        if len(parts) >= 2:
            result["apellidos"] = " ".join(parts[:2])
            if len(parts) > 2:
                result["nombres"] = " ".join(parts[2:])
    if doc_nums and not result["cedula"]:
        result["cedula"] = max(doc_nums, key=len)
    return result


def _clean_fecha(val: str) -> str:
    if not val or len(val) < 10:
        return ""
    return val


def _clean_lugar(val: str) -> str:
    if not val or len(val) < 3:
        return ""
    val = SPACES.sub(" ", REMOVE_CHARS.sub(" ", val)).strip().upper()
    val = val.lstrip("( ").rstrip(") ")
    if not val:
        return ""
    for city in COLOMBIAN_CITIES:
        if city in val:
            return city
    m = CITY_DEPTO.search(val)
    if m:
        return m.group(1).upper()
    return val.strip()


def _clean_estatura(val: str) -> str:
    if not val:
        return ""
    m = re.search(r"(\d{2,3})", val)
    if m and 30 <= int(m.group(1)) <= 250:
        return str(int(m.group(1)))
    return ""
