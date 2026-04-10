"""
Pydantic models for RAG1 knowledge base, request, audit output, and FE output.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
    chunk_id: str = Field(..., description="e.g. KB_10_severity_001")
    class_id: int = Field(..., ge=0, le=13)
    class_name: str
    class_name_vi: str
    icd10: str
    section_type: str = Field(..., description="One of SECTION_TYPES")
    content: str
    rag_tags: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class ImageSize(BaseModel):
    width: int
    height: int


class DetectionCropArtifact(BaseModel):
    det_id: int
    path: str


class SourceContext(BaseModel):
    dicom_path: str = ""
    rendered_image_path: str = ""
    crop_dir: str = ""
    detection_crops: list[DetectionCropArtifact] = Field(default_factory=list)


class Detection(BaseModel):
    det_id: int
    class_id: int = Field(..., ge=0, le=13)
    class_name: str
    bbox_xyxy: list[int] = Field(..., min_length=4, max_length=4)
    bbox_norm: list[float] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    laterality: str = "N/A"
    severity_hint: str = "unknown"


class PatientContext(BaseModel):
    age: int | None = None
    sex: str = "unknown"
    clinical_notes: str = ""
    prior_study_id: str | None = None


class RAG1Request(BaseModel):
    query_id: str
    study_id: str = ""
    image_id: str = ""
    image_size: ImageSize = Field(default_factory=lambda: ImageSize(width=0, height=0))
    detections: list[Detection] = Field(default_factory=list)
    patient_context: PatientContext = Field(default_factory=PatientContext)
    rag_mode: str = "findings_draft"
    language: Literal["vi", "en"] = "vi"
    top_k: int = 5
    source_context: SourceContext = Field(default_factory=SourceContext)


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
    likelihood: str = "possible"


class Flag(BaseModel):
    code: str
    level: str = "info"
    message: str


class FindingsDraft(BaseModel):
    impression: str = ""
    severity_assessment: str = "unknown"
    severity_confidence: float = 0.0
    differential_diagnosis: list[DifferentialDiagnosis] = Field(default_factory=list)
    recommended_next_steps: str = ""
    critical_flag: bool = False
    flags: list[Flag] = Field(default_factory=list)


class QuantitativeEvidence(BaseModel):
    width_ratio: float = 0.0
    height_ratio: float = 0.0
    area_ratio: float = 0.0
    estimated_ctr: float | None = None
    ctr_assessment: str = ""
    quantitative_severity: str = "unknown"
    quantitative_supported: bool = False
    rationale: str = ""
    crop_path: str = ""
    vision_candidate: bool = False
    vision_candidate_reasons: list[str] = Field(default_factory=list)
    vision_verification_status: str = "not_attempted"
    vision_support: str = "not_attempted"
    vision_explanation: str = ""
    vision_cache_hit: bool = False


class DetectionAdjudication(BaseModel):
    severity_final: str = "unknown"
    severity_source: str = "draft"
    needs_review: bool = False
    rationale: str = ""
    critical_flag_final: bool = False
    flag_codes: list[str] = Field(default_factory=list)
    impression_final: str = ""
    next_steps_final: str = ""


class DetectionResult(BaseModel):
    det_id: int
    class_id: int
    class_name: str
    laterality: str = "N/A"
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    findings_draft: FindingsDraft = Field(default_factory=FindingsDraft)
    quantitative_evidence: QuantitativeEvidence = Field(default_factory=QuantitativeEvidence)
    adjudication: DetectionAdjudication = Field(default_factory=DetectionAdjudication)


class OverallImpression(BaseModel):
    summary: str = ""
    most_critical_det_id: int | None = None
    overall_severity: str = "unknown"
    requires_urgent_action: bool = False


class FinalFindingForFE(BaseModel):
    det_id: int
    class_id: int
    class_name: str
    laterality: str = "N/A"
    confidence: float = 0.0
    bbox_xyxy: list[int] = Field(default_factory=list)
    bbox_norm: list[float] = Field(default_factory=list)
    severity_final: str = "unknown"
    severity_source: str = "draft"
    needs_review: bool = False
    impression_final: str = ""
    next_steps_final: str = ""
    critical_flag_final: bool = False
    flag_codes: list[str] = Field(default_factory=list)


class FinalForFE(BaseModel):
    study_id: str = ""
    image_id: str = ""
    findings: list[FinalFindingForFE] = Field(default_factory=list)
    summary_final: str = ""
    overall_severity_final: str = "unknown"
    requires_urgent_action_final: bool = False
    most_critical_det_id_final: int | None = None
    flag_codes_final: list[str] = Field(default_factory=list)


class RAG1Metadata(BaseModel):
    rag_version: str = "2.1"
    kb_version: str = "RAG1_KB_v2.0"
    model_used: str = ""
    kb_timestamp: str = ""
    processing_time_ms: int = 0
    safe_mode: bool = False
    response_cache_enabled: bool = False
    api_retry_policy: str = ""
    vision_verification_mode: str = "disabled"


class RAG1Response(BaseModel):
    query_id: str
    study_id: str = ""
    image_id: str = ""
    results_per_detection: list[DetectionResult] = Field(default_factory=list)
    overall_impression: OverallImpression = Field(default_factory=OverallImpression)
    final_for_fe: FinalForFE = Field(default_factory=FinalForFE)
    metadata: RAG1Metadata = Field(default_factory=RAG1Metadata)


CLASS_INFO: list[dict[str, str]] = [
    {"id": "0", "en": "Aortic Enlargement", "vi": "Gian / Phinh dong mach chu", "icd10": "I71"},
    {"id": "1", "en": "Atelectasis", "vi": "Xep phoi", "icd10": "J98.1"},
    {"id": "2", "en": "Calcification", "vi": "Voi hoa phoi / trung that", "icd10": "J98.4"},
    {"id": "3", "en": "Cardiomegaly", "vi": "Tim to", "icd10": "I51.7"},
    {"id": "4", "en": "Consolidation", "vi": "Dac phoi", "icd10": "J18.1"},
    {"id": "5", "en": "ILD", "vi": "Benh phoi mo ke", "icd10": "J84.1"},
    {"id": "6", "en": "Infiltration", "vi": "Tham nhiem phoi", "icd10": "J22"},
    {"id": "7", "en": "Lung Opacity", "vi": "Mo phoi (tong quat)", "icd10": "R91.8"},
    {"id": "8", "en": "Nodule/Mass", "vi": "Not phoi / Khoi phoi", "icd10": "R91.1"},
    {"id": "9", "en": "Other Lesion", "vi": "Ton thuong khac", "icd10": "R91.8"},
    {"id": "10", "en": "Pleural Effusion", "vi": "Tran dich mang phoi", "icd10": "J90"},
    {"id": "11", "en": "Pleural Thickening", "vi": "Day mang phoi", "icd10": "J92.0"},
    {"id": "12", "en": "Pneumothorax", "vi": "Tran khi mang phoi", "icd10": "J93.0"},
    {"id": "13", "en": "Pulmonary Fibrosis", "vi": "Xo phoi", "icd10": "J84.10"},
]
