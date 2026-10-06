import base64
import io
import json
import logging
import os
import re
import time

import httpx
from PIL import Image

from . import prompts
from .settings_store import STORE

logger = logging.getLogger("ai_ocr")

MAX_FAILS = 3
COOLDOWN_SECONDS = 120
MAX_IMAGE_SIDE = 1600

_state = {"fails": 0, "disabled_until": 0.0, "warned": False}


def _settings() -> tuple:
    data = STORE.load() or {}
    base_url = data.get("base_url") or os.environ.get("LLM_BASE_URL", "")
    api_key = data.get("api_key") or os.environ.get("LLM_API_KEY", "no-key")
    model = data.get("model") or os.environ.get("LLM_MODEL", "")
    timeout = float(os.environ.get("LLM_TIMEOUT", "300"))
    return base_url.rstrip("/"), api_key, model, timeout


def is_configured() -> bool:
    base_url, _, model, _ = _settings()
    return bool(base_url and model)


def _circuit_open() -> bool:
    return time.monotonic() < _state["disabled_until"]


def _note_failure() -> None:
    _state["fails"] += 1
    if _state["fails"] >= MAX_FAILS:
        _state["disabled_until"] = time.monotonic() + COOLDOWN_SECONDS
        _state["fails"] = 0
        if not _state["warned"]:
            logger.warning("IA local desactivada temporalmente (%ss)", COOLDOWN_SECONDS)
            _state["warned"] = True


def _note_success() -> None:
    _state["fails"] = 0
    _state["warned"] = False


def _parse_json(text: str):
    if not text:
        return None
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-zA-Z]*\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        return json.loads(clean)
    except ValueError:
        pass
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except ValueError:
            return None
    return None


def _encode(image: Image.Image) -> str:
    img = image.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_IMAGE_SIDE:
        scale = MAX_IMAGE_SIDE / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def ocr_page(pil_image: Image.Image) -> dict | None:
    base_url, api_key, model, timeout = _settings()
    if not (base_url and model) or _circuit_open():
        return None

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 700,
        "messages": [
            {"role": "system", "content": prompts.OCR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompts.OCR_USER_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{_encode(pil_image)}"},
                    },
                ],
            },
        ],
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            res = client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except Exception as exc:
        logger.warning("IA local inalcanzable: %s", exc)
        _note_failure()
        return None

    if res.status_code >= 400:
        logger.warning("IA local respondió %s: %s", res.status_code, res.text[:200])
        _note_failure()
        return None

    try:
        content = res.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as exc:
        logger.warning("Respuesta IA inesperada: %s", exc)
        _note_failure()
        return None

    parsed = _parse_json(content)
    if not isinstance(parsed, dict):
        _note_failure()
        return None

    _note_success()
    return {field: str(parsed.get(field, "") or "").strip() for field in prompts.FIELDS}


def health() -> dict:
    base_url, api_key, model, _ = _settings()
    info = {
        "enabled": bool(base_url and model),
        "reachable": False,
        "model": model,
        "base_url": base_url,
    }
    if not base_url:
        return info
    try:
        with httpx.Client(timeout=5) as client:
            res = client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        info["reachable"] = res.status_code < 400
        if info["reachable"]:
            try:
                info["models"] = [m.get("id") for m in res.json().get("data", [])][:20]
            except (ValueError, AttributeError):
                pass
    except Exception:
        pass
    return info
