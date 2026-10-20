import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .settings_store import DATA_DIR

DB_PATH = Path(os.environ.get("OCR_DB_PATH", str(DATA_DIR / "ocr.db")))

_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'usuario',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS sessions(
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen TEXT,
    ip TEXT,
    user_agent TEXT
);

CREATE TABLE IF NOT EXISTS documents(
    id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    kind TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs(
    id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    filename TEXT,
    file_path TEXT,
    kind TEXT,
    engine TEXT,
    params_json TEXT,
    headers_json TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    total_pages INTEGER NOT NULL DEFAULT 0,
    row_count INTEGER NOT NULL DEFAULT 0,
    extractor TEXT,
    ai_used INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    parent_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
    created_at TEXT,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS results(
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    field TEXT NOT NULL,
    value TEXT,
    source TEXT NOT NULL DEFAULT 'regex',
    updated_by INTEGER,
    updated_at TEXT,
    PRIMARY KEY(job_id, page, field)
);

CREATE TABLE IF NOT EXISTS job_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT
);

CREATE TABLE IF NOT EXISTS audit(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS app_settings(
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_documents_user ON documents(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_results_job_field ON results(job_id, field);
"""


def get_conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA foreign_keys=ON")
        return _conn


@contextmanager
def transaction():
    """Agrupa varias operaciones en una sola transacción SQLite."""
    with _lock:
        conn = get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def init_db() -> None:
    with _lock:
        conn = get_conn()
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    if "parent_id" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN parent_id TEXT")
    if "document_id" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN document_id TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_parent ON jobs(parent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_document ON jobs(document_id)")

    # Migración: cada archivo fuente existente se convierte en un documento
    # independiente del trabajo OCR. Así borrar un trabajo no borra el PDF.
    rows = conn.execute(
        "SELECT * FROM jobs WHERE engine<>'gt' AND file_path IS NOT NULL "
        "AND file_path<>'' AND document_id IS NULL ORDER BY created_at"
    ).fetchall()
    by_path = {}
    for row in rows:
        path = row["file_path"]
        doc_id = by_path.get(path)
        if not doc_id:
            found = conn.execute(
                "SELECT id FROM documents WHERE file_path=? LIMIT 1", (path,)
            ).fetchone()
            if found:
                doc_id = found["id"]
            else:
                doc_id = str(uuid.uuid4())
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = 0
                conn.execute(
                    "INSERT INTO documents(id, user_id, filename, file_path, kind, size, created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (doc_id, row["user_id"], row["filename"], path, row["kind"] or "pdf",
                     size, row["created_at"] or datetime.now(timezone.utc).isoformat(timespec="seconds")),
                )
            by_path[path] = doc_id
        conn.execute("UPDATE jobs SET document_id=? WHERE id=?", (doc_id, row["id"]))


def query(sql: str, params=()) -> list:
    with _lock:
        cursor = get_conn().execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def query_one(sql: str, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params=()) -> int:
    with _lock:
        conn = get_conn()
        cursor = conn.execute(sql, params)
        conn.commit()
        return cursor.lastrowid


def executemany(sql: str, seq) -> None:
    with _lock:
        conn = get_conn()
        conn.executemany(sql, seq)
        conn.commit()


def set_setting(key: str, value) -> None:
    import json
    execute(
        "INSERT INTO app_settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )


def get_setting(key: str, default=None):
    import json
    row = query_one("SELECT value FROM app_settings WHERE key=?", (key,))
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except (ValueError, TypeError):
        return default


def audit(user_id, action: str, target: str = "", detail: str = "") -> None:
    from datetime import datetime, timezone
    execute(
        "INSERT INTO audit(user_id, ts, action, target, detail) VALUES(?,?,?,?,?)",
        (user_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), action, target, detail),
    )
