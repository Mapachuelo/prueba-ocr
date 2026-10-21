import csv
import json
import logging
import os
import queue
import threading
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from . import db
from .settings_store import STORE

log = logging.getLogger("jobs")

UPLOAD_DIR = STORE.base_dir / "uploads"
DOWNLOAD_DIR = STORE.base_dir / "downloads"
PAGES_DIR = STORE.base_dir / "pages"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
PAGES_DIR.mkdir(parents=True, exist_ok=True)

CEDULA_FIELDS = [
    "numero", "apellidos", "nombres", "fecha_nacimiento", "lugar_nacimiento",
    "rh", "sexo", "estatura", "fecha_expedicion", "lugar_expedicion",
]
CEDULA_HEADERS = [
    "Página", "Cédula", "Apellidos", "Nombres",
    "Fecha_Nacimiento", "Lugar_Nacimiento",
    "RH", "Sexo", "Estatura",
    "Fecha_Expedición", "Lugar_Expedición",
    "OCR_Raw",
]
FIELD_LABELS = {
    "numero": "Cédula",
    "apellidos": "Apellidos",
    "nombres": "Nombres",
    "fecha_nacimiento": "Fecha de nacimiento",
    "lugar_nacimiento": "Lugar de nacimiento",
    "rh": "RH",
    "sexo": "Sexo",
    "estatura": "Estatura",
    "fecha_expedicion": "Fecha de expedición",
    "lugar_expedicion": "Lugar de expedición",
    "OCR_Raw": "Texto OCR",
}
MONTHS = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]

_queue: "queue.Queue[str]" = queue.Queue()
_cancel: set = set()
_workers_started = False


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------ configuración

def ocr_defaults() -> dict:
    return {
        "profile": db.get_setting("ocr_profile", os.environ.get("OCR_PROFILE", "cand")),
        "dpi": int(db.get_setting("ocr_dpi", int(os.environ.get("OCR_DPI", "200")))),
        "workers": int(db.get_setting("ocr_workers", int(os.environ.get("OCR_WORKERS", "1")))),
    }


def set_ocr_defaults(profile=None, dpi=None, workers=None) -> dict:
    if profile is not None:
        if profile not in ("legacy", "cand"):
            raise HTTPException(400, "Perfil OCR no válido")
        db.set_setting("ocr_profile", profile)
    if dpi is not None:
        try:
            dpi = int(dpi)
        except (TypeError, ValueError):
            raise HTTPException(400, "DPI no válido")
        if dpi not in (150, 200, 300, 400):
            raise HTTPException(400, "DPI debe ser 150, 200, 300 o 400")
        db.set_setting("ocr_dpi", dpi)
    if workers is not None:
        try:
            workers = max(1, min(4, int(workers)))
        except (TypeError, ValueError):
            raise HTTPException(400, "Workers no válido")
        db.set_setting("ocr_workers", workers)
    return ocr_defaults()


# ---------------------------------------------------------------- worker

def start_workers() -> None:
    global _workers_started
    if _workers_started:
        return
    # La cola en memoria no sobrevive a un reinicio. Los trabajos que quedaron
    # encolados o procesándose no pueden continuar: se marcan como interrumpidos.
    db.execute(
        "UPDATE jobs SET status='error', "
        "error=COALESCE(error, 'Interrumpido por reinicio del servidor'), "
        "finished_at=? WHERE status IN ('queued', 'processing')",
        (now(),),
    )
    for i in range(max(1, ocr_defaults()["workers"])):
        threading.Thread(target=_worker, daemon=True, name=f"ocr-worker-{i}").start()
    _workers_started = True


def _worker() -> None:
    while True:
        job_id = _queue.get()
        try:
            run_job(job_id)
        except Exception:
            log.exception("Error procesando job %s", job_id)
        finally:
            _queue.task_done()


def enqueue(job_id: str) -> None:
    _queue.put(job_id)


def is_cancelled(job_id: str) -> bool:
    return job_id in _cancel


def cancel_job(job_id: str, user: dict | None = None) -> None:
    job = _require_job(job_id, user)
    _cancel.add(job_id)
    if job["status"] == "queued":
        _set_status(job_id, status="cancelled", finished_at=now())
    _event(job_id, "warning", "Cancelación solicitada")


def _set_status(job_id: str, **fields) -> None:
    if not fields:
        return
    columns = ", ".join(f"{key}=?" for key in fields)
    db.execute(f"UPDATE jobs SET {columns} WHERE id=?", (*fields.values(), job_id))


def _event(job_id: str, level: str, message: str) -> None:
    db.execute(
        "INSERT INTO job_events(job_id, ts, level, message) VALUES(?,?,?,?)",
        (job_id, now(), level, message),
    )


# ------------------------------------------------------------- creación

def clean_display_name(name: str, original_filename: str,
                       allowed_extensions=None) -> str:
    original = Path(original_filename or "documento").name
    value = (name or "").strip().replace("\x00", "")
    value = Path(value).name.replace("/", "-").replace("\\", "-").strip()
    if not value:
        raise ValueError("Escribe un nombre para el documento")
    extension = Path(value).suffix.lower()
    allowed = tuple(item.lower() for item in (allowed_extensions or [Path(original).suffix]))
    if not extension:
        expected = " o ".join(allowed)
        raise ValueError(f"El nombre debe incluir la extensión {expected}")
    if allowed and extension not in allowed:
        expected = " o ".join(allowed)
        raise ValueError(f"El nombre debe terminar en {expected}")
    stem = Path(value).stem.strip()
    if not stem:
        raise ValueError("Escribe un nombre para el documento")
    if len(value) > 120:
        value = Path(value).stem[: max(1, 120 - len(extension))] + extension
    return value


def _insert_job(job_id, user_id, document_id, filename, original_filename, file_path,
                kind, engine, params, parent_id=None):
    db.execute(
        "INSERT INTO jobs(id, user_id, document_id, filename, original_filename, file_path, kind, engine, params_json, "
        "headers_json, status, created_at, parent_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (job_id, user_id, document_id, filename, original_filename, file_path, kind, engine,
         json.dumps(params or {}, ensure_ascii=False), json.dumps(CEDULA_HEADERS),
         "queued", now(), parent_id),
    )


def _insert_document(document_id: str, user_id: int, filename: str, original_filename: str,
                     file_path: Path, kind: str, size: int) -> None:
    db.execute(
        "INSERT INTO documents(id, user_id, filename, original_filename, file_path, kind, size, created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (document_id, user_id, filename, original_filename, str(file_path), kind, size, now()),
    )


def _create_jobs(document_id: str, user_id: int, filename: str, original_filename: str,
                 file_path: str, kind: str, engine: str, params: dict) -> str:
    if engine not in ("local", "ai", "compare"):
        raise HTTPException(400, "Motor no válido")
    params = params or {}
    if kind == "excel" and engine == "ai":
        engine = "local"
    job_id = str(uuid.uuid4())
    if engine == "compare":
        _insert_job(job_id, user_id, document_id, filename, original_filename,
                    file_path, kind, "compare", params)
        for child_engine in ("local", "ai"):
            child_id = str(uuid.uuid4())
            child_params = dict(params, parent=job_id, hidden=True)
            _insert_job(child_id, user_id, document_id, filename, original_filename,
                        file_path, kind, child_engine, child_params, parent_id=job_id)
            enqueue(child_id)
        _event(job_id, "info", "Job de comparación creado (local + IA)")
        return job_id

    _insert_job(job_id, user_id, document_id, filename, original_filename,
                file_path, kind, engine, params)
    enqueue(job_id)
    return job_id


def create_upload_job(user_id: int, filename: str, content: bytes, kind: str, engine: str,
                      params: dict, display_name: str = "", original_filename: str = "") -> str:
    if kind not in ("pdf", "excel"):
        raise HTTPException(400, "Tipo de archivo no soportado")
    if engine not in ("local", "ai", "compare"):
        raise HTTPException(400, "Motor no válido")
    original = Path(original_filename or filename or "documento").name
    allowed = (".pdf",) if kind == "pdf" else (".xlsx", ".xls")
    display = clean_display_name(display_name or filename, original, allowed)
    ext = ".pdf" if kind == "pdf" else Path(original).suffix.lower()
    document_id = str(uuid.uuid4())
    file_path = UPLOAD_DIR / f"{document_id}{ext}"
    file_path.write_bytes(content)
    _insert_document(document_id, user_id, display, original, file_path, kind, len(content))
    return _create_jobs(document_id, user_id, display, original, str(file_path), kind, engine, params)


def create_job_from_document(document_id: str, user_id: int, engine: str,
                             params: dict | None = None, user: dict | None = None) -> str:
    document = _require_document(document_id, user)
    path = Path(document["file_path"])
    if not path.exists():
        raise HTTPException(410, "El documento original ya no está disponible")
    return _create_jobs(document["id"], user_id, document["filename"],
                        document.get("original_filename") or document["filename"],
                        str(path), document["kind"], engine, params or {})


def retry_job(job_id: str, user_id: int, engine: str = None, user: dict | None = None) -> str:
    job = _require_job(job_id, user)
    if job["engine"] == "gt":
        raise HTTPException(400, "El ground truth no se puede reprocesar")
    engine = engine or job["engine"]
    if engine not in ("local", "ai", "compare"):
        raise HTTPException(400, "Motor no válido")
    if job.get("document_id"):
        params = json.loads(job["params_json"] or "{}")
        params.pop("parent", None)
        params.pop("hidden", None)
        return create_job_from_document(job["document_id"], user_id, engine, params, user=user)
    path = Path(job["file_path"])
    if not path.exists():
        raise HTTPException(410, "El archivo original ya no está disponible")
    params = json.loads(job["params_json"] or "{}")
    params.pop("parent", None)
    params.pop("hidden", None)
    return create_upload_job(
        user_id, job.get("original_filename") or job["filename"], path.read_bytes(),
        job["kind"], engine, params, display_name=job["filename"],
        original_filename=job.get("original_filename") or job["filename"],
    )


# ------------------------------------------------------------ ejecución

def run_job(job_id: str) -> None:
    job = db.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not job:
        return
    if job_id in _cancel:
        _cancel.discard(job_id)
        _set_status(job_id, status="cancelled", finished_at=now())
        return
    params = json.loads(job["params_json"] or "{}")
    _set_status(job_id, status="processing", started_at=now(), progress=0, error=None)
    _event(job_id, "info", "Procesando")
    try:
        if job["kind"] == "excel":
            _run_excel(job, params)
        else:
            _run_pdf(job, params)
        if is_cancelled(job_id):
            _set_status(job_id, status="cancelled", finished_at=now())
            _event(job_id, "warning", "Job cancelado")
        else:
            _set_status(job_id, status="done", progress=100, finished_at=now())
            _event(job_id, "info", "Completado")
    except Exception as exc:  # noqa: BLE001
        log.exception("Job %s falló", job_id)
        _set_status(job_id, status="error", error=str(exc), finished_at=now())
        _event(job_id, "error", str(exc))
    finally:
        _cancel.discard(job_id)
        parent = job.get("parent_id")
        if parent:
            _refresh_parent(parent)


def _run_excel(job: dict, params: dict) -> None:
    from .excel_handler import read_excel

    job_id = job["id"]
    data = read_excel(job["file_path"])
    headers = data.get("headers") or []
    rows = data.get("rows") or []
    db.execute("UPDATE jobs SET headers_json=? WHERE id=?", (json.dumps(headers), job_id))
    db.execute("DELETE FROM results WHERE job_id=?", (job_id,))
    _set_status(job_id, total_pages=len(rows))
    sources = {header: "excel" for header in headers}
    for index, row in enumerate(rows, 1):
        if is_cancelled(job_id):
            return
        values = {header: (row[i] if i < len(row) else "") for i, header in enumerate(headers)}
        _store_row(job_id, index, values, sources)
        if index % 10 == 0 or index == len(rows):
            _set_status(job_id, progress=int(index * 100 / max(len(rows), 1)))
    _set_status(job_id, row_count=len(rows), extractor="excel", progress=100)


def _run_pdf(job: dict, params: dict) -> None:
    from pdf2image import convert_from_path

    from . import ai_ocr, ocr_engine
    from .cedula_extractor import extract_from_pdf_page

    job_id = job["id"]
    engine = job["engine"]
    defaults = ocr_defaults()
    profile = params.get("profile") or defaults["profile"]
    dpi = int(params.get("dpi") or defaults["dpi"])
    ocr_engine.set_profile(profile)

    _event(job_id, "info", f"Convirtiendo PDF a {dpi} dpi")
    images = convert_from_path(job["file_path"], dpi=dpi)
    selected = parse_pages(params.get("pages"), len(images))
    total = len(selected)
    _set_status(job_id, total_pages=total, progress=0)
    db.execute("DELETE FROM results WHERE job_id=?", (job_id,))

    ai_available = engine == "ai" and ai_ocr.is_configured()
    if engine == "ai" and not ai_available:
        _event(job_id, "warning", "IA local no configurada o no disponible: se usa el motor local")

    ai_used = False
    ai_disabled = False
    sources_default = {field: "regex" for field in CEDULA_FIELDS}
    for index, page_num in enumerate(selected, 1):
        if is_cancelled(job_id):
            return
        image = images[page_num - 1]
        fields = None
        sources = dict(sources_default)
        if ai_available and not ai_disabled:
            ai_fields = ai_ocr.ocr_page(image, model=params.get("model") or "")
            if ai_fields:
                fields = ai_fields
                sources = {field: "ai" for field in CEDULA_FIELDS}
                ai_used = True
            else:
                detail = ai_ocr.last_error()
                message = f"Página {page_num}: la IA falló, se usa OCR local"
                if detail:
                    message += f" ({detail})"
                _event(job_id, "warning", message)
                if any(code in detail for code in ("HTTP 401", "HTTP 402", "HTTP 403", "FreeTier", "Insufficient")):
                    ai_disabled = True
                    _event(job_id, "warning", "IA desactivada para este trabajo; se usará OCR local en las páginas restantes")
        if fields is None:
            data = extract_from_pdf_page(image, page_num)
            fields = {field: data.get(field, "") for field in CEDULA_FIELDS}
            sources.update(data.get("_field_sources") or {})
            raw = data.get("_ocr_raw", "")
        else:
            raw = ""
        row = dict(fields)
        row["OCR_Raw"] = raw[:900]
        sources["OCR_Raw"] = sources.get("OCR_Raw", "regex")
        _store_row(job_id, page_num, row, sources)
        _set_status(job_id, progress=int(index * 100 / max(total, 1)))
        _event(job_id, "info", f"Página {page_num} procesada ({index}/{total})")

    extractor = "cedula_v3_vlm" if ai_used else f"cedula_v2_tesseract_{profile}"
    _set_status(job_id, row_count=len(selected), ai_used=1 if ai_used else 0,
                extractor=extractor, progress=100)


def _store_row(job_id: str, page: int, values: dict, sources: dict) -> None:
    ts = now()
    rows = [
        (job_id, page, field, str(value or ""), sources.get(field, "regex"), None, ts)
        for field, value in values.items()
    ]
    db.executemany(
        "INSERT OR REPLACE INTO results(job_id, page, field, value, source, updated_by, updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        rows,
    )


def _refresh_parent(parent_id: str) -> None:
    children = db.query("SELECT * FROM jobs WHERE parent_id=?", (parent_id,))
    if not children:
        return
    finished = all(child["status"] in ("done", "error", "cancelled") for child in children)
    any_done = any(child["status"] == "done" for child in children)
    progress = sum(child["progress"] for child in children) // len(children)
    row_count = sum(child["row_count"] for child in children)
    total_pages = max((child["total_pages"] for child in children), default=0)
    if not finished:
        _set_status(parent_id, status="processing", progress=progress)
    else:
        _set_status(parent_id, status="done" if any_done else "error",
                    progress=100 if any_done else progress, row_count=row_count,
                    total_pages=total_pages, finished_at=now())


# --------------------------------------------------------------- consultas

def parse_pages(spec, total: int) -> list:
    if not spec or spec == "all":
        return list(range(1, total + 1))
    pages = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            try:
                pages.update(range(int(start), int(end) + 1))
            except ValueError:
                continue
        else:
            try:
                pages.add(int(part))
            except ValueError:
                continue
    return sorted(page for page in pages if 1 <= page <= total)


def can_access(job: dict, user: dict | None) -> bool:
    if not user or user.get("role") == "admin":
        return True
    if job.get("engine") == "gt":
        return True
    return job.get("user_id") == user.get("id")


def _require_job(job_id: str, user: dict | None = None) -> dict:
    job = db.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not job or not can_access(job, user):
        raise HTTPException(404, "Job no encontrado")
    return job


def _children(job_id: str) -> list:
    return db.query(
        "SELECT * FROM jobs WHERE parent_id=? ORDER BY engine", (job_id,)
    )


def can_access_document(document: dict, user: dict | None) -> bool:
    if not user:
        return False
    if user.get("role") == "admin":
        return True
    return document.get("user_id") == user.get("id")


def _require_document(document_id: str, user: dict | None = None) -> dict:
    document = db.query_one("SELECT * FROM documents WHERE id=?", (document_id,))
    if not document or not can_access_document(document, user):
        raise HTTPException(404, "Documento no encontrado")
    return document


def public_document(document: dict) -> dict:
    jobs = db.query(
        "SELECT id, engine, status, created_at FROM jobs WHERE document_id=? AND parent_id IS NULL "
        "ORDER BY created_at DESC", (document["id"],)
    )
    last = jobs[0] if jobs else None
    return {
        "id": document["id"],
        "filename": document["filename"],
        "original_filename": document.get("original_filename") or document["filename"],
        "kind": document["kind"],
        "size": document["size"],
        "created_at": document["created_at"],
        "user": document.get("username"),
        "job_count": len(jobs),
        "last_job": {
            "id": last["id"], "engine": last["engine"], "status": last["status"],
            "created_at": last["created_at"],
        } if last else None,
    }


def list_documents(user: dict | None = None, limit: int = 50) -> list:
    limit = max(1, min(limit, 200))
    base = (
        "SELECT d.*, u.username FROM documents d LEFT JOIN users u ON u.id=d.user_id "
    )
    if user is not None and user.get("role") != "admin":
        rows = db.query(
            base + "WHERE d.user_id=? ORDER BY d.created_at DESC LIMIT ?",
            (user["id"], limit),
        )
    else:
        rows = db.query(base + "ORDER BY d.created_at DESC LIMIT ?", (limit,))
    return [public_document(row) for row in rows]


def rename_document(document_id: str, display_name: str, user: dict | None = None) -> str:
    document = _require_document(document_id, user)
    allowed = (".pdf",) if document["kind"] == "pdf" else (".xlsx", ".xls")
    name = clean_display_name(
        display_name, document.get("original_filename") or document["filename"], allowed,
    )
    db.execute("UPDATE documents SET filename=? WHERE id=?", (name, document_id))
    db.execute("UPDATE jobs SET filename=? WHERE document_id=?", (name, document_id))
    return name


def delete_document(document_id: str, user: dict | None = None) -> None:
    document = _require_document(document_id, user)
    jobs = db.query("SELECT id, status FROM jobs WHERE document_id=?", (document_id,))
    if any(job["status"] in ("queued", "processing") for job in jobs):
        raise HTTPException(400, "Espera a que terminen o cancela los trabajos del documento")
    for job in jobs:
        _cancel.discard(job["id"])
    db.execute("DELETE FROM jobs WHERE document_id=?", (document_id,))
    db.execute("DELETE FROM documents WHERE id=?", (document_id,))
    _remove_page_cache(document_id)
    path = document.get("file_path")
    if path and Path(path).exists() and UPLOAD_DIR in Path(path).parents:
        try:
            Path(path).unlink()
        except OSError:
            pass


def public_job(job: dict, with_children: bool = False) -> dict:
    result = {
        "id": job["id"],
        "document_id": job.get("document_id"),
        "filename": job["filename"],
        "original_filename": job.get("original_filename") or job["filename"],
        "kind": job["kind"],
        "engine": job["engine"],
        "status": job["status"],
        "progress": job["progress"],
        "total_pages": job["total_pages"],
        "row_count": job["row_count"],
        "extractor": job["extractor"],
        "ai_used": bool(job["ai_used"]),
        "error": job["error"],
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "user": job.get("username"),
        "params": json.loads(job.get("params_json") or "{}"),
    }
    if with_children:
        result["children"] = [
            {
                "id": child["id"],
                "engine": child["engine"],
                "status": child["status"],
                "progress": child["progress"],
                "row_count": child["row_count"],
                "ai_used": bool(child["ai_used"]),
            }
            for child in _children(job["id"])
        ]
    return result


def list_jobs(filters: dict, page: int = 1, size: int = 20, user: dict | None = None) -> dict:
    sql = (
        "SELECT j.*, u.username FROM jobs j LEFT JOIN users u ON u.id=j.user_id "
        "WHERE j.parent_id IS NULL"
    )
    rows = db.query(sql)
    scoped = user is not None and user.get("role") != "admin"
    if scoped:
        rows = [row for row in rows if row["user_id"] == user["id"]]
    rows = [row for row in rows if row["engine"] != "gt" or filters.get("include_gt")]
    if filters.get("status"):
        rows = [row for row in rows if row["status"] == filters["status"]]
    if filters.get("engine"):
        rows = [row for row in rows if row["engine"] == filters["engine"]]
    if filters.get("kind"):
        rows = [row for row in rows if row["kind"] == filters["kind"]]
    if filters.get("user_id"):
        rows = [row for row in rows if row["user_id"] == int(filters["user_id"])]
    if filters.get("q"):
        needle = normalize(filters["q"])
        rows = [row for row in rows if needle in normalize(row["filename"] or "")]
    if filters.get("date_from"):
        rows = [row for row in rows if (row["created_at"] or "") >= filters["date_from"]]
    if filters.get("date_to"):
        rows = [row for row in rows if (row["created_at"] or "")[:10] <= filters["date_to"][:10]]
    rows.sort(key=lambda row: row["created_at"] or "", reverse=True)
    for row in rows:
        if row["engine"] == "compare":
            _refresh_parent_if_stale(row)
            refreshed = db.query_one("SELECT * FROM jobs WHERE id=?", (row["id"],))
            if refreshed:
                row.update(refreshed)
    total = len(rows)
    start = (page - 1) * size
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [public_job(row) for row in rows[start:start + size]],
    }


def _refresh_parent_if_stale(row: dict) -> None:
    children = _children(row["id"])
    if children and any(child["status"] in ("processing", "done", "error") for child in children):
        if row["status"] not in ("done", "error", "cancelled"):
            _refresh_parent(row["id"])


def get_job(job_id: str, user: dict | None = None) -> dict:
    job = _require_job(job_id, user)
    if job["engine"] == "compare":
        _refresh_parent_if_stale(job)
        job = _require_job(job_id, user)
    return public_job(job, with_children=True)


def job_events(job_id: str, limit: int = 50, user: dict | None = None) -> list:
    _require_job(job_id, user)
    rows = db.query(
        "SELECT ts, level, message FROM job_events WHERE job_id=? ORDER BY id DESC LIMIT ?",
        (job_id, limit),
    )
    return list(reversed(rows))


def _validate_range(date_from: str, date_to: str) -> tuple:
    try:
        start = datetime.strptime(date_from, "%Y-%m-%d")
        end = datetime.strptime(date_to, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise HTTPException(400, "El rango de fechas no es válido")
    if start > end:
        raise HTTPException(400, "La fecha inicial no puede ser posterior a la final")
    return date_from, date_to + "T23:59:59"


def _range_rows(date_from: str, date_to: str, user_id=None) -> list:
    start, end = _validate_range(date_from, date_to)
    sql = (
        "SELECT * FROM jobs WHERE parent_id IS NULL AND engine<>'gt' "
        "AND created_at>=? AND created_at<=?"
    )
    params = [start, end]
    if user_id:
        sql += " AND user_id=?"
        params.append(int(user_id))
    return db.query(sql, tuple(params))


def delete_all_jobs(include_documents: bool = True) -> dict:
    rows = db.query(
        "SELECT id, document_id, status FROM jobs WHERE parent_id IS NULL AND engine<>'gt'"
    )
    active = [row for row in rows if row["status"] in ("queued", "processing")]
    if active:
        raise HTTPException(
            409,
            f"Hay {len(active)} trabajo(s) en curso; cancélalos antes de borrar todo",
        )
    documents = db.query("SELECT * FROM documents") if include_documents else []
    for row in rows:
        if not row.get("document_id"):
            _remove_page_cache(row["id"])
    db.execute("DELETE FROM jobs WHERE engine<>'gt'")
    if include_documents:
        for document in documents:
            _remove_page_cache(document["id"])
            path = document.get("file_path")
            if path and Path(path).exists() and UPLOAD_DIR in Path(path).parents:
                try:
                    Path(path).unlink()
                except OSError:
                    pass
        db.execute("DELETE FROM documents")
    return {"jobs": len(rows), "documents": len(documents) if include_documents else 0}


def bulk_delete_preview(date_from: str, date_to: str, user_id=None) -> dict:
    rows = _range_rows(date_from, date_to, user_id)
    document_ids = {row["document_id"] for row in rows if row.get("document_id")}
    users = {row["user_id"] for row in rows if row.get("user_id") is not None}
    active = [row for row in rows if row["status"] in ("queued", "processing")]
    return {
        "jobs": len(rows),
        "users": len(users),
        "documents": len(document_ids),
        "active_jobs": len(active),
        "date_from": date_from,
        "date_to": date_to,
    }


def bulk_delete_jobs(date_from: str, date_to: str, user_id=None, include_documents=False) -> dict:
    rows = _range_rows(date_from, date_to, user_id)
    active = [row for row in rows if row["status"] in ("queued", "processing")]
    if active:
        raise HTTPException(
            409,
            f"Hay {len(active)} trabajo(s) en curso en ese rango; cancélalos primero",
        )
    document_ids = {row["document_id"] for row in rows if row.get("document_id")}
    deleted = 0
    for row in rows:
        db.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
        deleted += 1
    deleted_documents = 0
    if include_documents:
        for document_id in document_ids:
            document = db.query_one("SELECT * FROM documents WHERE id=?", (document_id,))
            if not document:
                continue
            remaining = db.query_one(
                "SELECT COUNT(*) AS c FROM jobs WHERE document_id=?", (document_id,)
            )["c"]
            if remaining:
                continue
            db.execute("DELETE FROM documents WHERE id=?", (document_id,))
            _remove_page_cache(document_id)
            path = document.get("file_path")
            if path and Path(path).exists() and UPLOAD_DIR in Path(path).parents:
                try:
                    Path(path).unlink()
                except OSError:
                    pass
            deleted_documents += 1
    return {
        "jobs": deleted,
        "documents": deleted_documents,
        "date_from": date_from,
        "date_to": date_to,
        "include_documents": bool(include_documents),
    }


def _remove_page_cache(key: str) -> None:
    folder = PAGES_DIR / str(key)
    if not folder.exists():
        return
    for child in folder.glob("*"):
        try:
            child.unlink()
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        pass


def page_image(job_id: str, page: int, user: dict | None = None) -> Path:
    from pdf2image import convert_from_path

    job = _require_job(job_id, user)
    if job.get("kind") != "pdf":
        raise HTTPException(404, "Este trabajo no tiene imagen de página")
    try:
        page = int(page)
    except (TypeError, ValueError):
        raise HTTPException(400, "Página no válida")
    if page < 1:
        raise HTTPException(400, "Página no válida")
    key = job.get("document_id") or job_id
    target = PAGES_DIR / str(key) / f"{page}.jpg"
    if target.exists():
        return target
    source = Path(job.get("file_path") or "")
    if not source.exists():
        raise HTTPException(404, "El PDF original ya no está disponible")
    params = json.loads(job.get("params_json") or "{}")
    dpi = int(params.get("dpi") or ocr_defaults()["dpi"])
    try:
        images = convert_from_path(str(source), dpi=dpi, first_page=page, last_page=page)
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo generar imagen de %s página %s: %s", job_id, page, exc)
        raise HTTPException(404, "No se pudo generar la imagen de esa página")
    if not images:
        raise HTTPException(404, "No se encontró la página")
    image = images[0].convert("RGB")
    image.thumbnail((1600, 2200))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "JPEG", quality=85)
    return target


def delete_job(job_id: str, user: dict | None = None) -> None:
    job = _require_job(job_id, user)
    for child in _children(job_id):
        _cancel.discard(child["id"])
    _cancel.discard(job_id)
    # El documento y su archivo se conservan en Cargar OCR. Solo se elimina
    # el trabajo y sus resultados; el PDF se borra desde "Documentos".
    if not job.get("document_id"):
        _remove_page_cache(job_id)
    db.execute("DELETE FROM jobs WHERE id=?", (job_id,))


# --------------------------------------------------------------- resultados

def _load_cells(job_id: str) -> dict:
    rows = db.query(
        "SELECT page, field, value, source FROM results WHERE job_id=?", (job_id,)
    )
    pages: dict = {}
    for row in rows:
        page = pages.setdefault(row["page"], {"values": {}, "sources": {}})
        page["values"][row["field"]] = row["value"]
        page["sources"][row["field"]] = row["source"]
    return pages


def normalize(value) -> str:
    text = unicodedata.normalize("NFD", str(value or "").strip().upper())
    return "".join(char for char in text if unicodedata.category(char) != "Mn")


def parse_date(value: str):
    text = (value or "").strip().upper()
    for index, month in enumerate(MONTHS, 1):
        if month in text:
            parts = text.replace("-", " ").split()
            try:
                day = int(parts[0])
                year = int(parts[2])
                return datetime(year, index, day).date()
            except (ValueError, IndexError):
                return None
    return None


def _match_filters(item: dict, filters: dict) -> bool:
    values = item["values"]

    def value(field):
        return values.get(field, "") or ""

    if filters.get("page_from") and item["page"] < int(filters["page_from"]):
        return False
    if filters.get("page_to") and item["page"] > int(filters["page_to"]):
        return False
    if filters.get("pages"):
        try:
            if item["page"] not in {int(page) for page in filters["pages"]}:
                return False
        except (TypeError, ValueError):
            return False
    if filters.get("q"):
        needle = normalize(filters["q"])
        if not any(needle in normalize(val) for val in values.values()):
            return False
    for field in ("numero", "apellidos", "nombres", "lugar_nacimiento", "lugar_expedicion"):
        needle = filters.get(field)
        if needle and normalize(needle) not in normalize(value(field)):
            return False
    for field in ("rh", "sexo"):
        allowed = filters.get(field)
        if allowed:
            if isinstance(allowed, str):
                allowed = [part for part in allowed.split(",") if part]
            if normalize(value(field)) not in {normalize(option) for option in allowed}:
                return False
    if filters.get("estatura_min"):
        try:
            if int(value("estatura") or 0) < int(filters["estatura_min"]):
                return False
        except ValueError:
            return False
    if filters.get("estatura_max"):
        try:
            if int(value("estatura") or 999) > int(filters["estatura_max"]):
                return False
        except ValueError:
            return False
    for field in ("fecha_nacimiento", "fecha_expedicion"):
        date_from = filters.get(f"{field}_from")
        date_to = filters.get(f"{field}_to")
        if date_from or date_to:
            parsed = parse_date(value(field))
            if not parsed:
                return False
            if date_from:
                from_date = _parse_filter_date(date_from)
                if from_date and parsed < from_date:
                    return False
            if date_to:
                to_date = _parse_filter_date(date_to)
                if to_date and parsed > to_date:
                    return False
    if filters.get("source"):
        if filters["source"] not in item["sources"].values():
            return False
    filled = sum(1 for field in CEDULA_FIELDS if normalize(value(field)))
    level = "complete" if filled >= len(CEDULA_FIELDS) else "partial" if filled >= 5 else "incomplete"
    if filters.get("completeness") and filters["completeness"] != level:
        return False
    if filters.get("only_incomplete"):
        if all((value(field) or "").strip() for field in CEDULA_FIELDS):
            return False
    return True


def _parse_filter_date(value: str):
    text = str(value)
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    parsed = parse_date(text)
    return parsed


def _columns_for(job: dict) -> list:
    if job["kind"] == "pdf":
        return [{"key": field, "label": FIELD_LABELS.get(field, field)}
                for field in CEDULA_FIELDS + ["OCR_Raw"]]
    headers = json.loads(job["headers_json"] or "[]")
    return [{"key": header, "label": header} for header in headers]


def job_results(job_id: str, filters: dict, page: int = 1, size: int = 50,
                sort: str = None, direction: str = "asc", user: dict | None = None) -> dict:
    job = _require_job(job_id, user)
    if job["engine"] == "compare":
        raise HTTPException(400, "Usa los jobs hijos para ver resultados de una comparación")
    columns = _columns_for(job)
    cells = _load_cells(job_id)
    items = [{"page": number, **data} for number, data in sorted(cells.items())]
    items = [item for item in items if _match_filters(item, filters)]

    if filters.get("only_duplicates"):
        from collections import Counter
        counts = Counter(normalize(item["values"].get("numero")) for item in items
                         if normalize(item["values"].get("numero")))
        items = [item for item in items
                 if counts[normalize(item["values"].get("numero"))] > 1]

    if sort:
        reverse = direction == "desc"

        def sort_key(item):
            raw = item["values"].get(sort, "")
            if sort == "estatura":
                try:
                    return int(raw or 0)
                except ValueError:
                    return 0
            if sort.startswith("fecha"):
                parsed = parse_date(raw)
                return parsed.isoformat() if parsed else ""
            if sort == "pagina":
                return item["page"]
            return normalize(raw)

        items.sort(key=sort_key, reverse=reverse)

    total = len(items)
    start = (page - 1) * size
    return {
        "job": public_job(job),
        "columns": columns,
        "total": total,
        "page": page,
        "size": size,
        "rows": items[start:start + size],
    }


def update_results(job_id: str, updates: list, user_id: int, user: dict | None = None) -> int:
    _require_job(job_id, user)
    ts = now()
    rows = []
    for update in updates:
        page = int(update.get("page"))
        field = str(update.get("field") or "")
        if not field:
            continue
        rows.append((job_id, page, field, str(update.get("value") or ""), "manual", user_id, ts))
    if rows:
        db.executemany(
            "INSERT INTO results(job_id, page, field, value, source, updated_by, updated_at) "
            "VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(job_id, page, field) DO UPDATE SET value=excluded.value, "
            "source=excluded.source, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
            rows,
        )
    return len(rows)


# ---------------------------------------------------------------- comparar

def compare_jobs(base_id: str, other_id: str, filters: dict, user: dict | None = None) -> dict:
    base = _require_job(base_id, user)
    other = _require_job(other_id, user)
    base_cells = _load_cells(base_id)
    other_cells = _load_cells(other_id)
    field_filter = filters.get("field")
    page_from = int(filters.get("page_from") or 0)
    page_to = int(filters.get("page_to") or 10 ** 9)
    summary = {}
    diffs = []
    pages = sorted(base_cells)
    for page in pages:
        if page < page_from or page > page_to:
            continue
        base_page = base_cells.get(page, {"values": {}, "sources": {}})
        other_page = other_cells.get(page, {"values": {}, "sources": {}})
        for field in CEDULA_FIELDS:
            if field_filter and field != field_filter:
                continue
            stats = summary.setdefault(field, {"same": 0, "diff": 0})
            value_a = base_page["values"].get(field, "")
            value_b = other_page["values"].get(field, "")
            if normalize(value_a) == normalize(value_b):
                stats["same"] += 1
            else:
                stats["diff"] += 1
                diffs.append({
                    "page": page,
                    "field": field,
                    "a": value_a,
                    "b": value_b,
                    "a_source": base_page["sources"].get(field, ""),
                    "b_source": other_page["sources"].get(field, ""),
                })
    total = sum(stats["same"] + stats["diff"] for stats in summary.values())
    same = sum(stats["same"] for stats in summary.values())
    return {
        "base": public_job(base),
        "other": public_job(other),
        "summary": summary,
        "total_cells": total,
        "same_cells": same,
        "diff_cells": total - same,
        "diffs": diffs,
    }


# ------------------------------------------------------------------ stats

def stats(filters: dict, user: dict | None = None) -> dict:
    gt_job = db.query_one("SELECT * FROM jobs WHERE engine='gt' LIMIT 1")
    gt_cells = _load_cells(gt_job["id"]) if gt_job else {}
    engine_filter = filters.get("engine")
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    field_filter = filters.get("field")

    jobs = db.query(
        "SELECT * FROM jobs WHERE status='done' AND parent_id IS NULL "
        "AND engine IN ('local','ai') AND kind='pdf'"
    )
    if user is not None and user.get("role") != "admin":
        jobs = [job for job in jobs if job["user_id"] == user["id"]]
    elif filters.get("user_id"):
        jobs = [job for job in jobs if job["user_id"] == int(filters["user_id"])]
    if engine_filter:
        jobs = [job for job in jobs if job["engine"] == engine_filter]
    if date_from:
        jobs = [job for job in jobs if (job["created_at"] or "") >= date_from]
    if date_to:
        jobs = [job for job in jobs if (job["created_at"] or "")[:10] <= date_to[:10]]

    fields = [field_filter] if field_filter else CEDULA_FIELDS
    per_field = {field: {"ok": 0, "total": 0, "filled": 0} for field in fields}
    per_engine = {}
    completeness = {"complete": 0, "partial": 0, "incomplete": 0}
    sources = {}
    timeline = {}
    total_pages = 0
    ai_pages = 0

    for job in jobs:
        cells = _load_cells(job["id"])
        pages_in_job = 0
        for page, data in cells.items():
            pages_in_job += 1
            if job.get("ai_used"):
                ai_pages += 1
            filled = sum(1 for field in CEDULA_FIELDS if normalize(data["values"].get(field)))
            if filled >= len(CEDULA_FIELDS):
                completeness["complete"] += 1
            elif filled >= 5:
                completeness["partial"] += 1
            else:
                completeness["incomplete"] += 1
            for source in data["sources"].values():
                sources[source] = sources.get(source, 0) + 1

        total_pages += pages_in_job
        engine_stats = per_engine.setdefault(
            job["engine"], {field: {"ok": 0, "total": 0, "filled": 0} for field in fields}
        )
        day = (job["created_at"] or "")[:10]
        day_stats = timeline.setdefault(day, {"pages": 0, "ok": 0, "total": 0})
        day_stats["pages"] += pages_in_job

        for page, data in cells.items():
            expected = gt_cells.get(page, {}).get("values", {})
            for field in fields:
                got = data["values"].get(field, "")
                reference = expected.get(field, "")
                if normalize(got):
                    per_field[field]["filled"] += 1
                    engine_stats[field]["filled"] += 1
                if reference:
                    per_field[field]["total"] += 1
                    engine_stats[field]["total"] += 1
                    day_stats["total"] += 1
                    if normalize(got) == normalize(reference):
                        per_field[field]["ok"] += 1
                        engine_stats[field]["ok"] += 1
                        day_stats["ok"] += 1

    timeline_list = []
    for day in sorted(timeline):
        item = timeline[day]
        timeline_list.append({
            "date": day,
            "pages": item["pages"],
            "accuracy": round(item["ok"] * 100 / item["total"]) if item["total"] else None,
        })

    return {
        "jobs": len(jobs),
        "pages": total_pages,
        "gt_pages": len(gt_cells),
        "ai_pages": ai_pages,
        "completeness": completeness,
        "sources": sources,
        "timeline": timeline_list[-14:],
        "per_field": per_field,
        "per_engine": per_engine,
    }


# ----------------------------------------------------------------- export

def export_job(job_id: str, fmt: str, filters: dict, user: dict | None = None) -> tuple:
    from .excel_handler import table_to_xls, table_to_xlsx
    from .pdf_generator import table_to_pdf

    if fmt not in ("xlsx", "xls", "csv", "pdf"):
        raise HTTPException(400, "Formato no soportado")
    job = _require_job(job_id, user)
    data = job_results(job_id, filters, page=1, size=10 ** 9, user=user)
    columns = data["columns"]
    headers = [column["label"] for column in columns]
    rows = [
        [item["values"].get(column["key"], "") for column in columns]
        for item in data["rows"]
    ]
    output = DOWNLOAD_DIR / f"{job_id}.{fmt}"
    if fmt == "xlsx":
        table_to_xlsx(headers, rows, str(output))
    elif fmt == "xls":
        table_to_xls(headers, rows, str(output))
    elif fmt == "pdf":
        table_to_pdf(headers, rows, str(output))
    else:
        with output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)
    stem = Path(job["filename"] or job_id).stem
    return output, f"{stem}.{fmt}"
