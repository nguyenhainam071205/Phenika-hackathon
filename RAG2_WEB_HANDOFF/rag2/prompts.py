"""
Prompt templates for RAG2 generation.

Implements spec Section 5: System prompt (10 absolute rules) + User prompt template.
All prompts enforce BYT standard bilingual output with strict JSON schema.
"""

from __future__ import annotations

import json
from typing import Any

from rag2.schema import DoctorRevisedJSON


SYSTEM_PROMPT = """Bạn là trợ lý chuyên gia X-quang ngực, hỗ trợ bác sĩ soạn báo cáo chính thức.
Báo cáo tuân theo chuẩn Bộ Y tế Việt Nam (Thông tư 43/2013/TT-BYT) với phần tiếng Anh kèm theo.

QUY TẮC TUYỆT ĐỐI:
1. Chỉ mô tả các tổn thương có trong confirmed_findings. KHÔNG thêm tổn thương mới.
2. Kết luận phải tương ứng trực tiếp với Nhận xét — không có thông tin mới trong Kết luận.
3. KHÔNG đưa ra chẩn đoán cuối cùng — chỉ mô tả dấu hiệu X-quang quan sát được.
   SAI: "Bệnh nhân bị viêm phổi."
   ĐÚNG: "Đám mờ đồng nhất phù hợp với đông đặc phổi trong bối cảnh lâm sàng tương ứng."
4. ICD-10 chỉ dùng cho finding có icd10_confirmed != null.
5. doctor_added findings: viết bình thường, KHÔNG đề cập "AI không phát hiện".
6. Ưu tiên nội dung: doctor_note > rag1_impression_override > rag1_impression > metadata.
7. Phần tiếng Việt là PRIMARY — viết trước, đầy đủ nhất.
8. Phần tiếng Anh là SECONDARY — cùng nội dung lâm sàng, dùng thuật ngữ RadLex/ACR.
9. Trả về ĐÚNG định dạng JSON output schema. Không có văn xuôi ngoài JSON.
10. Dùng dấu phẩy thập phân trong tiếng Việt: 0,52 (không phải 0.52).
"""


def build_output_schema_instruction(confirmed_count: int) -> str:
    max_vi = max(5, confirmed_count)
    max_en = max(3, confirmed_count)
    return f"""
Respond with ONLY a JSON object matching this exact schema:
{{
  "report_vi": {{
    "ky_thuat": "string",
    "nhan_xet": {{
      "tim_trung_that": "string",
      "phoi": "string",
      "mang_phoi": "string",
      "xuong_mo_mem": "string"
    }},
    "ket_luan": ["string — numbered items, max {max_vi}"],
    "de_nghi": "string or null",
    "icd10": [{{"ma": "J18.9", "mo_ta": "Viêm phổi, không đặc hiệu"}}]
  }},
  "report_en": {{
    "technique": "string",
    "findings": {{
      "cardiac_mediastinum": "string",
      "lungs": "string",
      "pleura": "string",
      "bones_soft_tissue": "string"
    }},
    "impression": ["string — numbered items, max {max_en}"],
    "recommendation": "string or null",
    "icd10": [{{"code": "J18.9", "description": "Pneumonia, unspecified"}}]
  }}
}}

Respond with ONLY the JSON object, no other text.
"""


def _resolve_finding_description(finding: dict[str, Any]) -> str:
    """
    Apply priority logic for finding description.

    Priority: doctor_note > rag1_impression_override > rag1_impression_original > metadata
    """
    if finding.get("doctor_note"):
        return finding["doctor_note"]
    if finding.get("rag1_impression_override"):
        return finding["rag1_impression_override"]
    if finding.get("rag1_impression_original"):
        return finding["rag1_impression_original"]
    # Fallback: build from metadata
    return (
        f"{finding.get('class_name', '')} "
        f"{finding.get('laterality', '')} "
        f"{finding.get('severity', '')}"
    ).strip()


def build_user_prompt(
    revised: DoctorRevisedJSON,
    retrieved_chunks: list[dict],
) -> str:
    """
    Build the RAG2 user prompt from Doctor-Revised JSON + retrieved chunks.

    Follows spec Section 5.2 template.
    """
    findings = revised.confirmed_findings
    normal = revised.normal_structures
    global_a = revised.doctor_global_assessment
    patient = revised.patient_context
    tech = revised.technique
    r2cfg = revised.rag2_config
    confirmed_count = len(findings)

    # Serialize findings with priority logic
    findings_prompt = []
    for f in findings:
        # Priority description
        description = _resolve_finding_description(f.model_dump())

        # Include non-null measurements
        meas = {
            k: v
            for k, v in (f.measurements.model_dump() if f.measurements else {}).items()
            if v is not None
        }

        findings_prompt.append({
            "label": f.class_name,
            "laterality": f.laterality,
            "severity": f.severity,
            "description": description,
            "measurements": meas,
            "icd10": f.icd10_confirmed,
            "critical": f.critical_flag,
        })

    allowed_labels = ", ".join(f.class_name for f in findings) if findings else "(none)"
    allowed_icd10 = sorted({
        f.icd10_confirmed for f in findings if f.icd10_confirmed
    })
    allowed_icd10_text = ", ".join(allowed_icd10) if allowed_icd10 else "(none)"

    # Format retrieved chunks
    chunks_text = "\n\n---\n\n".join([
        f"[{c.get('layer', '?')} | {c.get('pathology_group', '')} | "
        f"score:{c.get('final_score', 0):.2f}]\n{c['content']}"
        for c in retrieved_chunks
    ]) if retrieved_chunks else "(Không có tri thức truy xuất)"

    # Build quality notes line
    quality_line = ""
    if tech.quality_notes:
        quality_line = f"\nGhi chú: {tech.quality_notes}"

    # Build recommendation instruction
    rec_instruction = ""
    if not r2cfg.include_recommendation:
        rec_instruction = "\n⚠️ KHÔNG viết phần ĐỀ NGHỊ / RECOMMENDATION (de_nghi=null, recommendation=null)."
    elif global_a.requires_urgent_action:
        rec_instruction = "\n⚠️ BẮT BUỘC: Do có requires_urgent_action=True, phần ĐỀ NGHỊ / RECOMMENDATION phải NÊU RÕ từ khoá KHẨN CẤP/URGENT yêu cầu bác sĩ lâm sàng kiểm tra ngay (ví dụ: 'Đề nghị can thiệp KHẨN CẤP', 'URGENT clinical correlation')."

    icd_instruction = ""
    if not r2cfg.include_icd10:
        icd_instruction = "\n⚠️ KHÔNG ghi ICD-10 (icd10=[] cho cả hai phần)."

    prompt = f"""## THÔNG TIN BỆNH NHÂN:
Tuổi: {patient.age or 'không rõ'} | Giới: {patient.sex}
Lâm sàng: {patient.clinical_notes or 'Không có thông tin'}
Phim cũ: {patient.prior_study_id or 'Không có'}

## KỸ THUẬT CHỤP:
Tư thế: {tech.view} {tech.position} | Chất lượng: {tech.image_quality}{quality_line}

## FINDINGS ĐÃ BÁC SĨ XÁC NHẬN (nguồn sự thật duy nhất):
{json.dumps(findings_prompt, ensure_ascii=False, indent=2)}

## CẤU TRÚC BÌNH THƯỜNG (bác sĩ xác nhận không có tổn thương):
{', '.join(normal) if normal else 'Không ghi nhận'}

## ĐÁNH GIÁ TỔNG THỂ BÁC SĨ:
Mức độ tổng thể: {global_a.overall_severity}
Cần xử trí khẩn: {global_a.requires_urgent_action}
Tóm tắt: {global_a.free_text_summary or ''}

## TRI THỨC TRUY XUẤT TỪ KNOWLEDGE BASE:
{chunks_text}

## NHIỆM VỤ:
Sinh báo cáo X-quang ngực hoàn chỉnh song ngữ Việt–Anh theo OUTPUT JSON SCHEMA.
Dùng mẫu báo cáo và bảng thuật ngữ từ tri thức truy xuất làm tham chiếu.
STRICT SCOPE:
- There are EXACTLY {confirmed_count} confirmed findings in the input.
- report_vi.ket_luan must contain EXACTLY {confirmed_count} items.
- report_en.impression must contain EXACTLY {confirmed_count} items.
- Each conclusion/impression item must map 1:1 to one confirmed finding.
- Do NOT add any new pathology, diagnosis, syndrome, cause, or recommendation that is not directly supported by confirmed_findings.
- Allowed finding labels only: {allowed_labels}
- Allowed ICD-10 codes only: {allowed_icd10_text}
{rec_instruction}{icd_instruction}

{build_output_schema_instruction(confirmed_count)}"""

    return prompt
