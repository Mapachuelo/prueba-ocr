import os
import uuid
import json
import zipfile
from io import BytesIO
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from openpyxl import Workbook
import xlwt

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

BASE_DIR = Path("/app/data")
UPLOAD_DIR = BASE_DIR / "uploads"
DOWNLOAD_DIR = BASE_DIR / "downloads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

class TableData(BaseModel):
    session_id: Optional[str] = None
    headers: list[str] = []
    rows: list[list[str]] = []

@app.post("/api/upload/pdf")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos PDF")
    session_id = str(uuid.uuid4())
    pdf_path = UPLOAD_DIR / f"{session_id}.pdf"
    content = await file.read()
    pdf_path.write_bytes(content)
    try:
        table_data = extract_table_from_pdf(str(pdf_path))
    except Exception as e:
        raise HTTPException(500, f"Error procesando PDF: {e}")
    json_path = UPLOAD_DIR / f"{session_id}.json"
    json_path.write_text(json.dumps(table_data, ensure_ascii=False, indent=2))
    return {
        "session_id": session_id,
        "filename": file.filename,
        "headers": table_data["headers"],
        "rows": table_data["rows"],
        "row_count": len(table_data["rows"]),
        "extractor": table_data.get("extractor", ""),
        "page_count": table_data.get("page_count", 0),
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
