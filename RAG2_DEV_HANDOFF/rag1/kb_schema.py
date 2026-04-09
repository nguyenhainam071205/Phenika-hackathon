"""
Pydantic models for RAG1 knowledge base, input, and output schemas.

Aligns with RAG1_Knowledge_Base_CXR14_v2.pdf — JSON Schema v2.0.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# Knowledge Base schema
# ═══════════════════════════════════════════════════════════════

SECTION_TYPES = [
    "definition",
    "xray_features",
    "severity",
    "ddx",
    "next_steps",
    "clinical_notes",
    "rag_tags",
    "references",
]


class KBChunk(BaseModel):
    """One chunk from the knowledge base, representing a section of a class."""

    chunk_id: str = Field(..., description="e.g. KB_10_severity_001")
    class_id: int = Field(..., ge=0, le=13)
    class_name: str
    class_name_vi: str
    icd10: str
    section_type: str = Field(..., description="One of SECTION_TYPES")
    content: str
    rag_tags: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# RAG1 Input JSON Schema (v2.0)
# ═══════════════════════════════════════════════════════════════

class ImageSize(BaseModel):
    width: int
    height: int


class Detection(BaseModel):
    det_id: int
    class_id: int = Field(..., ge=0, le=13)
    class_name: str
    bbox_xyxy: list[int] = Field(..., min_length=4, max_length=4)
    bbox_norm: list[float] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    laterality: str = "N/A"  # Left | Right | Bilateral | Central | N/A
    severity_hint: str = "unknown"  # mild | moderate | severe | unknown


class PatientContext(BaseModel):
    age: int | None = None
    sex: str = "unknown"  # M | F | unknown
    clinical_notes: str = ""
    prior_study_id: str | None = None


class RAG1Request(BaseModel):
    """Input to RAG1 service."""

    query_id: str
    study_id: str = ""
    image_id: str = ""
    image_size: ImageSize = Field(default_factory=lambda: ImageSize(width=0, height=0))
    detections: list[Detection] = Field(default_factory=list)
    patient_context: PatientContext = Field(default_factory=PatientContext)
    rag_mode: str = "findings_draft"  # findings_draft | ddx_only | severity_only
    language: Literal["vi", "en"] = "vi"
    top_k: int = 5


# ═══════════════════════════════════════════════════════════════
# RAG1 Output JSON Schema (v2.0)
# ═══════════════════════════════════════════════════════════════

class RetrievedChunk(BaseModel):
    chunk_id: str
    source: str = "RAG1_KB_v2.0"
    section: str
    relevance_score: float
    content: str
    icd10: str = ""
    references: list[str] = Field(default_factory=list)


class DifferentialDiagnosis(BaseModel):
    dx: str
    likelihood: str = "possible"  # likely | possible | unlikely


class Flag(BaseModel):
    code: str
    level: str = "info"  # info | warning | critical
    message: str


class FindingsDraft(BaseModel):
    impression: str = ""
    severity_assessment: str = "unknown"
    severity_confidence: float = 0.0
    differential_diagnosis: list[DifferentialDiagnosis] = Field(default_factory=list)
    recommended_next_steps: str = ""
    critical_flag: bool = False
    flags: list[Flag] = Field(default_factory=list)


class DetectionResult(BaseModel):
    det_id: int
    class_id: int
    class_name: str
    laterality: str = "N/A"
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    findings_draft: FindingsDraft = Field(default_factory=FindingsDraft)


class OverallImpression(BaseModel):
    summary: str = ""
    most_critical_det_id: int | None = None
    overall_severity: str = "unknown"
    requires_urgent_action: bool = False


class RAG1Metadata(BaseModel):
    rag_version: str = "2.0"
    kb_version: str = "RAG1_KB_v2.0"
    model_used: str = ""
    kb_timestamp: str = ""
    processing_time_ms: int = 0


class RAG1Response(BaseModel):
    """Full output from RAG1 service."""

    query_id: str
    study_id: str = ""
    image_id: str = ""
    results_per_detection: list[DetectionResult] = Field(default_factory=list)
    overall_impression: OverallImpression = Field(default_factory=OverallImpression)
    metadata: RAG1Metadata = Field(default_factory=RAG1Metadata)


# ═══════════════════════════════════════════════════════════════
# Class mapping table (from PDF page 1)
# ═══════════════════════════════════════════════════════════════

CLASS_INFO: list[dict[str, str]] = [
    {"id": "0",  "en": "Aortic Enlargement",   "vi": "Giãn / Phình động mạch chủ",  "icd10": "I71"},
    {"id": "1",  "en": "Atelectasis",           "vi": "Xẹp phổi",                    "icd10": "J98.1"},
    {"id": "2",  "en": "Calcification",         "vi": "Vôi hóa phổi / trung thất",   "icd10": "J98.4"},
    {"id": "3",  "en": "Cardiomegaly",          "vi": "Tim to",                       "icd10": "I51.7"},
    {"id": "4",  "en": "Consolidation",         "vi": "Đặc phổi",                    "icd10": "J18.1"},
    {"id": "5",  "en": "ILD",                   "vi": "Bệnh phổi mô kẽ",             "icd10": "J84.1"},
    {"id": "6",  "en": "Infiltration",          "vi": "Thâm nhiễm phổi",             "icd10": "J22"},
    {"id": "7",  "en": "Lung Opacity",          "vi": "Mờ phổi (tổng quát)",         "icd10": "R91.8"},
    {"id": "8",  "en": "Nodule/Mass",           "vi": "Nốt phổi / Khối phổi",        "icd10": "R91.1"},
    {"id": "9",  "en": "Other Lesion",          "vi": "Tổn thương khác",             "icd10": "R91.8"},
    {"id": "10", "en": "Pleural Effusion",      "vi": "Tràn dịch màng phổi",         "icd10": "J90"},
    {"id": "11", "en": "Pleural Thickening",    "vi": "Dày màng phổi",               "icd10": "J92.0"},
    {"id": "12", "en": "Pneumothorax",          "vi": "Tràn khí màng phổi",          "icd10": "J93.0"},
    {"id": "13", "en": "Pulmonary Fibrosis",    "vi": "Xơ phổi",                     "icd10": "J84.10"},
]
