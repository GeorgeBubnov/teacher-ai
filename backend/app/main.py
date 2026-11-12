import json
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .parser import extract_text, parse_document
from .ai_parser import parse_with_ai


STORAGE = Path(os.getenv("STORAGE_DIR", "/data"))
UPLOADS = STORAGE / "uploads"
RESULTS = STORAGE / "results"
UPLOADS.mkdir(parents=True, exist_ok=True)
RESULTS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Парсер учебно-календарного плана")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ParsedDocument(BaseModel):
    rows: list[dict]
    warnings: list[str] = []


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/parse")
async def parse_file(file: UploadFile = File(...)):
    if not file.filename or Path(file.filename).suffix.lower() not in {".doc", ".docx", ".pdf"}:
        raise HTTPException(400, "Поддерживаются только файлы .doc, .docx и .pdf")
    document_id = uuid.uuid4().hex
    source_path = UPLOADS / f"{document_id}{Path(file.filename).suffix.lower()}"
    source_path.write_bytes(await file.read())
    try:
        text = extract_text(source_path)
        ai_result = parse_with_ai(text)
        rows = ai_result.get("rows", [])
        warnings = ai_result.get("warnings", [])
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    result = {
        "id": document_id,
        "filename": file.filename,
        "rows": rows,
        "warnings": warnings,
        "diagnostics": ai_result.get("diagnostics", {}),
    }
    (RESULTS / f"{document_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


@app.put("/api/results/{document_id}")
def update_result(document_id: str, payload: ParsedDocument):
    path = RESULTS / f"{document_id}.json"
    if not path.exists():
        raise HTTPException(404, "Результат не найден")
    current = json.loads(path.read_text(encoding="utf-8"))
    current.update(payload.model_dump())
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


@app.get("/api/results/{document_id}/download")
def download_result(document_id: str):
    path = RESULTS / f"{document_id}.json"
    if not path.exists():
        raise HTTPException(404, "Результат не найден")
    return FileResponse(path, media_type="application/json", filename="parsed-plan.json")
