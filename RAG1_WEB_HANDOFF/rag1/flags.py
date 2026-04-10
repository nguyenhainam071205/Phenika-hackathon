"""
Deterministic flag generation for RAG1.
"""

from __future__ import annotations

from rag1.kb_schema import Detection, DetectionResult, Flag


IMAGE_COMBO_RULES = [
    {
        "required_class_ids": {0, 3},
        "code": "FLAG_CARDIO_AORTIC",
        "level": "critical",
        "message": (
            "Tim to kem gian dong mach chu - nguy co suy tim/phinh DMC, can danh gia khan / "
            "Cardiomegaly with aortic enlargement - urgent cardiac/aortic assessment"
        ),
    },
    {
        "required_class_ids": {3, 10},
        "code": "FLAG_EFFUSION_CARDIO",
        "level": "warning",
        "message": (
            "Tim to kem tran dich - nghi suy tim sung huyet / "
            "Cardiomegaly with effusion - suspect congestive heart failure"
        ),
    },
    {
        "required_class_ids": {10, 12},
        "code": "FLAG_PNEUMO_EFFUSION",
        "level": "critical",
        "message": (
            "Tran khi + tran dich dong thoi - cap cuu ngoai khoa / "
            "Simultaneous pneumothorax and effusion - surgical emergency"
        ),
    },
]


def generate_flags_for_detection(
    detection: Detection,
    severity: str = "unknown",
) -> list[Flag]:
    flags: list[Flag] = []

    if detection.class_id == 12 and severity == "severe":
        flags.append(Flag(
            code="FLAG_TENSION_PTX",
            level="critical",
            message="Tran khi ap luc - cap cuu ngay / Tension pneumothorax - immediate emergency",
        ))

    if detection.class_id == 10 and severity == "severe":
        flags.append(Flag(
            code="FLAG_MASSIVE_EFF",
            level="critical",
            message="Tran dich luong nhieu chen ep - dan luu khan cap / Massive pleural effusion - urgent drainage",
        ))

    if detection.class_id == 3 and severity == "severe":
        flags.append(Flag(
            code="FLAG_CARDIOMEGALY",
            level="warning",
            message="Tim to nang - sieu am tim ngay / Severe cardiomegaly - urgent echocardiography",
        ))

    if detection.class_id == 8:
        flags.append(Flag(
            code="FLAG_RAPID_GROWTH",
            level="warning",
            message="Not/khoi phoi phat hien - can theo doi Fleischner / Pulmonary nodule-mass - Fleischner follow-up required",
        ))

    if detection.confidence < 0.5:
        flags.append(Flag(
            code="FLAG_LOW_CONF",
            level="info",
            message="Do tin cay thap - can bac si xac nhan / Low confidence - physician verification required",
        ))

    return flags


def generate_image_flag_hits(detections: list[Detection]) -> list[dict]:
    class_ids = set(d.class_id for d in detections)
    hits: list[dict] = []

    for rule in IMAGE_COMBO_RULES:
        if rule["required_class_ids"].issubset(class_ids):
            hits.append(rule)

    if len(class_ids) >= 3:
        hits.append(
            {
                "required_class_ids": class_ids,
                "code": "FLAG_MULTILESION",
                "level": "info",
                "message": (
                    f"Phat hien {len(class_ids)} loai ton thuong - benh ly phuc tap / "
                    f"{len(class_ids)} lesion types detected - comprehensive review needed"
                ),
            }
        )

    opacity_detections = [d for d in detections if d.class_id == 7]
    if len(opacity_detections) >= 2:
        lateralities = {d.laterality for d in opacity_detections}
        if ("Left" in lateralities and "Right" in lateralities) or "Bilateral" in lateralities:
            hits.append(
                {
                    "required_class_ids": {7},
                    "code": "FLAG_BILATERAL_OP",
                    "level": "warning",
                    "message": "Mo phoi hai ben - nguy co ARDS / Bilateral opacity - ARDS risk",
                }
            )

    return hits


def generate_flags_for_image(
    detections: list[Detection],
    results: list[DetectionResult],
) -> list[Flag]:
    del results
    return [
        Flag(code=hit["code"], level=hit["level"], message=hit["message"])
        for hit in generate_image_flag_hits(detections)
    ]


def has_critical_flag(flags: list[Flag]) -> bool:
    return any(f.level == "critical" for f in flags)
