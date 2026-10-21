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
OPENCODE_BASE_URL = os.environ.get("OPENCODE_BASE_URL", "https://opencode.ai/inference/go/openai/v1")
OPENCODE_MODELS_URL = os.environ.get("OPENCODE_MODELS_URL", "https://opencode.ai/inference/go/v1/models")
FALLBACK_LOCAL_URLS = [
    "http://host.containers.internal:9931/v1",
    "http://127.0.0.1:9931/v1",
]
PAID_PROVIDERS = ("opencode", "external")
GO_ANTHROPIC_MODELS = {
    "claude-haiku-5-5", "qwen3.8-max", "qwen3.8-flash", "qwen3.7-plus", "minimax-m3",
}


def _is_go_anthropic(base_url: str, model: str) -> bool:
    return "opencode.ai/inference/go/openai" in (base_url or "") and model in GO_ANTHROPIC_MODELS
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
        "models_url": _normalize_base(data.get("models_url", "")),
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


def _fetch_models(base_url: str, api_key: str = "", timeout: float = 4.0, models_url: str = "") -> dict:
    started = time.monotonic()
    endpoint = models_url or f"{base_url}/models"
    try:
        with httpx.Client(timeout=timeout) as client:
            headers = {"User-Agent": "ocr-pdf-excel/1.0"}
            if "opencode.ai" in endpoint:
                headers["x-opencode-session"] = "ocr-pdf-excel"
            headers.update(_auth_headers(api_key))
            res = client.get(endpoint, headers=headers)
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


def _filter_models(models: list, provider: str) -> list:
    # Los modelos terminados en -free solo se pueden usar dentro del cliente
    # OpenCode; una API externa recibe 403 FreeTierError.
    if provider == "opencode":
        return [model for model in models if not model.get("id", "").lower().endswith("-free")]
    return models


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

    if provider in PAID_PROVIDERS:
        if not stored["base_url"]:
            result["error"] = "Configura la URL del proveedor de API"
        elif provider == "opencode" and not stored["api_key"]:
            result["error"] = "Configura la API key de OpenCode"
        else:
            fetched = _fetch_models(
                stored["base_url"], stored["api_key"], models_url=stored["models_url"]
            )
            result.update(
                reachable=fetched["ok"],
                models=fetched["models"],
                error=fetched["error"],
                latency_ms=fetched["latency_ms"],
            )
            result["selected"] = _select_model(fetched["models"], stored["model"])
    else:
        # Si el admin configuró una URL propia, se respeta aunque falle: nunca
        # se sustituye en silencio por la URL interna.
        candidates = [stored["base_url"]] if stored["base_url"] else [
            DEFAULT_LOCAL_URL, *FALLBACK_LOCAL_URLS
        ]
        for candidate in candidates:
            normalized = _normalize_base(candidate)
            if normalized and normalized not in [item["base_url"] for item in result["tried"]]:
                fetched = _fetch_models(normalized)
                result["tried"].append({"base_url": normalized, "ok": fetched["ok"], "error": fetched["error"]})
                if fetched["ok"] and fetched["models"]:
                    result.update(
                        base_url=normalized,
                        reachable=True,
                        models=fetched["models"],
                        error=None,
                        latency_ms=fetched["latency_ms"],
                    )
                    result["selected"] = _select_model(fetched["models"], stored["model"])
                    break
        if not result["reachable"]:
            result["error"] = (
                result["tried"][-1]["error"] if result["tried"]
                else "No se encontró el servidor local"
            )

    # Solo se auto-guarda la URL local cuando el admin no había fijado una.
    if provider == "local" and result["reachable"]:
        data = STORE.load() or {}
        configured_url = _normalize_base(data.get("base_url", ""))
        changed = (
            (not configured_url and _normalize_base(data.get("base_url", "")) != result["base_url"])
            or data.get("model") != result["selected"]
        )
        if changed and not configured_url:
            data.update(
                provider="local",
                base_url=result["base_url"],
                models_url="",
                api_key="",
                model=result["selected"],
                updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            )
            STORE.save(data)
        elif data.get("model") != result["selected"]:
            data["model"] = result["selected"]
            STORE.save(data)

    _cache.update(ts=now, provider=cache_key, data=result)
    return result


def last_error() -> str:
    return _state.get("last_error", "")


def migrate_open_code_go() -> None:
    """Migra la configuración antigua de Console al endpoint de OpenCode Go."""
    data = STORE.load() or {}
    if data.get("provider") != "opencode":
        return
    changed = False
    base = _normalize_base(data.get("base_url", ""))
    old_console = base in (
        "https://opencode.ai/inference/openai/v1",
        "https://opencode.ai/inference/openai",
    )
    if not base or old_console:
        data["base_url"] = OPENCODE_BASE_URL
        changed = True
    models_url = _normalize_base(data.get("models_url", ""))
    if not models_url or models_url in (
        "https://opencode.ai/inference/v1/models",
        "https://opencode.ai/inference/v1",
    ):
        data["models_url"] = OPENCODE_MODELS_URL
        changed = True
    model = str(data.get("model", ""))
    if not model or model.endswith("-free"):
        data["model"] = "claude-haiku-5-5"
        changed = True
    if changed:
        data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        STORE.save(data)
        _cache["ts"] = 0.0


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


def _payload(image: Image.Image, model: str, max_side: int, max_tokens: int,
             provider: str = "local") -> dict:
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
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
    if provider == "local":
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    return payload


def _anthropic_payload(payload: dict) -> dict:
    messages = []
    system = ""
    for message in payload.get("messages", []):
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            system = content if isinstance(content, str) else ""
            continue
        if isinstance(content, str):
            blocks = [{"type": "text", "text": content}]
        else:
            blocks = []
            for block in content or []:
                if block.get("type") == "text":
                    blocks.append({"type": "text", "text": block.get("text", "")})
                elif block.get("type") == "image_url":
                    url = (block.get("image_url") or {}).get("url", "")
                    if url.startswith("data:") and "," in url:
                        header, encoded = url.split(",", 1)
                        media = header[5:].split(";", 1)[0] or "image/jpeg"
                        blocks.append({
                            "type": "image",
                            "source": {"type": "base64", "media_type": media, "data": encoded},
                        })
        messages.append({"role": "user" if role == "user" else "assistant", "content": blocks})
    body = {
        "model": payload.get("model"),
        "max_tokens": payload.get("max_tokens", 1200),
        "messages": messages,
    }
    if system:
        body["system"] = system
    return body


def _post_anthropic(base_url: str, api_key: str, payload: dict, timeout: float) -> tuple:
    url = base_url.replace("/go/openai/v1", "/go/anthropic/v1/messages")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "ocr-pdf-excel/1.0",
        "x-opencode-session": "ocr-pdf-excel",
        "anthropic-version": "2023-06-01",
        "x-api-key": api_key,
        "Authorization": f"Bearer {api_key}",
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            res = client.post(url, headers=headers, json=_anthropic_payload(payload))
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"[:240], 0
    if res.status_code >= 400:
        return None, f"HTTP {res.status_code}: {res.text[:240]}", res.status_code
    try:
        data = res.json()
    except ValueError:
        return None, "Respuesta no JSON del servidor", res.status_code
    parts = [
        block.get("text", "")
        for block in (data.get("content") or [])
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return {"choices": [{"message": {"content": "".join(parts)}}]}, None, res.status_code


def _post_chat(base_url: str, api_key: str, payload: dict, timeout: float) -> tuple:
    if _is_go_anthropic(base_url, payload.get("model", "")):
        return _post_anthropic(base_url, api_key, payload, timeout)
    try:
        with httpx.Client(timeout=timeout) as client:
            res = client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "ocr-pdf-excel/1.0",
                    "x-opencode-session": "ocr-pdf-excel",
                    **_auth_headers(api_key),
                },
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
        payload = _payload(pil_image, selected, max_side, MAX_TOKENS, settings['provider'])
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
            payload = _payload(pil_image, selected, RETRY_IMAGE_SIDE, MAX_TOKENS * 2, settings['provider'])
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
    stored_local = _normalize_base(stored.get("base_url", "")) if active_provider == "local" else ""
    candidates = [stored_local] if stored_local else [DEFAULT_LOCAL_URL, *FALLBACK_LOCAL_URLS]
    for candidate in candidates:
        normalized = _normalize_base(candidate)
        if normalized and normalized not in [item["base_url"] for item in local["tried"]]:
            fetched = _fetch_models(normalized)
            local["tried"].append({"base_url": normalized, "ok": fetched["ok"], "error": fetched["error"]})
            if fetched["ok"] and fetched["models"]:
                local.update(
                    base_url=normalized,
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
        "configured": active_provider in PAID_PROVIDERS,
        "base_url": stored.get("base_url", "") if active_provider in PAID_PROVIDERS else "",
        "models_url": stored.get("models_url", "") if active_provider in PAID_PROVIDERS else "",
        "models": [],
        "selected": stored.get("model", "") if active_provider in PAID_PROVIDERS else "",
        "error": None,
    }
    if active_provider in PAID_PROVIDERS and external["base_url"]:
        fetched = _fetch_models(
            _normalize_base(external["base_url"]), stored.get("api_key", ""),
            models_url=stored.get("models_url", ""),
        )
        external["models"] = fetched["models"]
        external["selected"] = _select_model(
            external["models"], stored.get("model", ""),
        ) if external["models"] else ""
        external["error"] = fetched["error"]
    if active_provider == "opencode" and not stored.get("api_key"):
        external["error"] = "Configura la API key de OpenCode"

    return {
        "local": local,
        "external": external,
        "active_provider": active_provider,
        "paid_provider": active_provider in PAID_PROVIDERS,
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
        "messages": [{"role": "user", "content": "Responde solo: OK"}],
    }
    if settings["provider"] == "local":
        text_payload["chat_template_kwargs"] = {"enable_thinking": False}
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
