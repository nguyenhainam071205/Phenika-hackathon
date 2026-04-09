"""
Adapter — Convert RAG1 output → Doctor-Revised JSON for RAG2 input.

This module bridges the gap between RAG1's output schema and RAG2's input schema.
Used for:
  1. Demo/test mode (no Frontend needed)
  2. Auto-pipeline: RAG1 → adapter → RAG2

When a real Frontend exists, the FE will produce the Doctor-Revised JSON directly
and this adapter becomes optional.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from rag1.kb_schema import (
    CLASS_INFO,
    RAG1Request,
    RAG1Response,
)

from rag2.schema import (
    ConfirmedFinding,
    DoctorGlobalAssessment,
    DoctorRevisedJSON,
    Measurements,
    PatientContext,
    RAG2RequestConfig,
    Technique,
)


# All 14 class names from VinBigData
ALL_STRUCTURES = [
    "Aortic Enlargement", "Atelectasis", "Calcification", "Cardiomegaly",
    "Consolidation", "ILD", "Infiltration", "Lung Opacity",
    "Nodule/Mass", "Other Lesion", "Pleural Effusion",
    "Pleural Thickening", "Pneumothorax", "Pulmonary Fibrosis",
]

# Structures that are always checked as "normal" if not detected
CHECKABLE_NORMAL_STRUCTURES = [
    "Aorta", "Bones", "Soft tissue", "Trachea",
]


def _find_class_icd10(class_id: int) -> str:
    """Lookup ICD-10 code from CLASS_INFO."""
    for info in CLASS_INFO:
        if int(info["id"]) == class_id:
            return info.get("icd10", "")
    return ""


def _infer_normal_structures(detected_class_ids: set[int]) -> list[str]:
    """
    Infer normal structures from what was NOT detected.

    Logic: If no cardiac/aortic/bone findings → those are normal.
    """
    normals = list(CHECKABLE_NORMAL_STRUCTURES)

    # Aorta: normal if no Aortic Enlargement (class 0)
    if 0 in detected_class_ids:
        normals = [s for s in normals if s != "Aorta"]

    return normals


def rag1_to_doctor_revised(
    rag1_response: RAG1Response,
    rag1_request: RAG1Request | None = None,
    *,
    auto_confirm_icd10: bool = True,
    language: str = "vi+en",
    report_standard: str = "BYT",
) -> DoctorRevisedJSON:
    """
    Convert RAG1 output + input into a Doctor-Revised JSON suitable for RAG2.

    In demo mode, this simulates a doctor who:
      - Accepts all AI findings without modification
      - Uses RAG1 impressions as-is
      - Optionally auto-confirms ICD-10 codes

    Args:
        rag1_response: The RAG1Response object.
        rag1_request: The original RAG1Request (for patient context, etc.).
        auto_confirm_icd10: If True, auto-confirm ICD-10 from CLASS_INFO.
        language: Output language for RAG2.
        report_standard: Report standard (BYT/ACR).

    Returns:
        DoctorRevisedJSON ready for RAG2 processing.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Build confirmed findings from RAG1 detection results
    confirmed_findings: list[ConfirmedFinding] = []
    detected_class_ids: set[int] = set()

    for det_result in rag1_response.results_per_detection:
        detected_class_ids.add(det_result.class_id)
        finding = det_result.findings_draft

        # Lookup ICD-10 from class info
        icd10_code = _find_class_icd10(det_result.class_id)

        # Find original detection from request (for bbox, confidence)
        original_detection = None
        if rag1_request:
            for d in rag1_request.detections:
                if d.det_id == det_result.det_id:
                    original_detection = d
                    break

        confirmed_findings.append(ConfirmedFinding(
            det_id=det_result.det_id,
            class_id=det_result.class_id,
            class_name=det_result.class_name,
            source="ai_confirmed",  # Auto mode = AI confirmed
            laterality=det_result.laterality,
            severity=finding.severity_assessment,
            severity_source="ai_suggested",
            bbox_xyxy=original_detection.bbox_xyxy if original_detection else [],
            bbox_norm=original_detection.bbox_norm if original_detection else [],
            doctor_note=None,  # No doctor in auto mode
            rag1_impression_accepted=True,
            rag1_impression_override=None,
            rag1_impression_original=finding.impression,
            measurements=Measurements(),  # No measurements in auto mode
            icd10_suggested=icd10_code,
            icd10_confirmed=icd10_code if auto_confirm_icd10 else None,
            critical_flag=finding.critical_flag,
        ))

    # Patient context
    patient = PatientContext()
    if rag1_request and rag1_request.patient_context:
        pc = rag1_request.patient_context
        patient = PatientContext(
            age=pc.age,
            sex=pc.sex,
            clinical_notes=pc.clinical_notes,
            prior_study_id=pc.prior_study_id,
        )

    # Overall assessment from RAG1
    overall = rag1_response.overall_impression
    global_assessment = DoctorGlobalAssessment(
        overall_severity=overall.overall_severity,
        requires_urgent_action=overall.requires_urgent_action,
        free_text_summary=overall.summary,
    )

    # Infer normal structures
    normal_structures = _infer_normal_structures(detected_class_ids)

    return DoctorRevisedJSON(
        query_id=rag1_response.query_id,
        study_id=rag1_response.study_id,
        image_id=rag1_response.image_id,
        revision_id=str(uuid.uuid4()),
        revised_at=now,
        revised_by="AUTO_ADAPTER",
        technique=Technique(),  # Default PA/erect/adequate
        confirmed_findings=confirmed_findings,
        normal_structures=normal_structures,
        doctor_global_assessment=global_assessment,
        patient_context=patient,
        rag2_config=RAG2RequestConfig(
            language=language,
            report_standard=report_standard,
        ),
    )
