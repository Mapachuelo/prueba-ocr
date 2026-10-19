import base64
import io
import json
import logging
import os
import re
import time
from urllib.parse import urlsplit

import httpx
from PIL import Image

from . import prompts
from .settings_store import STORE

logger = logging.getLogger("ai_ocr")

MAX_FAILS = 3
COOLDOWN_SECONDS = 120
MAX_IMAGE_SIDE = int(os.environ.get("LLM_MAX_IMAGE_SIDE", "1600"))
RETRY_IMAGE_SIDE = int(os.environ.get("LLM_RETRY_IMAGE_SIDE", "1024"))
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "1200"))
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "300"))
DEFAULT_LOCAL_URL = os.environ.get("LLM_BASE_URL", "http://host.containers.internal:9931/v1")
FALLBACK_LOCAL_URLS = [
    "http://host.containers.internal:9931/v1",
    "http://127.0.0.1:9931/v1",
]
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

_state = {"fails": 0, "disabled_until": 0.0, "warned": False, "last_error": ""}
_cache = {"ts": 0.0, "provider": "", "data": None}


def _normalize_base(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not re.match(r"^https?://", url):
        url = "http://" + url
    url = url.rstrip("/")
    path = urlsplit(url).path
    if path in ("", "/"):
        url += "/v1"
    return url


def _settings() -> dict:
    data = STORE.load() or {}
    provider = data.get("provider") or "local"
    return {
        "provider": provider,
        "base_url": _normalize_base(data.get("base_url", "")),
        "api_key": data.get("api_key", "") or os.environ.get("LLM_API_KEY", ""),
        "model": data.get("model", "") or os.environ.get("LLM_MODEL", ""),
        "timeout": float(data.get("timeout") or TIMEOUT),
    }


def _auth_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _parse_model(item: dict) -> dict:
    status = item.get("status") or {}
    args = status.get("args") or []
    vision = "--mmproj" in args
    context = None
    if "--ctx-size" in args:
        try:
            context = int(args[args.index("--ctx-size") + 1])
        except (ValueError, IndexError):
            context = None
    state = status.get("value") or ("failed" if status.get("failed") else "unknown")
    return {
        "id": item.get("id") or item.get("model") or "",
        "loaded": state == "loaded",
        "status": state,
        "vision": vision,
        "context": context,
        "aliases": item.get("aliases") or [],
    }


def _fetch_models(base_url: str, api_key: str = "", timeout: float = 4.0) -> dict:
    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout) as client:
            res = client.get(f"{base_url}/models", headers=_auth_headers(api_key))
        latency = int((time.monotonic() - started) * 1000)
        if res.status_code >= 400:
            return {
                "ok": False,
                "latency_ms": latency,
                "error": f"HTTP {res.status_code}: {res.text[:200]}",
                "models": [],
            }
        data = res.json()
        models = [_parse_model(item) for item in data.get("data", []) if isinstance(item, dict)]
        return {"ok": True, "latency_ms": latency, "error": None, "models": models}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}"[:240],
            "models": [],
        }


def _select_model(models: list, current: str) -> str:
    if current:
        for model in models:
            if model["id"] == current:
                return current
    loaded_vision = [m for m in models if m["loaded"] and m["vision"]]
    if loaded_vision:
        return loaded_vision[0]["id"]
    loaded = [m for m in models if m["loaded"]]
    if loaded:
        return loaded[0]["id"]
    vision = [m for m in models if m["vision"]]
    if vision:
        return vision[0]["id"]
    return models[0]["id"] if models else ""


def discover(force: bool = False) -> dict:
    now = time.monotonic()
    stored = _settings()
    provider = stored["provider"]
    cache_key = f"{provider}:{stored['base_url']}:{stored['model']}"
    if (
        not force
        and _cache["data"] is not None
        and _cache["provider"] == cache_key
        and now - _cache["ts"] < 30
    ):
        return _cache["data"]

    result = {
        "provider": provider,
        "base_url": stored["base_url"],
        "reachable": False,
        "models": [],
        "selected": stored["model"],
        "error": None,
        "tried": [],
        "external": None,
    }

    if provider == "external":
        if not stored["base_url"]:
            result["error"] = "Configura la URL del proveedor externo"
        else:
            fetched = _fetch_models(stored["base_url"], stored["api_key"])
            result.update(
                reachable=fetched["ok"],
                models=fetched["models"],
                error=fetched["error"],
                latency_ms=fetched["latency_ms"],
            )
            result["selected"] = _select_model(fetched["models"], stored["model"])
    else:
        candidates = []
        for candidate in [stored["base_url"], DEFAULT_LOCAL_URL, *FALLBACK_LOCAL_URLS]:
            normalized = _normalize_base(candidate)
            if normalized and normalized not in candidates:
                candidates.append(normalized)
        for base in candidates:
            fetched = _fetch_models(base)
            result["tried"].append({"base_url": base, "ok": fetched["ok"], "error": fetched["error"]})
            if fetched["ok"] and fetched["models"]:
                result.update(
                    base_url=base,
                    reachable=True,
                    models=fetched["models"],
                    error=None,
                    latency_ms=fetched["latency_ms"],
                )
                result["selected"] = _select_model(fetched["models"], stored["model"])
                break
        if not result["reachable"]:
            result["error"] = (
                result["tried"][-1]["error"] if result["tried"] else "No se encontró llama.cpp"
            )

    # Auto-guardar la URL/modelo detectados para no volver a fallar en cada petición.
    if provider == "local" and result["reachable"]:
        data = STORE.load() or {}
        changed = (
            data.get("provider") != "local"
            or _normalize_base(data.get("base_url", "")) != result["base_url"]
            or data.get("model") != result["selected"]
        )
        if changed:
            data.update(
                provider="local",
                base_url=result["base_url"],
                api_key="",
                model=result["selected"],
                updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            )
            STORE.save(data)

    _cache.update(ts=now, provider=cache_key, data=result)
    return result


def is_configured() -> bool:
    data = discover()
    return bool(data["reachable"] and data["selected"])


def _circuit_open() -> bool:
    return time.monotonic() < _state["disabled_until"]


def _note_failure(message: str = "") -> None:
    _state["fails"] += 1
    _state["last_error"] = message
    if _state["fails"] >= MAX_FAILS:
        _state["disabled_until"] = time.monotonic() + COOLDOWN_SECONDS
        _state["fails"] = 0
        if not _state["warned"]:
            logger.warning("IA local desactivada temporalmente (%ss)", COOLDOWN_SECONDS)
            _state["warned"] = True


def _note_success() -> None:
    _state["fails"] = 0
    _state["warned"] = False
    _state["last_error"] = ""


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


def _encode(image: Image.Image, max_side: int) -> str:
    img = image.convert("RGB")
    width, height = img.size
    if max(width, height) > max_side:
        scale = max_side / max(width, height)
        img = img.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _payload(image: Image.Image, model: str, max_side: int, max_tokens: int) -> dict:
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": prompts.OCR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompts.OCR_USER_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{_encode(image, max_side)}"},
                    },
                ],
            },
        ],
    }


def _post_chat(base_url: str, api_key: str, payload: dict, timeout: float) -> tuple:
    try:
        with httpx.Client(timeout=timeout) as client:
            res = client.post(
                f"{base_url}/chat/completions",
                headers={"Content-Type": "application/json", **_auth_headers(api_key)},
                json=payload,
            )
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"[:240], 0
    if res.status_code >= 400:
        return None, f"HTTP {res.status_code}: {res.text[:240]}", res.status_code
    try:
        return res.json(), None, res.status_code
    except ValueError:
        return None, "Respuesta no JSON del servidor", res.status_code


def ocr_page(pil_image: Image.Image, model: str = "") -> dict | None:
    settings = _settings()
    discovery = discover() if settings["provider"] == "local" else None
    base_url = discovery["base_url"] if discovery else settings["base_url"]
    selected = model or (discovery["selected"] if discovery else settings["model"])
    api_key = settings["api_key"]
    if not (base_url and selected):
        _state["last_error"] = "No hay modelo de IA disponible"
        return None
    if _circuit_open():
        return None

    last_error = ""
    for attempt, max_side in enumerate((MAX_IMAGE_SIDE, RETRY_IMAGE_SIDE)):
        if attempt:
            logger.info("Reintentando IA con imagen de %spx", max_side)
        payload = _payload(pil_image, selected, max_side, MAX_TOKENS)
        data, error, status = _post_chat(base_url, api_key, payload, settings["timeout"])
        if error:
            last_error = error
            # Un 500 puede ser el assert de visión de llama.cpp; probar más pequeño una vez.
            if status == 500 and attempt == 0:
                continue
            break
        try:
            choice = data["choices"][0]
            message = choice.get("message") or {}
            content = message.get("content") or ""
            reasoning = message.get("reasoning_content") or ""
            finish = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError):
            last_error = "Respuesta de IA con formato inesperado"
            break
        parsed = _parse_json(content) or _parse_json(reasoning)
        if isinstance(parsed, dict):
            _note_success()
            return {field: str(parsed.get(field, "") or "").strip() for field in prompts.FIELDS}
        if finish == "length" and attempt == 0:
            last_error = "La IA agotó tokens antes de devolver JSON"
            # Reintentar con el doble de presupuesto y la imagen pequeña.
            payload = _payload(pil_image, selected, RETRY_IMAGE_SIDE, MAX_TOKENS * 2)
            data, error, status = _post_chat(base_url, api_key, payload, settings["timeout"])
            if error:
                last_error = error
                break
            try:
                message = data["choices"][0]["message"]
            except (KeyError, IndexError, TypeError):
                break
            parsed = _parse_json(message.get("content") or "") or _parse_json(
                message.get("reasoning_content") or ""
            )
            if isinstance(parsed, dict):
                _note_success()
                return {field: str(parsed.get(field, "") or "").strip() for field in prompts.FIELDS}
        last_error = "La IA no devolvió JSON válido"
        break

    _note_failure(last_error)
    logger.warning("IA local falló: %s", last_error)
    return None


def health() -> dict:
    discovery = discover()
    return {
        "enabled": bool(discovery["reachable"] and discovery["selected"]),
        "reachable": discovery["reachable"],
        "provider": discovery["provider"],
        "base_url": discovery["base_url"],
        "model": discovery["selected"],
        "models": discovery["models"],
        "error": discovery["error"],
        "last_error": _state["last_error"],
        "tried": discovery.get("tried", []),
    }


def providers() -> dict:
    stored = STORE.load() or {}
    active_provider = stored.get("provider") or "local"
    local = {
        "base_url": "",
        "reachable": False,
        "models": [],
        "selected": "",
        "error": None,
        "tried": [],
        "default_url": DEFAULT_LOCAL_URL,
    }
    candidates = []
    stored_local = _normalize_base(stored.get("base_url", "")) if active_provider == "local" else ""
    for candidate in [stored_local, DEFAULT_LOCAL_URL, *FALLBACK_LOCAL_URLS]:
        normalized = _normalize_base(candidate)
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    for base in candidates:
        fetched = _fetch_models(base)
        local["tried"].append({"base_url": base, "ok": fetched["ok"], "error": fetched["error"]})
        if fetched["ok"] and fetched["models"]:
            local.update(
                base_url=base,
                reachable=True,
                models=fetched["models"],
                error=None,
                latency_ms=fetched["latency_ms"],
            )
            current = stored.get("model", "") if active_provider == "local" else ""
            local["selected"] = _select_model(fetched["models"], current)
            break
    if not local["reachable"]:
        local["error"] = local["tried"][-1]["error"] if local["tried"] else "No se encontró llama.cpp"

    external = {
        "configured": active_provider == "external",
        "base_url": stored.get("base_url", "") if active_provider == "external" else "",
        "models": [],
        "selected": stored.get("model", "") if active_provider == "external" else "",
    }
    if active_provider == "external" and external["base_url"]:
        fetched = _fetch_models(
            _normalize_base(external["base_url"]), stored.get("api_key", "")
        )
        external["models"] = fetched["models"]
        external["error"] = fetched["error"]

    return {
        "local": local,
        "external": external,
        "active_provider": active_provider,
        "last_error": _state["last_error"],
    }


def probe() -> dict:
    settings = _settings()
    discovery = discover(force=True)
    base_url = discovery["base_url"]
    model = discovery["selected"]
    result = {
        "ok": False,
        "reachable": discovery["reachable"],
        "base_url": base_url,
        "model": model,
        "models": discovery["models"],
        "error": discovery["error"],
        "text_ok": False,
        "vision_ok": False,
        "latency_ms": None,
        "sample": "",
    }
    if not (base_url and model):
        return result

    text_payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 20,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": "Responde solo: OK"}],
    }
    started = time.monotonic()
    data, error, _ = _post_chat(base_url, settings["api_key"], text_payload, 120)
    result["latency_ms"] = int((time.monotonic() - started) * 1000)
    if error:
        result["error"] = error
        return result
    try:
        content = (data["choices"][0]["message"].get("content") or "").strip()
        result["text_ok"] = bool(content)
        result["sample"] = content[:120]
    except (KeyError, IndexError, TypeError):
        result["error"] = "Respuesta de texto con formato inesperado"
        return result

    vision_payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 20,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": "Responde solo: OK"},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(TINY_PNG).decode()
                }},
            ],
        }],
    }
    data, error, status = _post_chat(base_url, settings["api_key"], vision_payload, 180)
    if error:
        if status == 500:
            result["error"] = (
                "El servidor falló con la imagen. Sube ubatch-size a 2048/4096 en llama.cpp. "
                + error
            )
        else:
            result["error"] = error
        return result
    try:
        result["vision_ok"] = bool((data["choices"][0]["message"].get("content") or "").strip())
    except (KeyError, IndexError, TypeError):
        result["vision_ok"] = False
    result["ok"] = result["text_ok"] and result["vision_ok"]
    return result
