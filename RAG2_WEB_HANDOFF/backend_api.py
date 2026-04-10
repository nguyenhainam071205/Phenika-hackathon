"""
Minimal FastAPI wrapper for the RAG2 handoff package.

This package is meant for web developers who only need to call RAG2 through
HTTP without depending on the full project repository.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUTPUTS_DIR = ROOT / "outputs"
SAMPLE_DOCTOR_REVISED = ROOT / "demo_rag1_output.doctor_revised.json"
SAMPLE_RAG1_OUTPUT = ROOT / "demo_rag1_output.json"
SUPPORTED_LANGUAGES = {"vi", "en", "vi+en"}

app = FastAPI(
    title="RAG2 Dev Handoff API",
    version="1.0.0",
    description="HTTP wrapper for Doctor-Revised JSON -> RAG2 report generation.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _validate_language(language: str) -> None:
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {language}")


def _write_doctor_revised_job(revised: object, response: object, source_name: str) -> dict:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = f"{_utc_stamp()}-{uuid.uuid4().hex[:8]}-{source_name}"
    job_dir = OUTPUTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    input_path = job_dir / "doctor_revised_input.json"
    output_path = job_dir / "rag2_report.json"

    input_path.write_text(
        revised.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )
    output_path.write_text(
        response.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )

    return {
        "job_id": job_id,
        "artifacts": {
            "doctor_revised_input": _relative(input_path),
            "rag2_report": _relative(output_path),
        },
        "result": response.model_dump(mode="json", exclude_none=False),
    }


def _run_doctor_revised(payload: dict, source_name: str) -> dict:
    from rag2.config import RAG2Config
    from rag2.engine import RAG2Engine
    from rag2.schema import DoctorRevisedJSON

    try:
        revised = DoctorRevisedJSON(**payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Doctor-Revised JSON: {exc}")

    config = RAG2Config()
    engine = RAG2Engine(config)

    try:
        response = engine.process(revised)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"RAG2 processing error: {exc}")

    return _write_doctor_revised_job(revised, response, source_name)


def _run_from_rag1(payload: dict, source_name: str, language: str) -> dict:
    from rag1.kb_schema import RAG1Response
    from rag2.adapter import rag1_to_doctor_revised
    from rag2.config import RAG2Config
    from rag2.engine import RAG2Engine

    _validate_language(language)

    try:
        rag1_response = RAG1Response(**payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid RAG1 output JSON: {exc}")

    revised = rag1_to_doctor_revised(rag1_response, language=language)
    config = RAG2Config()
    engine = RAG2Engine(config)

    try:
        response = engine.process(revised)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"RAG2 processing error: {exc}")

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = f"{_utc_stamp()}-{uuid.uuid4().hex[:8]}-{source_name}"
    job_dir = OUTPUTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    rag1_input_path = job_dir / "rag1_input.json"
    adapter_path = job_dir / "doctor_revised_adapter.json"
    output_path = job_dir / "rag2_report.json"

    rag1_input_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    adapter_path.write_text(
        revised.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )
    output_path.write_text(
        response.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )

    return {
        "job_id": job_id,
        "adapter_used": True,
        "confirmed_findings_count": len(revised.confirmed_findings),
        "artifacts": {
            "rag1_input": _relative(rag1_input_path),
            "doctor_revised_adapter": _relative(adapter_path),
            "rag2_report": _relative(output_path),
        },
        "result": response.model_dump(mode="json", exclude_none=False),
    }


@app.get("/health")
def health() -> dict:
    from rag2.config import RAG2Config

    config = RAG2Config()
    return {
        "status": "ok" if (config.kb_data_dir.exists() and config.chroma_persist_dir.exists()) else "not_ready",
        "package_root": str(ROOT),
        "has_github_token": bool(config.github_token),
        "kb_data_exists": config.kb_data_dir.exists(),
        "chroma_store_exists": config.chroma_persist_dir.exists(),
        "sample_count": 2,
        "llm_model": config.llm_model,
    }


@app.get("/samples")
def list_samples() -> dict:
    return {
        "samples": [
            {
                "sample_id": "doctor_revised_demo",
                "type": "doctor_revised",
                "path": _relative(SAMPLE_DOCTOR_REVISED),
                "description": "Direct Doctor-Revised JSON input for /rag2/generate-report",
            },
            {
                "sample_id": "rag1_output_demo",
                "type": "rag1_output",
                "path": _relative(SAMPLE_RAG1_OUTPUT),
                "description": "RAG1 output JSON for /rag2/demo-from-rag1",
            },
        ]
    }


@app.post("/run-sample")
def run_sample(sample_id: str, language: str = "vi+en") -> dict:
    if sample_id == "doctor_revised_demo":
        payload = json.loads(SAMPLE_DOCTOR_REVISED.read_text(encoding="utf-8"))
        result = _run_doctor_revised(payload, source_name=sample_id)
        result["sample_id"] = sample_id
        result["sample_type"] = "doctor_revised"
        return result

    if sample_id == "rag1_output_demo":
        payload = json.loads(SAMPLE_RAG1_OUTPUT.read_text(encoding="utf-8"))
        result = _run_from_rag1(payload, source_name=sample_id, language=language)
        result["sample_id"] = sample_id
        result["sample_type"] = "rag1_output"
        return result

    raise HTTPException(status_code=404, detail=f"Sample not found: {sample_id}")


@app.post("/generate-report")
def generate_report(payload: dict) -> dict:
    return _run_doctor_revised(payload, source_name="doctor-revised")


@app.post("/demo-from-rag1")
def demo_from_rag1(payload: dict) -> dict:
    language = payload.pop("_language", "vi+en")
    return _run_from_rag1(payload, source_name="rag1-auto", language=language)
