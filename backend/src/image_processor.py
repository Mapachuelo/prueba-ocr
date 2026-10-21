import cv2
import numpy as np
from PIL import Image


def preprocess_for_ocr(pil_image: Image.Image, dpi: int = 200) -> np.ndarray:
    gray = _to_gray(pil_image)
    gray = _deskew(gray)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def enhance_page(pil_image: Image.Image) -> np.ndarray:
    """Página realzada para el motor OCR candidato (perfil `cand`)."""
    gray = _to_gray(pil_image)
    gray = _deskew(gray)
    gray = _remove_shadow(gray)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def barcode_values(pil_image: Image.Image) -> list:
    try:
        from pyzbar.pyzbar import decode
    except Exception:
        return []
    try:
        results = decode(pil_image.convert("RGB"))
    except Exception:
        return []
    values = []
    for item in results or []:
        try:
            values.append(item.data.decode("utf-8", "ignore"))
        except Exception:
            continue
    return values


def _to_gray(pil_image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(pil_image.convert("RGB")), cv2.COLOR_RGB2GRAY)


def _remove_shadow(gray: np.ndarray) -> np.ndarray:
    kernel = np.ones((7, 7), np.uint8)
    dilate = cv2.dilate(gray, kernel)
    background = cv2.medianBlur(dilate, 21)
    return cv2.divide(gray, background, scale=255)


def _deskew(img: np.ndarray) -> np.ndarray:
    coords = np.column_stack(np.where(img < 200))
    if len(coords) < 100:
        return img
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle
    if abs(angle) < 0.5 or abs(angle) > 5:
        return img
    h, w = img.shape
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        img, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
