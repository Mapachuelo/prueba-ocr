import csv
import os
import time
import uuid
import json
import zipfile
from io import BytesIO, StringIO
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request, Depends
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from openpyxl import Workbook
import xlwt

from . import auth
from . import ai_ocr
from .settings_store import STORE
from .ocr_extract import extract_table_from_pdf
from .excel_handler import table_to_xlsx, table_to_xls, read_excel
from .pdf_generator import table_to_pdf

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

class TableData(BaseModel):
    session_id: Optional[str] = None
    headers: list[str] = []
    rows: list[list[str]] = []


class CredentialsIn(BaseModel):
    username: str
    password: str


class AISettingsIn(BaseModel):
    api_key: str = ""
    local_path: str = ""
    base_url: str = ""
    model: str = ""


def ai_public(used: bool) -> dict:
    config = STORE.load() or {}
    return {
        "enabled": ai_ocr.is_configured(),
        "used": bool(used),
        "model": config.get("model", ""),
        "base_url": config.get("base_url", ""),
    }


@app.get("/api/health/ai")
async def health_ai():
    return ai_ocr.health()


@app.get("/api/auth/status")
async def auth_status(request: Request):
    return {"setup": auth.is_setup(), "authenticated": auth.is_authenticated(request)}


@app.post("/api/auth/setup")
async def auth_setup(data: CredentialsIn, response: Response):
    username = auth.create_credentials(data.username, data.password)
    auth.set_session(response, username)
    return {"ok": True, "username": username}


@app.post("/api/auth/login")
async def auth_login(data: CredentialsIn, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    auth.check_rate_limit(ip)
    if not auth.verify_credentials(data.username, data.password):
        auth.note_failure(ip)
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    auth.note_success(ip)
    auth.set_session(response, data.username.strip())
    return {"ok": True}


@app.post("/api/auth/logout")
async def auth_logout(response: Response):
    auth.clear_session(response)
    return {"ok": True}


@app.get("/api/settings/ai", dependencies=[Depends(auth.require_auth)])
async def get_ai_settings():
    return STORE.public(STORE.load())


@app.put("/api/settings/ai", dependencies=[Depends(auth.require_auth)])
async def put_ai_settings(data: AISettingsIn):
    current = STORE.load() or {}
    api_key = data.api_key.strip() or current.get("api_key", "")
    base_url = data.base_url.strip()
    if base_url and not base_url.startswith(("http://", "https://")):
        raise HTTPException(400, "La URL base debe iniciar con http:// o https://")
    saved = {
        "api_key": api_key,
        "local_path": data.local_path.strip(),
        "base_url": base_url.rstrip("/"),
        "model": data.model.strip(),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    STORE.save(saved)
    return STORE.public(saved)


@app.delete("/api/settings/ai", dependencies=[Depends(auth.require_auth)])
async def delete_ai_settings():
    STORE.clear()
    return {"ok": True}


@app.post("/api/upload/pdf")
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

@app.post("/api/upload/excel")
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


@app.post("/api/download/all")
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


@app.post("/api/download/xlsx")
async def download_xlsx(data: TableData):
    sid = data.session_id or str(uuid.uuid4())
    headers, rows = _resolve_table(data)
    output = DOWNLOAD_DIR / f"{sid}.xlsx"
    table_to_xlsx(headers, rows, str(output))
    return FileResponse(str(output), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename="tabla.xlsx")

@app.post("/api/download/xls")
async def download_xls(data: TableData):
    sid = data.session_id or str(uuid.uuid4())
    headers, rows = _resolve_table(data)
    output = DOWNLOAD_DIR / f"{sid}.xls"
    table_to_xls(headers, rows, str(output))
    return FileResponse(str(output), media_type="application/vnd.ms-excel", filename="tabla.xls")

@app.post("/api/download/csv")
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


@app.post("/api/download/pdf")
async def download_pdf(data: TableData):
    sid = data.session_id or str(uuid.uuid4())
    headers, rows = _resolve_table(data)
    output = DOWNLOAD_DIR / f"{sid}.pdf"
    table_to_pdf(headers, rows, str(output))
    return FileResponse(str(output), media_type="application/pdf", filename="tabla.pdf")

@app.get("/api/health")
async def health():
    return {"status": "ok"}
