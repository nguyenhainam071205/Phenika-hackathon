"""
Rule-based clinical flag generation for RAG1.

Implements the flag table from RAG1_Knowledge_Base_CXR14_v2.pdf page 5.
Flags are deterministic — no LLM needed.
"""

from __future__ import annotations

from rag1.kb_schema import Detection, DetectionResult, Flag


def generate_flags_for_detection(
    detection: Detection,
    severity: str = "unknown",
) -> list[Flag]:
    """Generate flags for a single detection based on class + severity."""
    flags: list[Flag] = []

    # FLAG_TENSION_PTX — Pneumothorax severe
    if detection.class_id == 12 and severity == "severe":
        flags.append(Flag(
            code="FLAG_TENSION_PTX",
            level="critical",
            message="Tràn khí áp lực — cấp cứu ngay / Tension pneumothorax — immediate emergency",
        ))

    # FLAG_MASSIVE_EFF — Pleural Effusion severe
    if detection.class_id == 10 and severity == "severe":
        flags.append(Flag(
            code="FLAG_MASSIVE_EFF",
            level="critical",
            message="Tràn dịch lượng nhiều chèn ép — dẫn lưu khẩn cấp / Massive pleural effusion — urgent drainage",
        ))

    # FLAG_CARDIOMEGALY — CTR > 0.65 (severe cardiomegaly)
    if detection.class_id == 3 and severity == "severe":
        flags.append(Flag(
            code="FLAG_CARDIOMEGALY",
            level="warning",
            message="Tim to nặng — siêu âm tim ngay / Severe cardiomegaly — urgent echocardiography",
        ))

    # FLAG_RAPID_GROWTH — Nodule/Mass (always flag for follow-up)
    if detection.class_id == 8:
        flags.append(Flag(
            code="FLAG_RAPID_GROWTH",
            level="warning",
            message="Nốt/Khối phổi phát hiện — cần theo dõi Fleischner / Pulmonary nodule/mass — Fleischner follow-up required",
        ))

    # FLAG_LOW_CONF — Low confidence detection
    if detection.confidence < 0.5:
        flags.append(Flag(
            code="FLAG_LOW_CONF",
            level="info",
            message="Độ tin cậy thấp — cần bác sĩ xác nhận / Low confidence — physician verification required",
        ))

    return flags


def generate_flags_for_image(
    detections: list[Detection],
    results: list[DetectionResult],
) -> list[Flag]:
    """
    Generate image-level flags based on multi-detection patterns.
    """
    flags: list[Flag] = []

    # FLAG_MULTILESION — ≥3 different classes detected
    unique_classes = set(d.class_id for d in detections)
    if len(unique_classes) >= 3:
        flags.append(Flag(
            code="FLAG_MULTILESION",
            level="info",
            message=(
                f"Phát hiện {len(unique_classes)} loại tổn thương — bệnh lý phức tạp, cần đọc toàn diện / "
                f"{len(unique_classes)} lesion types detected — complex pathology, comprehensive review needed"
            ),
        ))

    # FLAG_BILATERAL_OP — Bilateral opacity (class 7) in ≥2 zones
    opacity_detections = [d for d in detections if d.class_id == 7]
    if len(opacity_detections) >= 2:
        lateralities = set(d.laterality for d in opacity_detections)
        if "Left" in lateralities and "Right" in lateralities or "Bilateral" in lateralities:
            flags.append(Flag(
                code="FLAG_BILATERAL_OP",
                level="warning",
                message="Mờ phổi hai bên — nguy cơ ARDS, theo dõi sát / Bilateral opacity — ARDS risk, close monitoring",
            ))

    return flags


def has_critical_flag(flags: list[Flag]) -> bool:
    """Check if any flag is critical level."""
    return any(f.level == "critical" for f in flags)
