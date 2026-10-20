import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response

from . import db
from .settings_store import STORE

SESSION_COOKIE = "ocr_session"
SESSION_TTL_HOURS = 8
REMEMBER_TTL_DAYS = 30
MAX_FAILS = 5
FAIL_WINDOW = 60
LOCK_SECONDS = 30
ROLES = ("admin", "usuario")
PASSWORD_MIN_LENGTH = int(os.environ.get("PASSWORD_MIN_LENGTH", "4"))

_fails: dict = {}
_locked: dict = {}
log = logging.getLogger("auth")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- bootstrap

def _import_legacy_auth() -> bool:
    path = STORE.base_dir / "auth.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
        username = data["username"]
        salt = data["salt"]
        password_hash = data["hash"]
    except (ValueError, KeyError, OSError):
        return False
    db.execute(
        "INSERT INTO users(username, password_hash, salt, role, active, created_at) "
        "VALUES(?,?,?,?,1,?)",
        (username, password_hash, salt, "admin", now()),
    )
    log.info("Usuario legacy importado desde auth.json: %s", username)
    return True


def _seed_ground_truth_job() -> None:
    if db.query_one("SELECT 1 FROM jobs WHERE engine='gt' LIMIT 1"):
        return
    gt_path = STORE.base_dir / "ground_truth.json"
    if not gt_path.exists():
        return
    try:
        data = json.loads(gt_path.read_text())
    except (ValueError, OSError):
        return
    pages = data.get("pages") or {}
    if not pages:
        return
    fields = data.get("fields") or [
        "numero", "apellidos", "nombres", "fecha_nacimiento", "lugar_nacimiento",
        "rh", "sexo", "estatura", "fecha_expedicion", "lugar_expedicion",
    ]
    db.execute(
        "INSERT INTO jobs(id, user_id, filename, kind, engine, status, progress, "
        "total_pages, row_count, extractor, created_at, finished_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        ("ground-truth", None, "ground_truth.json", "gt", "gt", "done", 100,
         len(pages), len(pages), "agente", now(), now()),
    )
    db.execute(
        "UPDATE jobs SET headers_json=? WHERE id=?",
        (json.dumps(fields), "ground-truth"),
    )
    rows = []
    for page, values in pages.items():
        for field, value in values.items():
            if field not in fields:
                continue
            rows.append(("ground-truth", int(page), field, str(value or ""), "agent", None, now()))
    db.executemany(
        "INSERT OR REPLACE INTO results(job_id, page, field, value, source, updated_by, updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        rows,
    )


def bootstrap() -> None:
    db.init_db()
    db.execute("UPDATE users SET role='usuario' WHERE role IN ('operador', 'lector')")
    if not is_setup():
        _import_legacy_auth()
    _seed_ground_truth_job()


# ------------------------------------------------------------------- users

def is_setup() -> bool:
    row = db.query_one("SELECT COUNT(*) AS c FROM users")
    return bool(row and row["c"] > 0)


def _create_user(username: str, password: str, role: str) -> int:
    username = (username or "").strip()
    if len(username) < 3 or len(username) > 32:
        raise HTTPException(400, "El usuario debe tener entre 3 y 32 caracteres")
    if len(password or "") < PASSWORD_MIN_LENGTH:
        raise HTTPException(400, f"La contraseña debe tener al menos {PASSWORD_MIN_LENGTH} caracteres")
    if role not in ROLES:
        raise HTTPException(400, "Rol no válido")
    if db.query_one("SELECT 1 FROM users WHERE username=?", (username,)):
        raise HTTPException(409, "El usuario ya existe")
    salt = secrets.token_bytes(16)
    user_id = db.execute(
        "INSERT INTO users(username, password_hash, salt, role, active, created_at) "
        "VALUES(?,?,?,?,1,?)",
        (username, _hash(password, salt).hex(), salt.hex(), role, now()),
    )
    return user_id


def create_first_admin(username: str, password: str) -> int:
    if is_setup():
        raise HTTPException(409, "Ya existen credenciales")
    return _create_user(username, password, "admin")


def list_users() -> list:
    return db.query(
        "SELECT id, username, role, active, created_at, last_login FROM users ORDER BY username"
    )


LAST_ADMIN_MESSAGE = "Debe existir al menos un administrador activo"


def update_user(user_id: int, role=None, active=None, password=None) -> None:
    if role is not None and role not in ROLES:
        raise HTTPException(400, "Rol no válido")
    if password and len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(400, f"La contraseña debe tener al menos {PASSWORD_MIN_LENGTH} caracteres")

    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Usuario no encontrado")
        user = dict(row)
        next_role = role if role is not None else user["role"]
        next_active = bool(active) if active is not None else bool(user["active"])
        removes_admin = (
            user["role"] == "admin" and user["active"]
            and (next_role != "admin" or not next_active)
        )
        if removes_admin:
            others = conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE role='admin' AND active=1 AND id<>?",
                (user_id,),
            ).fetchone()["c"]
            if not others:
                raise HTTPException(400, LAST_ADMIN_MESSAGE)

        if role is not None:
            conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        if active is not None:
            conn.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, user_id))
            if not active:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        if password:
            salt = secrets.token_bytes(16)
            conn.execute(
                "UPDATE users SET password_hash=?, salt=? WHERE id=?",
                (_hash(password, salt).hex(), salt.hex(), user_id),
            )
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


def delete_user(user_id: int) -> None:
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Usuario no encontrado")
        user = dict(row)
        if user["role"] == "admin" and user["active"]:
            others = conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE role='admin' AND active=1 AND id<>?",
                (user_id,),
            ).fetchone()["c"]
            if not others:
                raise HTTPException(400, LAST_ADMIN_MESSAGE)
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))


def verify_credentials(username: str, password: str):
    rows = db.query("SELECT * FROM users WHERE username=? AND active=1", ((username or "").strip(),))
    if not rows:
        return None
    user = rows[0]
    try:
        salt = bytes.fromhex(user["salt"])
        expected = bytes.fromhex(user["password_hash"])
    except ValueError:
        return None
    if not hmac.compare_digest(_hash(password or "", salt), expected):
        return None
    db.execute("UPDATE users SET last_login=? WHERE id=?", (now(), user["id"]))
    return user


def change_password(user_id: int, current: str, new: str) -> None:
    user = db.query_one("SELECT * FROM users WHERE id=?", (user_id,))
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    salt = bytes.fromhex(user["salt"])
    if not hmac.compare_digest(_hash(current or "", salt), bytes.fromhex(user["password_hash"])):
        raise HTTPException(401, "Contraseña actual incorrecta")
    if len(new or "") < PASSWORD_MIN_LENGTH:
        raise HTTPException(400, f"La nueva contraseña debe tener al menos {PASSWORD_MIN_LENGTH} caracteres")
    new_salt = secrets.token_bytes(16)
    db.execute(
        "UPDATE users SET password_hash=?, salt=? WHERE id=?",
        (_hash(new, new_salt).hex(), new_salt.hex(), user_id),
    )


# ---------------------------------------------------------------- sessions

def _expiry(remember: bool) -> str:
    delta = timedelta(days=REMEMBER_TTL_DAYS) if remember else timedelta(hours=SESSION_TTL_HOURS)
    return (datetime.now(timezone.utc) + delta).isoformat(timespec="seconds")


def create_session(user_id: int, request: Request, remember: bool = False) -> str:
    token = secrets.token_urlsafe(32)
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")[:200]
    db.execute(
        "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen, ip, user_agent) "
        "VALUES(?,?,?,?,?,?,?)",
        (_token_hash(token), user_id, now(), _expiry(remember), now(), ip, ua),
    )
    return token


def session_user(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    row = db.query_one(
        "SELECT s.*, u.username, u.role, u.active FROM sessions s "
        "JOIN users u ON u.id = s.user_id WHERE s.token_hash=?",
        (_token_hash(token),),
    )
    if not row or not row["active"]:
        return None
    if row["expires_at"] <= now():
        db.execute("DELETE FROM sessions WHERE token_hash=?", (row["token_hash"],))
        return None
    return {
        "id": row["user_id"],
        "username": row["username"],
        "role": row["role"],
        "token_hash": row["token_hash"],
    }


def destroy_session(request: Request) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))


def set_session_cookie(response: Response, token: str, remember: bool = False) -> None:
    max_age = REMEMBER_TTL_DAYS * 86400 if remember else SESSION_TTL_HOURS * 3600
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="strict", path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


# --------------------------------------------------------------- deps/rbac

def current_user(request: Request) -> dict:
    user = session_user(request)
    if not user:
        raise HTTPException(401, "Sesión requerida")
    return user


def require_role(*roles):
    def dependency(request: Request) -> dict:
        user = current_user(request)
        if roles and user["role"] not in roles:
            raise HTTPException(403, "No tienes permisos para esta acción")
        return user
    return dependency


# -------------------------------------------------------------- throttling

def _check_rate_limit(key: str) -> None:
    until = _locked.get(key, 0)
    now_m = time.monotonic()
    if until > now_m:
        raise HTTPException(
            429, "Demasiados intentos fallidos. Intenta más tarde.",
            headers={"Retry-After": str(int(until - now_m) + 1)},
        )


def note_failure(key: str) -> None:
    now_m = time.monotonic()
    attempts = [t for t in _fails.get(key, []) if now_m - t < FAIL_WINDOW]
    attempts.append(now_m)
    if len(attempts) >= MAX_FAILS:
        _locked[key] = now_m + LOCK_SECONDS
        attempts = []
    _fails[key] = attempts


def note_success(key: str) -> None:
    _fails.pop(key, None)
    _locked.pop(key, None)


# mantener compatibilidad con imports antiguos
require_auth = current_user
is_authenticated = lambda request: session_user(request) is not None
