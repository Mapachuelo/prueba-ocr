import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import HTTPException, Request, Response

from .settings_store import STORE

SESSION_COOKIE = "ocr_session"
SESSION_TTL_SECONDS = 8 * 3600
MAX_FAILS = 5
FAIL_WINDOW = 60
LOCK_SECONDS = 30

_AUTH_PATH = STORE.base_dir / "auth.json"
_fails: dict = {}
_locked: dict = {}


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _load() -> dict | None:
    if not _AUTH_PATH.exists():
        return None
    try:
        data = json.loads(_AUTH_PATH.read_text())
        return data if isinstance(data, dict) else None
    except (ValueError, OSError):
        return None


def is_setup() -> bool:
    data = _load()
    return bool(data and data.get("username") and data.get("hash") and data.get("salt"))


def create_credentials(username: str, password: str) -> str:
    if is_setup():
        raise HTTPException(409, "Ya existen credenciales")
    username = username.strip()
    if len(username) < 3 or len(username) > 32:
        raise HTTPException(400, "El usuario debe tener entre 3 y 32 caracteres")
    if len(password) < 8:
        raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres")
    salt = secrets.token_bytes(16)
    data = {
        "username": username,
        "salt": salt.hex(),
        "hash": _hash(password, salt).hex(),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    STORE.base_dir.mkdir(parents=True, exist_ok=True)
    _AUTH_PATH.write_text(json.dumps(data))
    os.chmod(_AUTH_PATH, 0o600)
    return username


def verify_credentials(username: str, password: str) -> bool:
    data = _load()
    if not data:
        return False
    if not hmac.compare_digest(username.strip(), data.get("username", "")):
        return False
    try:
        salt = bytes.fromhex(data["salt"])
        expected = bytes.fromhex(data["hash"])
    except (KeyError, ValueError):
        return False
    return hmac.compare_digest(_hash(password, salt), expected)


def create_token(username: str) -> str:
    payload = json.dumps({"u": username, "exp": int(time.time()) + SESSION_TTL_SECONDS}).encode()
    sig = hmac.new(STORE.raw_key, payload, hashlib.sha256).digest()
    return f"{_b64e(payload)}.{_b64e(sig)}"


def valid_session(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload_b64, sig_b64 = token.split(".", 1)
    try:
        payload = _b64d(payload_b64)
        sig = _b64d(sig_b64)
    except (ValueError, TypeError):
        return False
    expected = hmac.new(STORE.raw_key, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        data = json.loads(payload)
    except ValueError:
        return False
    return int(data.get("exp", 0)) > time.time()


def is_authenticated(request: Request) -> bool:
    return valid_session(request.cookies.get(SESSION_COOKIE))


def require_auth(request: Request) -> bool:
    if not is_authenticated(request):
        raise HTTPException(401, "Sesión requerida")
    return True


def check_rate_limit(ip: str) -> None:
    until = _locked.get(ip, 0)
    now = time.monotonic()
    if until > now:
        raise HTTPException(
            429,
            "Demasiados intentos fallidos. Intenta más tarde.",
            headers={"Retry-After": str(int(until - now) + 1)},
        )


def note_failure(ip: str) -> None:
    now = time.monotonic()
    attempts = [t for t in _fails.get(ip, []) if now - t < FAIL_WINDOW]
    attempts.append(now)
    if len(attempts) >= MAX_FAILS:
        _locked[ip] = now + LOCK_SECONDS
        attempts = []
    _fails[ip] = attempts


def note_success(ip: str) -> None:
    _fails.pop(ip, None)
    _locked.pop(ip, None)


def set_session(response: Response, username: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        create_token(username),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
