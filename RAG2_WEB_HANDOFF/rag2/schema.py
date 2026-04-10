"""
Pydantic models for RAG2 input (Doctor-Revised JSON v2.0) and output schemas.

Aligns with RAG2_Specification_v2.1.md — Sections 2 and 6.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# RAG2 Input — Doctor-Revised JSON (v2.0)
# ═══════════════════════════════════════════════════════════════


class Technique(BaseModel):
    """Thông tin kỹ thuật chụp."""
    view: str = "PA"  # PA | AP | Lateral | Oblique
    position: str = "erect"  # erect | supine | decubitus_right | decubitus_left
    image_quality: str = "adequate"  # adequate | suboptimal | poor
    quality_notes: str | None = None


class Measurements(BaseModel):
    """Đo lường bác sĩ thực hiện trên OHIF (tất cả optional)."""
    max_depth_mm: float | None = None  # Pleural Effusion
    ctr: float | None = None  # Cardiothoracic Ratio
    diameter_mm: float | None = None  # Nodule/Mass
    length_mm: float | None = None  # Chiều dài tổn thương
    area_cm2: float | None = None  # Diện tích


class ConfirmedFinding(BaseModel):
    """Một finding đã được bác sĩ xác nhận."""
    # Định danh
    det_id: int
    class_id: int = Field(..., ge=0, le=13)
    class_name: str

    # Nguồn gốc
    source: Literal["ai_confirmed", "ai_modified", "doctor_added"] = "ai_confirmed"

    # Đặc điểm lâm sàng
    laterality: str = "N/A"  # Left | Right | Bilateral | Central | N/A
    severity: str = "unknown"  # mild | moderate | severe | unknown
    severity_source: str = "ai_suggested"  # doctor | ai_agreed | ai_suggested

    # Bounding box
    bbox_xyxy: list[int] = Field(default_factory=list)
    bbox_norm: list[float] = Field(default_factory=list)

    # Ghi chú bác sĩ (KEY FIELD — RAG2 ưu tiên cao nhất)
    doctor_note: str | None = None

    # Kế thừa từ RAG1
    rag1_impression_accepted: bool = True
    rag1_impression_override: str | None = None
    rag1_impression_original: str = ""  # Lưu lại impression gốc từ RAG1

    # Đo lường
    measurements: Measurements = Field(default_factory=Measurements)

    # ICD-10
    icd10_suggested: str = ""
    icd10_confirmed: str | None = None

    # Flag nguy cấp
    critical_flag: bool = False


class DoctorGlobalAssessment(BaseModel):
    """Đánh giá tổng thể của bác sĩ."""
    overall_severity: str = "unknown"  # mild | moderate | severe
    requires_urgent_action: bool = False
    comparison_available: bool = False
    comparison_notes: str | None = None
    free_text_summary: str = ""


class PatientContext(BaseModel):
    """Ngữ cảnh bệnh nhân."""
    age: int | None = None
    sex: str = "unknown"  # M | F | unknown
    clinical_notes: str = ""
    prior_study_id: str | None = None


class RAG2RequestConfig(BaseModel):
    """Cấu hình RAG2 cho mỗi request."""
    mode: str = "full_report"  # full_report | impression_only | structured_json
    language: str = "vi+en"  # vi | en | vi+en
    report_standard: str = "BYT"  # BYT | ACR | BYT_ACR
    top_k: int = 5
    include_icd10: bool = True
    include_recommendation: bool = True


class DoctorRevisedJSON(BaseModel):
    """
    Full input schema for RAG2 — Doctor-Revised JSON v2.0.

    This is the SINGLE SOURCE OF TRUTH after doctor review.
    """
    # Định danh
    query_id: str
    study_id: str = ""
    image_id: str = ""
    revision_id: str = ""
    revised_at: str = ""
    revised_by: str = ""

    # Kỹ thuật chụp
    technique: Technique = Field(default_factory=Technique)

    # Findings đã xác nhận
    confirmed_findings: list[ConfirmedFinding] = Field(default_factory=list)

    # Cấu trúc bình thường
    normal_structures: list[str] = Field(default_factory=list)

    # Đánh giá tổng thể
    doctor_global_assessment: DoctorGlobalAssessment = Field(
        default_factory=DoctorGlobalAssessment
    )

    # Ngữ cảnh bệnh nhân
    patient_context: PatientContext = Field(default_factory=PatientContext)

    # Cấu hình RAG2
    rag2_config: RAG2RequestConfig = Field(default_factory=RAG2RequestConfig)


# ═══════════════════════════════════════════════════════════════
# RAG2 Output — Report Response
# ═══════════════════════════════════════════════════════════════


class NhanXet(BaseModel):
    """Nhận xét tiếng Việt theo chuẩn BYT — 4 phần bắt buộc."""
    tim_trung_that: str = ""  # Tim & Trung thất
    phoi: str = ""  # Phổi
    mang_phoi: str = ""  # Màng phổi
    xuong_mo_mem: str = ""  # Xương & Mô mềm


class ICD10Vi(BaseModel):
    ma: str
    mo_ta: str


class ReportVi(BaseModel):
    """Báo cáo tiếng Việt — PRIMARY (BYT chuẩn)."""
    ky_thuat: str = ""
    nhan_xet: NhanXet = Field(default_factory=NhanXet)
    ket_luan: list[str] = Field(default_factory=list)  # Tối đa 5 dòng
    de_nghi: str | None = None
    icd10: list[ICD10Vi] = Field(default_factory=list)


class Findings(BaseModel):
    """Findings tiếng Anh theo chuẩn ACR."""
    cardiac_mediastinum: str = ""
    lungs: str = ""
    pleura: str = ""
    bones_soft_tissue: str = ""


class ICD10En(BaseModel):
    code: str
    description: str


class ReportEn(BaseModel):
    """Báo cáo tiếng Anh — SECONDARY (ACR standard)."""
    technique: str = ""
    findings: Findings = Field(default_factory=Findings)
    impression: list[str] = Field(default_factory=list)  # Tối đa 3 dòng
    recommendation: str | None = None
    icd10: list[ICD10En] = Field(default_factory=list)


class RAG2Metadata(BaseModel):
    """Metadata chất lượng & an toàn."""
    rag_version: str = "2.0"
    kb_version: str = "RAG2_KB_v1.0"
    llm_model: str = ""
    report_standard: str = "BYT"
    language: str = "vi+en"
    chunks_used: int = 0
    processing_time_ms: int = 0

    # Safety fields
    critical_flags: list[int] = Field(default_factory=list)  # det_ids with critical
    requires_urgent_review: bool = False
    confidence_notes: list[str] = Field(default_factory=list)
    report_status: str = "COMPLETED"  # COMPLETED | FAILED_VALIDATION

    # Traceability
    findings_count_input: int = 0
    findings_count_output: int = 0


class RAG2Response(BaseModel):
    """Full output from RAG2 service."""
    # Echo định danh
    query_id: str
    study_id: str = ""
    image_id: str = ""
    revision_id: str = ""
    report_id: str = ""
    generated_at: str = ""

    # Báo cáo song ngữ
    report_vi: ReportVi = Field(default_factory=ReportVi)
    report_en: ReportEn = Field(default_factory=ReportEn)

    # Metadata
    metadata: RAG2Metadata = Field(default_factory=RAG2Metadata)
