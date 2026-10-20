import csv
import json
import os
import time
import uuid
import zipfile
from io import BytesIO, StringIO
from pathlib import Path
from typing import Optional

import xlwt
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from openpyxl import Workbook
from pydantic import BaseModel

from . import ai_ocr, auth, db, jobs
from .excel_handler import read_excel, table_to_xls, table_to_xlsx
from .ocr_extract import extract_table_from_pdf
from .pdf_generator import table_to_pdf
from .settings_store import STORE

app = FastAPI(title="OCR PDF to Excel")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = STORE.base_dir
UPLOAD_DIR = BASE_DIR / "uploads"
DOWNLOAD_DIR = BASE_DIR / "downloads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

OPEN_PATHS = {"/api/health", "/api/auth/status", "/api/auth/setup", "/api/auth/login"}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if (
        path.startswith("/api/")
        and path not in OPEN_PATHS
        and request.method != "OPTIONS"
    ):
        if not auth.session_user(request):
            return JSONResponse({"detail": "Sesión requerida"}, status_code=401)
        if request.method in MUTATING and request.headers.get("x-requested-with") != "XMLHttpRequest":
            return JSONResponse({"detail": "Petición no válida (CSRF)"}, status_code=403)
    return await call_next(request)


@app.on_event("startup")
async def _startup():
    auth.bootstrap()
    jobs.start_workers()


class TableData(BaseModel):
    session_id: Optional[str] = None
    headers: list[str] = []
    rows: list[list[str]] = []


class CredentialsIn(BaseModel):
    username: str
    password: str
    remember: bool = False


class PasswordChangeIn(BaseModel):
    current: str
    new: str


class UserIn(BaseModel):
    username: str
    password: str
    role: str = "usuario"


class UserPatch(BaseModel):
    role: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = None


class DocumentJobIn(BaseModel):
    engine: str = "local"
    profile: str = ""
    dpi: str = ""
    pages: str = ""
    model: str = ""


class AISettingsIn(BaseModel):
    provider: str = "local"
    api_key: str = ""
    local_path: str = ""
    base_url: str = ""
    model: str = ""


class OCRSettingsIn(BaseModel):
    profile: Optional[str] = None
    dpi: Optional[int] = None
    workers: Optional[int] = None


class ResultUpdatesIn(BaseModel):
    updates: list[dict] = []


def _filters(raw: str) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def ai_public(used: bool) -> dict:
    config = STORE.load() or {}
    return {
        "enabled": ai_ocr.is_configured(),
        "used": bool(used),
        "model": config.get("model", ""),
        "base_url": config.get("base_url", ""),
    }


# ------------------------------------------------------------------- auth

@app.get("/api/auth/status")
async def auth_status(request: Request):
    user = auth.session_user(request)
    return {
        "setup": auth.is_setup(),
        "authenticated": bool(user),
        "user": {"username": user["username"], "role": user["role"]} if user else None,
    }


@app.post("/api/auth/setup")
async def auth_setup(data: CredentialsIn, request: Request, response: Response):
    user_id = auth.create_first_admin(data.username, data.password)
    token = auth.create_session(user_id, request, data.remember)
    auth.set_session_cookie(response, token, data.remember)
    db.audit(user_id, "setup", "admin", "primer administrador creado")
    return {"ok": True, "username": data.username.strip(), "role": "admin"}


@app.post("/api/auth/login")
async def auth_login(data: CredentialsIn, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    key = f"{ip}:{(data.username or '').strip().lower()}"
    auth._check_rate_limit(key)
    user = auth.verify_credentials(data.username, data.password)
    if not user:
        auth.note_failure(key)
        db.audit(None, "login_failed", data.username or "", f"ip={ip}")
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    auth.note_success(key)
    token = auth.create_session(user["id"], request, data.remember)
    auth.set_session_cookie(response, token, data.remember)
    db.audit(user["id"], "login", user["username"], f"ip={ip}")
    return {"ok": True, "username": user["username"], "role": user["role"]}


@app.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    user = auth.session_user(request)
    auth.destroy_session(request)
    auth.clear_session_cookie(response)
    if user:
        db.audit(user["id"], "logout", user["username"])
    return {"ok": True}


@app.get("/api/auth/me", dependencies=[Depends(auth.require_auth)])
async def auth_me(user: dict = Depends(auth.require_auth)):
    return {"username": user["username"], "role": user["role"]}


@app.post("/api/auth/change-password", dependencies=[Depends(auth.require_auth)])
async def auth_change_password(data: PasswordChangeIn, user: dict = Depends(auth.require_auth)):
    auth.change_password(user["id"], data.current, data.new)
    db.audit(user["id"], "change_password", user["username"])
    return {"ok": True}


# ------------------------------------------------------------------ users

@app.get("/api/users", dependencies=[Depends(auth.require_role("admin"))])
async def get_users():
    return {"items": auth.list_users()}


@app.post("/api/users", dependencies=[Depends(auth.require_role("admin"))])
async def post_user(data: UserIn, user: dict = Depends(auth.require_role("admin"))):
    user_id = auth._create_user(data.username, data.password, data.role)
    db.audit(user["id"], "user_create", data.username, f"role={data.role}")
    return {"ok": True, "id": user_id}


@app.patch("/api/users/{user_id}", dependencies=[Depends(auth.require_role("admin"))])
async def patch_user(user_id: int, data: UserPatch, user: dict = Depends(auth.require_role("admin"))):
    if user_id == user["id"] and data.active is False:
        raise HTTPException(400, "No puedes desactivar tu propia cuenta")
    auth.update_user(user_id, role=data.role, active=data.active, password=data.password)
    db.audit(user["id"], "user_update", str(user_id),
             f"role={data.role} active={data.active} password={'set' if data.password else 'no'}")
    return {"ok": True}


@app.delete("/api/users/{user_id}", dependencies=[Depends(auth.require_role("admin"))])
async def remove_user(user_id: int, user: dict = Depends(auth.require_role("admin"))):
    if user_id == user["id"]:
        raise HTTPException(400, "No puedes eliminar tu propia cuenta")
    auth.delete_user(user_id)
    db.audit(user["id"], "user_delete", str(user_id))
    return {"ok": True}


# ------------------------------------------------------------------- jobs

@app.post("/api/jobs", dependencies=[Depends(auth.require_role("admin", "usuario"))])
async def create_job(
    file: UploadFile = File(...),
    engine: str = Form("local"),
    profile: str = Form(""),
    dpi: str = Form(""),
    pages: str = Form(""),
    model: str = Form(""),
    user: dict = Depends(auth.require_role("admin", "usuario")),
):
    if not file.filename:
        raise HTTPException(400, "Archivo no válido")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext == ".pdf":
        kind = "pdf"
    elif ext in (".xlsx", ".xls"):
        kind = "excel"
    else:
        raise HTTPException(400, "Solo se aceptan PDF, XLSX o XLS")
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(413, "El archivo supera los 50 MB")
    if kind == "pdf" and not content.startswith(b"%PDF"):
        raise HTTPException(400, "El archivo no parece un PDF válido")
    params = {}
    if profile:
        params["profile"] = profile
    if dpi:
        params["dpi"] = int(dpi)
    if pages:
        params["pages"] = pages
    if model:
        params["model"] = model
    job_id = jobs.create_upload_job(user["id"], file.filename, content, kind, engine, params)
    db.audit(user["id"], "job_create", job_id, f"{file.filename} engine={engine}")
    return {"id": job_id}


@app.get("/api/documents", dependencies=[Depends(auth.require_role("admin", "usuario"))])
async def get_documents(user: dict = Depends(auth.require_role("admin", "usuario"))):
    return {"items": jobs.list_documents(user=user)}


@app.post("/api/documents/{document_id}/jobs", dependencies=[Depends(auth.require_role("admin", "usuario"))])
async def create_document_job(document_id: str, data: DocumentJobIn,
                               user: dict = Depends(auth.require_role("admin", "usuario"))):
    params = {}
    if data.profile:
        params["profile"] = data.profile
    if data.dpi:
        try:
            params["dpi"] = int(data.dpi)
        except ValueError:
            raise HTTPException(400, "DPI no válido")
    if data.pages:
        params["pages"] = data.pages
    if data.model:
        params["model"] = data.model
    job_id = jobs.create_job_from_document(
        document_id, user["id"], data.engine, params, user=user
    )
    db.audit(user["id"], "job_create", job_id, f"document={document_id} engine={data.engine}")
    return {"id": job_id}


@app.delete("/api/documents/{document_id}", dependencies=[Depends(auth.require_role("admin", "usuario"))])
async def remove_document(document_id: str, user: dict = Depends(auth.require_role("admin", "usuario"))):
    document = jobs._require_document(document_id, user)
    jobs.delete_document(document_id, user=user)
    db.audit(user["id"], "document_delete", document_id, document["filename"])
    return {"ok": True}


@app.get("/api/jobs", dependencies=[Depends(auth.require_auth)])
async def get_jobs(filters: str = "", page: int = 1, size: int = 20,
                   user: dict = Depends(auth.require_auth)):
    parsed = _filters(filters)
    return jobs.list_jobs(parsed, page=page, size=size, user=user)


@app.get("/api/jobs/{job_id}", dependencies=[Depends(auth.require_auth)])
async def get_job(job_id: str, user: dict = Depends(auth.require_auth)):
    return jobs.get_job(job_id, user=user)


@app.get("/api/jobs/{job_id}/events", dependencies=[Depends(auth.require_auth)])
async def get_job_events(job_id: str, limit: int = 50,
                         user: dict = Depends(auth.require_auth)):
    return {"items": jobs.job_events(job_id, limit, user=user)}


@app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(auth.require_role("admin", "usuario"))])
async def cancel_job(job_id: str, user: dict = Depends(auth.require_role("admin", "usuario"))):
    jobs.cancel_job(job_id, user=user)
    db.audit(user["id"], "job_cancel", job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry", dependencies=[Depends(auth.require_role("admin", "usuario"))])
async def retry_job(job_id: str, request: Request, user: dict = Depends(auth.require_role("admin", "usuario"))):
    body = {}
    try:
        body = await request.json()
    except ValueError:
        body = {}
    new_id = jobs.retry_job(job_id, user["id"], body.get("engine"), user=user)
    db.audit(user["id"], "job_retry", new_id, f"from={job_id}")
    return {"id": new_id}


@app.delete("/api/jobs/{job_id}", dependencies=[Depends(auth.require_auth)])
async def remove_job(job_id: str, user: dict = Depends(auth.require_auth)):
    job = jobs._require_job(job_id, user)
    if job["engine"] == "gt":
        raise HTTPException(400, "El ground truth no se puede eliminar")
    jobs.delete_job(job_id, user=user)
    db.audit(user["id"], "job_delete", job_id, job["filename"])
    return {"ok": True}


@app.get("/api/jobs/{job_id}/results", dependencies=[Depends(auth.require_auth)])
async def get_job_results(job_id: str, filters: str = "", page: int = 1, size: int = 50,
                          sort: str = "", direction: str = "asc",
                          user: dict = Depends(auth.require_auth)):
    return jobs.job_results(job_id, _filters(filters), page=page, size=size,
                            sort=sort or None, direction=direction, user=user)


@app.patch("/api/jobs/{job_id}/results", dependencies=[Depends(auth.require_role("admin", "usuario"))])
async def patch_job_results(job_id: str, data: ResultUpdatesIn,
                            user: dict = Depends(auth.require_role("admin", "usuario"))):
    count = jobs.update_results(job_id, data.updates, user["id"], user=user)
    db.audit(user["id"], "results_update", job_id, f"{count} celdas")
    return {"ok": True, "updated": count}


@app.post("/api/jobs/{job_id}/export/{fmt}", dependencies=[Depends(auth.require_auth)])
async def export_job(job_id: str, fmt: str, request: Request,
                     user: dict = Depends(auth.require_auth)):
    try:
        body = await request.json()
    except ValueError:
        body = {}
    filters = body.get("filters") or {}
    path, filename = jobs.export_job(job_id, fmt, filters, user=user)
    db.audit(user["id"], "job_export", job_id, fmt)
    media = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
        "csv": "text/csv; charset=utf-8",
        "pdf": "application/pdf",
    }[fmt]
    return FileResponse(str(path), media_type=media, filename=filename)


@app.get("/api/jobs/{job_id}/compare", dependencies=[Depends(auth.require_auth)])
async def compare_job(job_id: str, other_id: str, filters: str = "",
                      user: dict = Depends(auth.require_auth)):
    return jobs.compare_jobs(job_id, other_id, _filters(filters), user=user)


@app.get("/api/ground-truth", dependencies=[Depends(auth.require_auth)])
async def ground_truth_job():
    row = db.query_one("SELECT id FROM jobs WHERE engine='gt' LIMIT 1")
    if not row:
        raise HTTPException(404, "No hay ground truth cargado")
    return jobs.get_job(row["id"])


# ------------------------------------------------------------------ stats

@app.get("/api/stats", dependencies=[Depends(auth.require_role("admin", "usuario"))])
async def get_stats(filters: str = "", user: dict = Depends(auth.require_role("admin", "usuario"))):
    return jobs.stats(_filters(filters), user=user)


# --------------------------------------------------------------- settings

@app.get("/api/settings/ai", dependencies=[Depends(auth.require_role("admin"))])
async def get_ai_settings():
    return STORE.public(STORE.load())


@app.put("/api/settings/ai", dependencies=[Depends(auth.require_role("admin"))])
async def put_ai_settings(data: AISettingsIn, user: dict = Depends(auth.require_role("admin"))):
    current = STORE.load() or {}
    provider = (data.provider or "local").strip().lower()
    if provider not in ("local", "external"):
        raise HTTPException(400, "Proveedor no válido")
    base_url = ai_ocr._normalize_base(data.base_url) if data.base_url.strip() else ""
    if not base_url and current.get("provider") == provider:
        base_url = current.get("base_url", "")
    if base_url and not base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "La URL base debe iniciar con http:// o https://")
    if provider == "external" and not base_url:
        raise HTTPException(400, "El proveedor externo requiere URL base")
    api_key = data.api_key.strip()
    if not api_key and current.get("provider") == provider:
        api_key = current.get("api_key", "")
    if provider == "local":
        api_key = ""
    saved = {
        "provider": provider,
        "api_key": api_key,
        "local_path": data.local_path.strip() or current.get("local_path", ""),
        "base_url": base_url,
        "model": data.model.strip(),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    STORE.save(saved)
    ai_ocr._cache["ts"] = 0.0
    if not saved["model"]:
        discovery = ai_ocr.discover(force=True)
        saved["model"] = discovery.get("selected", "")
        STORE.save(saved)
    db.audit(user["id"], "settings_ai_update", provider, "config actualizada")
    return STORE.public(saved)


@app.delete("/api/settings/ai", dependencies=[Depends(auth.require_role("admin"))])
async def delete_ai_settings(user: dict = Depends(auth.require_role("admin"))):
    STORE.clear()
    db.audit(user["id"], "settings_ai_delete", "ai")
    return {"ok": True}


@app.get("/api/ai/providers", dependencies=[Depends(auth.require_auth)])
async def ai_providers(refresh: int = 0):
    if refresh:
        ai_ocr._cache["ts"] = 0.0
    return ai_ocr.providers()


@app.post("/api/settings/ai/test", dependencies=[Depends(auth.require_role("admin"))])
async def test_ai_settings():
    return ai_ocr.probe()


class AIModelsIn(BaseModel):
    base_url: str
    api_key: str = ""


@app.post("/api/settings/ai/models", dependencies=[Depends(auth.require_role("admin"))])
async def list_ai_models(data: AIModelsIn):
    base_url = ai_ocr._normalize_base(data.base_url)
    if not base_url:
        raise HTTPException(400, "URL base requerida")
    fetched = ai_ocr._fetch_models(base_url, data.api_key)
    return {
        "base_url": base_url,
        "reachable": fetched["ok"],
        "models": fetched["models"],
        "error": fetched["error"],
    }


@app.get("/api/settings/ocr", dependencies=[Depends(auth.require_role("admin"))])
async def get_ocr_settings():
    return jobs.ocr_defaults()


@app.put("/api/settings/ocr", dependencies=[Depends(auth.require_role("admin"))])
async def put_ocr_settings(data: OCRSettingsIn, user: dict = Depends(auth.require_role("admin"))):
    result = jobs.set_ocr_defaults(data.profile, data.dpi, data.workers)
    db.audit(user["id"], "settings_ocr_update", "ocr", json.dumps(result))
    return result


# ----------------------------------------------------------------- health

@app.get("/api/health/ai", dependencies=[Depends(auth.require_auth)])
async def health_ai():
    return ai_ocr.health()


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ------------------------------------------- API legacy (v1, deprecándose)

@app.post("/api/upload/pdf", dependencies=[Depends(auth.require_role("admin", "usuario"))])
async def upload_pdf(file: UploadFile = File(...), mode: str = Form("local")):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos PDF")
    session_id = str(uuid.uuid4())
    pdf_path = UPLOAD_DIR / f"{session_id}.pdf"
    content = await file.read()
    pdf_path.write_bytes(content)
    try:
        table_data = extract_table_from_pdf(str(pdf_path), mode=mode)
    except Exception as e:
        raise HTTPException(500, f"Error procesando PDF: {e}")
    json_path = UPLOAD_DIR / f"{session_id}.json"
    json_path.write_text(json.dumps(table_data, ensure_ascii=False, indent=2))
    ai_info = ai_public(table_data.get("ai_used", False))
    return {
        "session_id": session_id,
        "filename": file.filename,
        "headers": table_data["headers"],
        "rows": table_data["rows"],
        "row_count": len(table_data["rows"]),
        "extractor": table_data.get("extractor", ""),
        "page_count": table_data.get("page_count", 0),
        "mode": "ai" if ai_info["used"] else "local",
        "ai": ai_info,
    }


@app.post("/api/upload/excel", dependencies=[Depends(auth.require_role("admin", "usuario"))])
async def upload_excel(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "Archivo no válido")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".xlsx", ".xls"):
        raise HTTPException(400, "Solo se aceptan archivos .xlsx o .xls")
    session_id = str(uuid.uuid4())
    excel_path = UPLOAD_DIR / f"{session_id}{ext}"
    content = await file.read()
    excel_path.write_bytes(content)
    try:
        data = read_excel(str(excel_path))
    except Exception as e:
        raise HTTPException(500, f"Error leyendo Excel: {e}")
    json_path = UPLOAD_DIR / f"{session_id}.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return {
        "session_id": session_id,
        "filename": file.filename,
        "headers": data["headers"],
        "rows": data["rows"],
        "row_count": len(data["rows"]),
        "ai": ai_public(False),
    }


def _resolve_table(data: TableData):
    headers, rows = data.headers, data.rows
    if not headers and not rows and data.session_id:
        json_path = UPLOAD_DIR / f"{data.session_id}.json"
        if json_path.exists():
            saved = json.loads(json_path.read_text())
            headers, rows = saved.get("headers", []), saved.get("rows", [])
    return headers, rows


def _build_xlsx(headers: list, rows: list) -> BytesIO:
    buf = BytesIO()
    wb = Workbook()
    ws = wb.active
    if headers:
        ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(buf)
    buf.seek(0)
    return buf


def _build_xls(headers: list, rows: list) -> BytesIO:
    buf = BytesIO()
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Sheet1")
    for col_idx, header in enumerate(headers):
        ws.write(0, col_idx, header)
    for row_idx, row in enumerate(rows, start=1):
        for col_idx, value in enumerate(row):
            ws.write(row_idx, col_idx, value)
    wb.save(buf)
    buf.seek(0)
    return buf


@app.post("/api/download/all", dependencies=[Depends(auth.require_auth)])
async def download_all(data: TableData):
    sid = data.session_id or str(uuid.uuid4())
    headers, rows = _resolve_table(data)
    xlsx = _build_xlsx(headers, rows)
    xls = _build_xls(headers, rows)
    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("tabla.xlsx", xlsx.getvalue())
        zf.writestr("tabla.xls", xls.getvalue())
    zip_buf.seek(0)
    return Response(
        zip_buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="tabla_{sid}.zip"'},
    )


@app.post("/api/download/xlsx", dependencies=[Depends(auth.require_auth)])
async def download_xlsx(data: TableData):
    sid = data.session_id or str(uuid.uuid4())
    headers, rows = _resolve_table(data)
    output = DOWNLOAD_DIR / f"{sid}.xlsx"
    table_to_xlsx(headers, rows, str(output))
    return FileResponse(str(output), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename="tabla.xlsx")


@app.post("/api/download/xls", dependencies=[Depends(auth.require_auth)])
async def download_xls(data: TableData):
    sid = data.session_id or str(uuid.uuid4())
    headers, rows = _resolve_table(data)
    output = DOWNLOAD_DIR / f"{sid}.xls"
    table_to_xls(headers, rows, str(output))
    return FileResponse(str(output), media_type="application/vnd.ms-excel", filename="tabla.xls")


@app.post("/api/download/csv", dependencies=[Depends(auth.require_auth)])
async def download_csv(data: TableData):
    sid = data.session_id or str(uuid.uuid4())
    headers, rows = _resolve_table(data)
    buf = StringIO()
    writer = csv.writer(buf)
    if headers:
        writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    content = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="tabla_{sid}.csv"'},
    )


@app.post("/api/download/pdf", dependencies=[Depends(auth.require_auth)])
async def download_pdf(data: TableData):
    sid = data.session_id or str(uuid.uuid4())
    headers, rows = _resolve_table(data)
    output = DOWNLOAD_DIR / f"{sid}.pdf"
    table_to_pdf(headers, rows, str(output))
    return FileResponse(str(output), media_type="application/pdf", filename="tabla.pdf")
