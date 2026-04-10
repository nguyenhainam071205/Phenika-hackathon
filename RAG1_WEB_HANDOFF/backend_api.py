"""
Minimal FastAPI wrapper for the root RAG1 pipeline.
"""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dicom_to_rag1_json import build_rag1_input_payload, resolve_dicom_input, write_rag1_input_bundle
from rag1.config import RAG1Config
from rag1.engine import RAG1Engine


SUPPORTED_LANGUAGES = {"vi", "en"}
SUPPORTED_RAG_MODES = {"findings_draft", "ddx_only", "severity_only"}
SAMPLES_DIR = ROOT / "image_dicom"
OUTPUTS_DIR = ROOT / "outputs"
UPLOADS_DIR = OUTPUTS_DIR / "_uploads"
ORTHANC_DIR = OUTPUTS_DIR / "_orthanc"
ORTHANC_URL = os.environ.get("ORTHANC_URL", "http://localhost:8042")

app = FastAPI(
    title="RAG1 Hybrid API",
    version="2.1.0",
    description="HTTP wrapper for the DICOM -> YOLO -> RAG1 hybrid pipeline.",
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


def _validate_inputs(language: str, rag_mode: str, top_k: int) -> None:
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported language: {language}")
    if rag_mode not in SUPPORTED_RAG_MODES:
        raise HTTPException(status_code=400, detail=f"Unsupported rag_mode: {rag_mode}")
    if top_k <= 0:
        raise HTTPException(status_code=400, detail="top_k must be > 0")


def _find_sample_dicom(sample_id: str) -> Path:
    wrapper_dir = SAMPLES_DIR / f"{sample_id}.dicom"
    if wrapper_dir.exists():
        return resolve_dicom_input(wrapper_dir)
    direct_dir = SAMPLES_DIR / sample_id
    if direct_dir.exists():
        return resolve_dicom_input(direct_dir)
    raise HTTPException(status_code=404, detail=f"Sample not found: {sample_id}")


def _run_pipeline(
    dicom_path: Path,
    source_name: str,
    language: str,
    rag_mode: str,
    top_k: int,
    device: str,
) -> dict:
    _validate_inputs(language=language, rag_mode=rag_mode, top_k=top_k)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    config = RAG1Config()
    config.validate()

    request, image_rgb, runtime_bundle = build_rag1_input_payload(
        dicom_path=dicom_path,
        model_arg=None,
        device=device,
        language=language,
        rag_mode=rag_mode,
        top_k=top_k,
    )

    job_id = f"{_utc_stamp()}-{uuid.uuid4().hex[:8]}-{source_name}"
    job_dir = OUTPUTS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    input_json_path = job_dir / f"{source_name}.rag1_input.json"
    input_png_path = job_dir / f"{source_name}.png"
    output_json_path = job_dir / f"{source_name}.rag1_output.json"

    write_rag1_input_bundle(
        request=request,
        image_rgb=image_rgb,
        output_json_path=input_json_path,
        output_image_path=input_png_path,
    )

    engine = RAG1Engine(config)
    response = engine.process(request)

    output_json_path.write_text(
        response.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )

    return {
        "job_id": job_id,
        "source_name": source_name,
        "dicom_path": str(dicom_path.resolve()),
        "artifacts": {
            "input_json": _relative(input_json_path),
            "input_png": _relative(input_png_path),
            "output_json": _relative(output_json_path),
        },
        "detector": runtime_bundle["detector"],
        "result": response.model_dump(mode="json", exclude_none=False),
    }


@app.get("/health")
def health() -> dict:
    config = RAG1Config()
    return {
        "status": "ok",
        "package_root": str(ROOT),
        "safe_mode": config.safe_mode,
        "has_github_token": bool(config.github_token),
        "response_cache_enabled": config.enable_response_cache,
        "kb_pdf_exists": config.kb_pdf_path.exists(),
        "chroma_store_exists": config.chroma_persist_dir.exists(),
        "yolo_weights_exists": config.yolo_weights_path.exists(),
        "vision_verification_enabled": config.enable_vision_verification,
        "vision_only_on_review_cases": config.vision_only_on_review_cases,
        "sample_count": len(list(SAMPLES_DIR.glob("*.dicom"))),
    }


@app.get("/samples")
def list_samples() -> dict:
    samples = []
    for wrapper in sorted(SAMPLES_DIR.glob("*.dicom")):
        try:
            dicom_path = resolve_dicom_input(wrapper)
        except FileNotFoundError:
            continue
        samples.append(
            {
                "sample_id": wrapper.stem,
                "wrapper_dir": _relative(wrapper),
                "dicom_file": _relative(dicom_path),
            }
        )
    return {"samples": samples}


@app.post("/run-sample")
def run_sample(
    sample_id: str,
    language: str = "vi",
    rag_mode: str = "findings_draft",
    top_k: int = 5,
    device: str = "cpu",
) -> dict:
    dicom_path = _find_sample_dicom(sample_id)
    return _run_pipeline(
        dicom_path=dicom_path,
        source_name=Path(sample_id).stem,
        language=language,
        rag_mode=rag_mode,
        top_k=top_k,
        device=device,
    )


@app.post("/run-upload")
def run_upload(
    dicom_file: UploadFile = File(...),
    language: str = Form("vi"),
    rag_mode: str = Form("findings_draft"),
    top_k: int = Form(5),
    device: str = Form("cpu"),
) -> dict:
    suffix = Path(dicom_file.filename or "upload.dicom").suffix or ".dicom"
    upload_id = f"{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    upload_dir = UPLOADS_DIR / upload_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    saved_path = upload_dir / f"input{suffix}"
    with saved_path.open("wb") as handle:
        shutil.copyfileobj(dicom_file.file, handle)

    return _run_pipeline(
        dicom_path=saved_path,
        source_name=saved_path.stem,
        language=language,
        rag_mode=rag_mode,
        top_k=top_k,
        device=device,
    )


# ── Orthanc integration ──────────────────────────────────────────────────────

class OrthancRunRequest(BaseModel):
    """Request body for /rag1/run-orthanc."""
    sop_instance_uid: str
    study_instance_uid: str | None = None
    series_instance_uid: str | None = None
    language: str = "en"
    rag_mode: str = "findings_draft"
    top_k: int = 5
    device: str = "cpu"


def _fetch_dicom_from_orthanc(sop_instance_uid: str) -> Path:
    """Download a DICOM file from Orthanc by SOPInstanceUID.

    Strategy:
      1. Query Orthanc /tools/find to locate the instance by SOPInstanceUID
      2. Download the raw DICOM via /instances/{id}/file
    """
    # Step 1: Find the Orthanc internal ID for this SOPInstanceUID
    import json as _json

    find_url = f"{ORTHANC_URL}/tools/find"
    find_body = _json.dumps({
        "Level": "Instance",
        "Query": {"SOPInstanceUID": sop_instance_uid},
        "Expand": False,
    }).encode("utf-8")

    try:
        req = Request(find_url, data=find_body, method="POST")
        req.add_header("Content-Type", "application/json")
        with urlopen(req) as resp:
            orthanc_ids = _json.loads(resp.read().decode("utf-8"))
    except (URLError, HTTPError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to query Orthanc at {find_url}: {exc}",
        )

    if not orthanc_ids:
        raise HTTPException(
            status_code=404,
            detail=f"SOPInstanceUID not found in Orthanc: {sop_instance_uid}",
        )

    orthanc_id = orthanc_ids[0]

    # Step 2: Download the DICOM file
    file_url = f"{ORTHANC_URL}/instances/{orthanc_id}/file"
    try:
        req = Request(file_url, method="GET")
        with urlopen(req) as resp:
            dicom_bytes = resp.read()
    except (URLError, HTTPError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to download DICOM from Orthanc: {file_url}: {exc}",
        )

    # Save to temp location
    download_id = f"{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
    download_dir = ORTHANC_DIR / download_id
    download_dir.mkdir(parents=True, exist_ok=True)

    saved_path = download_dir / f"{sop_instance_uid[:40]}.dicom"
    saved_path.write_bytes(dicom_bytes)

    return saved_path


@app.post("/run-orthanc")
def run_orthanc(body: OrthancRunRequest) -> dict:
    """Fetch a DICOM instance from Orthanc by SOPInstanceUID and run RAG1."""
    try:
        print(f"[RAG1 API] Starting Orthanc run for SOPInstanceUID: {body.sop_instance_uid}")
        dicom_path = _fetch_dicom_from_orthanc(body.sop_instance_uid)
        
        print(f"[RAG1 API] DICOM fetched to {dicom_path}. Running pipeline...")
        result = _run_pipeline(
            dicom_path=dicom_path,
            source_name=dicom_path.stem,
            language=body.language,
            rag_mode=body.rag_mode,
            top_k=body.top_k,
            device=body.device,
        )
        print(f"[RAG1 API] Pipeline execution successful.")
        return result
    except HTTPException:
        # Re-raise FastAPIs own HTTP exceptions (like 404 from fetch)
        raise
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"[RAG1 API ERROR] {str(e)}\n{error_trace}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal RAG1 Error: {str(e)}"
        )
