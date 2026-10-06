import re

import numpy as np
from PIL import Image

from . import ocr_engine as _ocr_engine
from .ocr_engine import get_text as _ocr_get_text

_CLEAN_RE = re.compile(r"[^A-Za-z0-9ÁÉÍÓÚÑáéíóúñ .():,\-/+&<\n]")
_MULTI_SPACE = re.compile(r"[ \t]+")

FIELDS = [
    "numero", "apellidos", "nombres", "fecha_nacimiento", "lugar_nacimiento",
    "rh", "sexo", "estatura", "fecha_expedicion", "lugar_expedicion",
]

MONTHS3 = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]
MONTH_FULL = {
    "ENERO": "ENE", "FEBRERO": "FEB", "MARZO": "MAR", "ABRIL": "ABR",
    "MAYO": "MAY", "JUNIO": "JUN", "JULIO": "JUL", "AGOSTO": "AGO",
    "SEPTIEMBRE": "SEP", "OCTUBRE": "OCT", "NOVIEMBRE": "NOV", "DICIEMBRE": "DIC",
}
_MONTHS = "|".join(list(MONTHS3) + list(MONTH_FULL.keys()))
_DATE_RE = re.compile(
    r"\b(\d{1,2})\s*[-\–—/.:=&'*\s]?\s*(" + _MONTHS + r")\s*[-\–—/.:=&'*\s]?\s*(\d{2}|\d{4})\b",
    re.IGNORECASE,
)
_RH_RE = re.compile(r"(?<![A-Z0-9])(?:O|A|B|AB)[ \t]*[+\-](?![0-9])", re.IGNORECASE)
_HEIGHT_CM_RE = re.compile(r"(?<!\d)(\d{3})(?!\d)")
_HEIGHT_M_RE = re.compile(r"(?<!\d)([12][.,]\d{2})(?!\d)")

COLOMBIAN_CITIES = {
    "CALI", "MEDELLIN", "BOGOTA", "BOGOTÁ", "BARRANQUILLA", "CARTAGENA",
    "BUCARAMANGA", "PEREIRA", "MANIZALES", "IBAGUE", "IBAGUÉ", "VILLAVICENCIO",
    "SANTA MARTA", "CUCUTA", "CÚCUTA", "PASTO", "NEIVA", "ARMENIA", "POPAYAN",
    "POPAYÁN", "TUNJA", "FLORENCIA", "YOPAL", "RIOHACHA", "VALLEDUPAR",
    "MONTERIA", "MONTERÍA", "SINCELEJO", "QUIBDO", "QUIBDÓ", "MOCOA",
    "LETICIA", "INIRIDA", "INÍRIDA", "PUERTO CARREÑO", "SAN JOSE DEL GUAVIARE",
    "MITU", "MITÚ", "PITALITO", "GARZON", "GARZÓN", "MILAN", "MILÁN",
    "SOLANO", "LERIDA", "LÉRIDA", "EL PAUJIL", "EL DONCELLO", "MACARENA",
    "SAN VICENTE DEL CAGUAN", "CALIMA", "QUIRA", "QUIRÁ", "MORELIA", "PITAL",
    "VILLAGARZON", "VILLAGARZÓN", "BOGOTA D.C.", "BOGOTA D.C", "SAN JOSE",
    "CARTAGO", "CARTAGENA DE CHAIRA", "CHAIRA", "SOLITA", "SOLITÁ", "VEGA",
}

_STOP_LINES = (
    "REPUBLICA", "COLOMBIA", "IDENTIFICA", "CEDULA", "CIUDADANIA", "NUMERO",
    "NÚMERO", "NUIP", "FECHA", "LUGAR", "ESTATURA", "NACIMIENTO", "EXPEDICI",
    "NACIONALIDAD", "INDICE", "DEREC", "REGISTRADOR", "FIRMA", "NOMBRE",
    "CAMSCAN", "SCANNED", "POWERED", "G.S.", "GS.", "SEXO", "SANCHEZ TORRES",
    "SÁNCHEZ", "TOARES", "MUI", "COL ", "NOMBRES", "APELLIDOS", "RH", "Y LUGAR",
)


def _norm_lines(text: str):
    lines = []
    for raw in (text or "").split("\n"):
        line = _MULTI_SPACE.sub(" ", _CLEAN_RE.sub(" ", raw)).strip()
        lines.append(line)
    return lines


def _alpha(s: str) -> str:
    return " ".join(re.findall(r"[A-ZÁÉÍÓÚÑ]+", s.upper()))


def _is_name_line(line: str) -> bool:
    t = _alpha(line)
    if len(t) < 4:
        return False
    if re.search(r"\d", line):
        return False
    words = t.split()
    if not words:
        return False
    up = " " + t + " "
    if any(k in up for k in _STOP_LINES):
        return False
    if len(words) == 1 and len(words[0]) <= 3:
        return False
    return True


def _is_label_line(line: str, kind: str) -> bool:
    t = _alpha(line)
    if not t:
        return False
    if kind == "apellidos":
        return bool(re.match(r"^(A?PEL|APE|AP5)", t)) and "NOMB" not in t
    if kind == "nombres":
        return bool(re.search(r"(?:^|\s)(?:NOMB|OMBR|CMBR|MBR)", " " + t))
    if kind == "fecha_nac":
        return bool(re.search(r"F[ECIO]\w{1,4}\s*(?:DE\s*)?(?:NAC|NAG|NAT)\w*IENTO", t))
    if kind == "lugar_nac":
        return bool(re.search(r"LUG(?:AR|AA|AN|RA|A)\s*(?:DE\s*)?(?:NAC|NAG|NAT)\w*IENTO", t))
    if kind == "expedicion":
        return ("EXPEDIC" in t or "EXBED" in t) and ("LUGAR" in t or "FECHA" in t or "LUGA" in t or "LUGRA" in t)
    if kind == "estatura":
        return any(k in t for k in ("ESTATURA", "G.S.", "GS", "NACIONALIDAD"))
    return False


def _find_label(lines, kind) -> int:
    for i, line in enumerate(lines):
        if _is_label_line(line, kind):
            return i
    return -1


def _scan_back_names(lines, idx) -> str:
    parts = []
    for i in range(idx - 1, max(-1, idx - 4), -1):
        if _is_name_line(lines[i]):
            parts.insert(0, _alpha(lines[i]))
        else:
            break
    return " ".join(dict.fromkeys(parts))


def _scan_forward_names(lines, idx) -> str:
    parts = []
    for i in range(idx + 1, min(len(lines), idx + 4)):
        if _is_name_line(lines[i]):
            parts.append(_alpha(lines[i]))
        else:
            break
    return " ".join(dict.fromkeys(parts))


def _clean_name(s: str) -> str:
    s = " ".join(re.findall(r"[A-ZÁÉÍÓÚÑ]+", s.upper()))
    words = [w for w in s.split() if len(w) > 1 or w in ("DE", "LA", "EL", "DEL")]
    keep_end = ("DE", "LA", "DEL", "AL", "OS")
    while len(words) > 1 and len(words[-1]) <= 2 and words[-1] not in keep_end:
        words.pop()
    return " ".join(words).strip()


def _extract_names(lines, is_new) -> tuple:
    if is_new:
        ap = _find_label(lines, "apellidos")
        no = _find_label(lines, "nombres")
        apellidos = _scan_forward_names(lines, ap) if ap >= 0 else ""
        nombres = _scan_forward_names(lines, no) if no >= 0 else ""
        if not apellidos and no >= 0:
            apellidos = _scan_back_names(lines, no)
        if not apellidos and not nombres:
            apellidos, nombres = _fallback_names(lines)
        return _clean_name(apellidos), _clean_name(nombres)

    ap = _find_label(lines, "apellidos")
    no = _find_label(lines, "nombres")
    apellidos = _scan_back_names(lines, ap) if ap >= 0 else ""
    nombres = ""
    if no >= 0:
        nombres = _scan_back_names(lines, no)
    if ap >= 0 and no < 0:
        nombres = _scan_forward_names(lines, ap)
    if not apellidos and not nombres:
        apellidos, nombres = _fallback_names(lines)
    return _clean_name(apellidos), _clean_name(nombres)


def _fallback_names(lines) -> tuple:
    lines_clean = [re.sub(r"\d", "", l) for l in lines]
    names = []
    started = False
    for line in lines_clean:
        if re.search(r"\b(N[UÚ]MERO|NUIP|No\.?)\b", _alpha(line)):
            started = True
            continue
        if not started:
            continue
        up = line.upper()
        if any(k in up for k in ("DEREC", "INDICE", "REGISTRADOR", "FECHA", "ESTATURA", "LUGAR", "CAMSCAN")):
            break
        if _is_name_line(line):
            words = [w for w in _alpha(line).split() if len(w) > 1]
            names.append(" ".join(words[:2]))
            if len(names) >= 2:
                break
    if not names:
        return "", ""
    return _clean_name(names[0]), _clean_name(names[1] if len(names) > 1 else "")


def _parse_date(match, line: str = "") -> str:
    day, month_str, year = match.group(1), match.group(2).upper(), match.group(3)
    month = month_str[:3] if len(month_str) <= 3 else MONTH_FULL.get(month_str)
    if not month or month not in MONTHS3:
        return ""
    if not (1 <= int(day) <= 31):
        return ""
    if len(year) != 4:
        return ""
    return f"{day.zfill(2)}-{month}-{year}"


def _find_date_in_lines(lines, start, end) -> str:
    for i in range(start, min(end, len(lines))):
        for m in _DATE_RE.finditer(lines[i]):
            d = _parse_date(m, lines[i])
            if d:
                return d
    return ""


def _extract_fecha_nac(lines) -> str:
    idx = _find_label(lines, "fecha_nac")
    if idx >= 0:
        d = _find_date_in_lines(lines, idx, idx + 3)
        if d:
            return d
    for i, line in enumerate(lines):
        up = line.upper()
        if "LUGAR" in up:
            continue
        has_nac = any(k in up for k in ("NACIMIENTO", "NACMIENTO", "NAGIMIENTO"))
        has_fec = any(k in up for k in ("FEC", "FOCH"))
        if has_nac and has_fec:
            d = _find_date_in_lines(lines, i, i + 3)
            if d:
                return d
    return ""


def _normalize_place(raw: str) -> str:
    raw = _MULTI_SPACE.sub(" ", _CLEAN_RE.sub(" ", raw)).strip().upper()
    raw = raw.strip("( ):-.,")
    if not raw:
        return ""
    for city in COLOMBIAN_CITIES:
        if city in raw:
            if city.startswith("BOGOTA"):
                return "BOGOTA"
            return city
    m = re.search(r"\(([A-ZÁÉÍÓÚÑ ]+)\)", raw)
    depto = m.group(1).strip() if m else ""
    before = raw.split("(")[0].strip(" -:.,")
    words = [w for w in re.findall(r"[A-ZÁÉÍÓÚÑ]{4,}", before)]
    if len(words) >= 2 and words[-1] in COLOMBIAN_CITIES:
        return words[-1]
    if words:
        return " ".join(words)
    if depto:
        return depto
    return ""


def _place_like(line: str) -> bool:
    up = line.upper()
    if re.search(r"\d", up):
        return False
    if any(k in up for k in ("FECHA", "LUGAR", "ESTATURA", "NACIMIENTO", "EXPEDICI", "INDICE", "DEREC", "REGISTRADOR", "SEXO", "RH", "G.S.", "GS", "NACIONALIDAD", "REPUBLICA", "IDENTIFICA", "CEDULA", "CAMSCAN")):
        return False
    t = _alpha(up)
    return len(t) >= 3


def _extract_lugar(lines, is_new) -> str:
    idx = _find_label(lines, "lugar_nac")
    if idx < 0:
        return ""
    if is_new:
        snippet = " ".join(lines[idx + 1:idx + 4])
    else:
        parts = []
        for i in range(idx - 1, max(-1, idx - 4), -1):
            if _place_like(lines[i]):
                parts.insert(0, lines[i])
            else:
                break
        snippet = " ".join(parts)
    snippet = re.sub(r"\d{1,2}[-\–—/.:=&'*\s]*[A-Z]{3,9}[-\–—/.:=&'*\s]*\d{2,4}", " ", snippet, flags=re.I)
    snippet = _MULTI_SPACE.sub(" ", snippet).strip()
    return _normalize_place(snippet)


def _extract_rh(lines) -> str:
    win_lines = set()
    for i, line in enumerate(lines):
        up = line.upper()
        if any(k in up for k in ("ESTATURA", "G.S.", "GS", "RH", "SEXO", "COL", "NACIONALIDAD", "NACIMIENTO")):
            for j in (i - 1, i, i + 1):
                if 0 <= j < len(lines):
                    win_lines.add(j)
    win = "\n".join(lines[j] for j in sorted(win_lines))
    m = _RH_RE.search(win)
    if m:
        return m.group(0).replace(" ", "").upper()
    return ""


def _extract_estatura(lines, is_new, text: str) -> str:
    cands = []
    for m in _HEIGHT_M_RE.finditer(text):
        cands.append(round(float(m.group(1).replace(",", ".")) * 100))
    for line in lines:
        if "COL" in line.upper() or any(k in line.upper() for k in ("ESTATURA", "G.S.", "GS", "NACIONALIDAD")):
            for m in _HEIGHT_CM_RE.finditer(line):
                cands.append(int(m.group(1)))
    for v in cands:
        if 130 <= v <= 220:
            return str(v)
    return ""


def _extract_sexo(text: str, barcode_sexo: str, mrz_sexo: str) -> str:
    if barcode_sexo:
        return barcode_sexo
    if mrz_sexo:
        return mrz_sexo
    for m in re.finditer(r"\bCOL\s+[\d.,]+\s+([MF])\b", text, re.I):
        return m.group(1).upper()
    return ""


def _extract_expedicion(lines, is_new) -> tuple:
    idx = _find_label(lines, "expedicion")
    if idx < 0:
        for i, line in enumerate(lines):
            if "EXPEDICI" in line.upper():
                idx = i
                break
    if idx < 0:
        return "", ""
    if is_new:
        start, end = idx, idx + 4
    else:
        start, end = max(0, idx - 3), idx + 2
    for i in range(start, min(end, len(lines))):
        for m in _DATE_RE.finditer(lines[i]):
            d = _parse_date(m, lines[i])
            if not d:
                continue
            rest = lines[i].split(m.group(0))[-1]
            rest = re.sub(r"[0-9]", " ", rest)
            rest = _MULTI_SPACE.sub(" ", _CLEAN_RE.sub(" ", rest)).strip(" ,:-.")
            place = _normalize_place(rest)
            return d, place
    return "", ""


_BARCODE_RE = re.compile(
    r"(?:^|[^A-Z0-9])[AP]?[-\s]?\d{6,9}[-\s]([\d .,]{5,12})[-\s]?([MF])[-\s]?[\d .]",
    re.IGNORECASE,
)

_MRZ_VALUES = {str(d): d for d in range(10)}
_MRZ_VALUES.update({chr(ord("A") + i): 10 + i for i in range(26)})
_MRZ_VALUES["<"] = 0
_MRZ_WEIGHTS = (7, 3, 1)


def mrz_check_digit(segment: str) -> str:
    total = sum(
        _MRZ_VALUES.get(ch, 0) * _MRZ_WEIGHTS[i % 3]
        for i, ch in enumerate(segment.upper())
    )
    return str(total % 10)


def _mrz_doc_number(lines) -> str:
    for line in lines:
        clean = re.sub(r"\s", "", line.upper())
        if "<" not in clean or len(clean) < 16:
            continue
        segment = clean[5:14]
        check = clean[14:15]
        digits = _clean_num(segment)
        if not (6 <= len(digits) <= 11):
            continue
        if check.isdigit() and mrz_check_digit(segment) == check:
            return digits
    return ""


def _parse_barcode(text: str) -> dict:
    result = {"sexo": "", "cedulas": [], "decoded": []}
    for m in _BARCODE_RE.finditer(text):
        result["cedulas"].append(m.group(1))
        result["sexo"] = m.group(2).upper()
    return result


def _merge_decoded_barcodes(barcode: dict, payloads) -> None:
    for payload in payloads or []:
        for n in re.findall(r"\d{6,18}", payload):
            barcode.setdefault("decoded", []).append(n)
        if not barcode.get("sexo"):
            m = re.search(r"(?:^|[^A-Z])([MF])(?:[^A-Z]|$)", payload.upper())
            if m:
                barcode["sexo"] = m.group(1)


def _parse_mrz(lines) -> dict:
    res = {"cedula": "", "apellidos": "", "nombres": "", "fecha_nac": "", "sexo": ""}
    for line in lines:
        if "<" not in line:
            continue
        if re.search(r"[A-Z]+<+[A-Z]", line):
            parts = [re.sub(r"[^A-Z]+$", "", p) for p in line.replace(" ", "").split("<")]
            parts = [p for p in parts if p]
            if len(parts) >= 2:
                res["apellidos"] = " ".join(parts[:2])
                if len(parts) > 2:
                    res["nombres"] = " ".join(parts[2:])
        m = re.search(r"\b(\d{2})(\d{2})(\d{2})([MF])\d*COL(\d{6,11})", line, re.I)
        if m and not res["cedula"]:
            yy, mm, dd, sexo, ced = m.groups()
            if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31:
                yy_f = "20" + yy if int(yy) < 60 else "19" + yy
                res["fecha_nac"] = f"{dd}-{MONTHS3[int(mm) - 1]}-{yy_f}"
                res["sexo"] = sexo.upper()
                res["cedula"] = ced
    return res


def _is_valid_cedula(s: str) -> bool:
    return bool(s) and 6 <= len(s) <= 11


def _clean_num(s: str) -> str:
    return re.sub(r"\D", "", s)


def _is_barcode_line(line: str) -> bool:
    return bool(_BARCODE_RE.search(line)) or bool(re.match(r"^[AP][-\s]", line.strip()))


def _extract_cedula(upper: str, lines, barcode: dict, mrz: dict, mrz_doc: str = "") -> str:
    for pat in (r"NUIP\s*[:\-.,]?\s*([\d.,]{6,18})", r"(?:N[UÚ]MERO|No\.?)\s*[:\-.,]?\s*([\d.,]{6,18})"):
        for m in re.finditer(pat, upper, re.I):
            n = _clean_num(m.group(1))
            if _is_valid_cedula(n):
                return n
    if _is_valid_cedula(mrz_doc):
        return mrz_doc
    for candidate in barcode.get("decoded", []):
        n = _clean_num(candidate)
        if _is_valid_cedula(n):
            return n
    if _is_valid_cedula(mrz.get("cedula")):
        return mrz["cedula"]
    for n in barcode.get("cedulas", []):
        n = _clean_num(n)
        if _is_valid_cedula(n):
            return n
    for line in lines:
        if _is_barcode_line(line):
            continue
        for n in sorted(set(re.findall(r"\d[\d.,]{5,14}", line)), key=len, reverse=True):
            n = _clean_num(n)
            if _is_valid_cedula(n):
                return n
    return ""


def parse_cedula_text(text: str, decoded_barcodes=None) -> dict:
    lines = _norm_lines(text)
    upper = " ".join(lines).upper()
    barcode = _parse_barcode(text)
    _merge_decoded_barcodes(barcode, decoded_barcodes)
    mrz = _parse_mrz(lines)
    mrz_doc = _mrz_doc_number(lines)
    is_new = ("NUIP" in upper) or ("1CCO" in upper) or ("<<<<<" in upper) or ("NACIONALIDAD" in upper)

    cedula = _extract_cedula(upper, lines, barcode, mrz, mrz_doc)
    if _ocr_engine.active_profile() == "cand" and cedula.startswith("0"):
        stripped = cedula.lstrip("0")
        if _is_valid_cedula(stripped):
            cedula = stripped
    apellidos, nombres = _extract_names(lines, is_new)
    if not apellidos and mrz.get("apellidos"):
        apellidos = mrz["apellidos"]
    if not nombres and mrz.get("nombres"):
        nombres = mrz["nombres"]

    fecha_nac = _extract_fecha_nac(lines)
    if not fecha_nac and mrz.get("fecha_nac"):
        fecha_nac = mrz["fecha_nac"]

    lugar_nac = _extract_lugar(lines, is_new)
    rh = _extract_rh(lines)
    est = _extract_estatura(lines, is_new, upper)
    sexo = _extract_sexo(upper, barcode.get("sexo", ""), mrz.get("sexo", ""))
    fecha_exp, lugar_exp = _extract_expedicion(lines, is_new)

    return {
        "numero": cedula,
        "apellidos": apellidos,
        "nombres": nombres,
        "fecha_nacimiento": fecha_nac,
        "lugar_nacimiento": lugar_nac,
        "rh": rh,
        "sexo": sexo,
        "estatura": est,
        "fecha_expedicion": fecha_exp,
        "lugar_expedicion": lugar_exp,
    }


def extract_from_image(pil_image: Image.Image, dpi: int = 200) -> dict:
    decoded = _decode_barcodes(pil_image)
    if _ocr_engine.active_profile() == "cand":
        legacy_text, enhanced_text = _ocr_engine.get_candidate_texts(pil_image)
        base = parse_cedula_text(legacy_text, decoded_barcodes=decoded)
        if enhanced_text:
            extra = parse_cedula_text(enhanced_text, decoded_barcodes=decoded)
            result = _fuse_fields(base, extra)
            result["_ocr_full"] = legacy_text + "\n---\n" + enhanced_text
        else:
            result = base
            result["_ocr_full"] = legacy_text
        result["_ocr_raw"] = legacy_text[:900]
        return result
    text = _ocr_get_text(pil_image)
    result = parse_cedula_text(text, decoded_barcodes=decoded)
    result["_ocr_raw"] = text[:900]
    result["_ocr_full"] = text
    return result


LONGER_PREFERRED_FIELDS = (
    "apellidos", "nombres", "lugar_nacimiento", "lugar_expedicion",
)


def _decode_barcodes(pil_image: Image.Image) -> list:
    try:
        from .image_processor import barcode_values
        return barcode_values(pil_image)
    except Exception:
        return []


def _fuse_fields(base: dict, extra: dict) -> dict:
    """Completa campos vacíos con la segunda pasada y prefiere nombres/lugares más largos."""
    merged = dict(base)
    for field in FIELDS:
        current = (base.get(field) or "").strip()
        candidate = (extra.get(field) or "").strip()
        if not candidate:
            continue
        if not current:
            merged[field] = candidate
        elif field in LONGER_PREFERRED_FIELDS and len(candidate) > len(current) + 2:
            merged[field] = candidate
    return merged


def extract_from_pdf_page(pil_image: Image.Image, page_num: int, dpi: int = 200) -> dict:
    result = extract_from_image(pil_image, dpi)
    result["pagina"] = page_num
    return result


def _empty_result(reason: str = "") -> dict:
    return {
        "_ocr_raw": "",
        "numero": "", "apellidos": "", "nombres": "",
        "fecha_nacimiento": "", "lugar_nacimiento": "",
        "rh": "", "sexo": "", "estatura": "",
        "fecha_expedicion": "", "lugar_expedicion": "",
    }
