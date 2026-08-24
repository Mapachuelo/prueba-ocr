import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image


def _preprocess(pil_image: Image.Image) -> Image.Image:
    img = pil_image.convert("L")
    w, h = img.size
    target_min = 1800
    scale = max(1.0, target_min / max(w, h))
    if scale > 1.0:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


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


def _tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def get_text(pil_image: Image.Image) -> str:
    if not _tesseract_available():
        return _paddle_text(pil_image)
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
