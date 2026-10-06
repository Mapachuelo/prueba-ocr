import os
import re
import shutil
import subprocess
import tempfile

from PIL import Image

_PROFILE = os.environ.get("OCR_PROFILE", "cand").strip().lower()
MRZ_WHITELIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
_MRZ_LINE_RE = re.compile(r"^[A-Z0-9<]{20,}$")


def active_profile() -> str:
    return _PROFILE


def _preprocess(pil_image: Image.Image) -> Image.Image:
    img = pil_image.convert("L")
    w, h = img.size
    target_min = 1800
    scale = max(1.0, target_min / max(w, h))
    if scale > 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


def _tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _run_tesseract(image: Image.Image, psm: str, lang: str = "spa+eng") -> str:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        image.save(tmp.name)
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            ["tesseract", tmp_path, "stdout", "-l", lang, "--psm", psm],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.stdout or ""
    finally:
        os.unlink(tmp_path)


def _legacy_text(pil_image: Image.Image) -> str:
    pre = _preprocess(pil_image)
    text = _run_tesseract(pre, psm="6")
    if len(text.strip()) < 12:
        sparse = _run_tesseract(pre, psm="11")
        if len(sparse.strip()) > len(text.strip()):
            text = sparse
    if len(text.strip()) < 12:
        auto = _run_tesseract(pre, psm="3")
        if len(auto.strip()) > len(text.strip()):
            text = auto
    return text


def get_text(pil_image: Image.Image) -> str:
    if not _tesseract_available():
        return _paddle_text(pil_image)
    if _PROFILE == "cand":
        legacy, enhanced = get_candidate_texts(pil_image)
        return legacy if not enhanced else legacy + "\n" + enhanced
    return _legacy_text(pil_image)


def get_candidate_texts(pil_image: Image.Image) -> tuple:
    """Perfil candidato: texto legado + texto con preprocesado mejorado (sombra/CLAHE)."""
    from . import image_processor

    legacy_text = _legacy_text(pil_image)
    enhanced_img = Image.fromarray(image_processor.enhance_page(pil_image))
    enhanced_text = _legacy_text(enhanced_img)
    mrz_lines = _mrz_strip(pil_image)
    if mrz_lines:
        enhanced_text = (enhanced_text.rstrip() + "\n" + "\n".join(mrz_lines)).strip()
    return legacy_text, enhanced_text


def _mrz_strip(pil_image: Image.Image) -> list:
    from . import image_processor

    arr = image_processor.preprocess_for_ocr(pil_image)
    h = arr.shape[0]
    strip = Image.fromarray(arr[int(h * 0.78):, :])
    strip = _preprocess(strip)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        strip.save(tmp.name)
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            [
                "tesseract", tmp_path, "stdout", "-l", "spa+eng", "--psm", "6",
                "--oem", "1", "-c", f"tessedit_char_whitelist={MRZ_WHITELIST}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        os.unlink(tmp_path)
    lines = []
    for raw in (result.stdout or "").splitlines():
        clean = raw.strip().replace(" ", "").upper()
        if _MRZ_LINE_RE.match(clean):
            lines.append(clean)
    return lines


def _paddle_text(pil_image: Image.Image) -> str:
    try:
        from paddleocr import PaddleOCR
        import logging
        logging.getLogger("ppocr").setLevel(logging.ERROR)
        ocr = PaddleOCR(use_angle_cls=True, lang="en", use_gpu=False, show_log=False)
        import numpy as np
        raw = ocr.ocr(np.array(pil_image.convert("RGB")), cls=True)
        entries = raw
        while (isinstance(entries, list) and len(entries) == 1
               and isinstance(entries[0], (list, tuple))
               and not isinstance(entries[0][0], (int, float))):
            entries = entries[0]
        lines = []
        for bbox, (text, conf) in entries or []:
            lines.append(text.strip())
        return "\n".join(l for l in lines if l)
    except Exception:
        return ""
