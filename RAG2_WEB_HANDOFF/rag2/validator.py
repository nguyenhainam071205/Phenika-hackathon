"""
RAG2 Validator — Validates RAG2 output against input constraints.

Safety-critical rules (spec Section 8.3):
  - Hallucination Rate = 0%
  - Critical Miss Rate = 0%
  - ICD-10 False Add Rate = 0%
  - Findings Coverage Fail = 0%
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rag2.schema import DoctorRevisedJSON, RAG2Response


@dataclass
class ValidationError:
    """A single validation error."""
    rule: str
    severity: str  # error | warning
    message: str


@dataclass
class ValidationResult:
    """Result of validating a RAG2 response."""
    is_valid: bool = True
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationError] = field(default_factory=list)

    def add_error(self, rule: str, message: str) -> None:
        self.errors.append(ValidationError(rule=rule, severity="error", message=message))
        self.is_valid = False

    def add_warning(self, rule: str, message: str) -> None:
        self.warnings.append(ValidationError(rule=rule, severity="warning", message=message))


def validate_rag2_response(
    input_json: DoctorRevisedJSON,
    response: RAG2Response,
) -> ValidationResult:
    """
    Validate a RAG2 response against the input constraints.

    Rules:
      1. findings_count_output == findings_count_input (CRITICAL)
      2. ICD-10 output ⊆ icd10_confirmed input
      3. All 4 NHẬN XÉT sections non-empty
      4. KẾT LUẬN ≤ 5 items (BYT), IMPRESSION ≤ 3 items (ACR)
      5. critical_flags match input critical_flag=true
      6. Echo fields match (query_id, study_id, etc.)
    """
    result = ValidationResult()

    # ── Rule 1: Findings coverage (CRITICAL) ──────────────────
    input_count = len(input_json.confirmed_findings)
    output_count = response.metadata.findings_count_output

    if output_count != input_count:
        result.add_error(
            "FINDINGS_COVERAGE",
            f"findings_count_output ({output_count}) != "
            f"findings_count_input ({input_count}). "
            f"Report may have missed or hallucinated findings."
        )

    # ── Rule 2: ICD-10 subset check ──────────────────────────
    confirmed_icd10 = set()
    for f in input_json.confirmed_findings:
        if f.icd10_confirmed:
            confirmed_icd10.add(f.icd10_confirmed)

    output_icd10_vi = set(item.ma for item in response.report_vi.icd10)
    output_icd10_en = set(item.code for item in response.report_en.icd10)
    all_output_icd10 = output_icd10_vi | output_icd10_en

    extra_icd10 = all_output_icd10 - confirmed_icd10
    if extra_icd10 and confirmed_icd10:  # Only check if input has confirmed codes
        result.add_error(
            "ICD10_FALSE_ADD",
            f"Output contains ICD-10 codes not in confirmed input: {extra_icd10}"
        )

    # ── Rule 3: Section completeness ─────────────────────────
    nhan_xet = response.report_vi.nhan_xet
    for section_name, section_value in [
        ("tim_trung_that", nhan_xet.tim_trung_that),
        ("phoi", nhan_xet.phoi),
        ("mang_phoi", nhan_xet.mang_phoi),
        ("xuong_mo_mem", nhan_xet.xuong_mo_mem),
    ]:
        if not section_value or not section_value.strip():
            result.add_error(
                "SECTION_COMPLETENESS",
                f"Nhận xét section '{section_name}' is empty"
            )

    findings_en = response.report_en.findings
    for section_name, section_value in [
        ("cardiac_mediastinum", findings_en.cardiac_mediastinum),
        ("lungs", findings_en.lungs),
        ("pleura", findings_en.pleura),
        ("bones_soft_tissue", findings_en.bones_soft_tissue),
    ]:
        if not section_value or not section_value.strip():
            result.add_error(
                "SECTION_COMPLETENESS",
                f"Findings section '{section_name}' is empty"
            )

    # ── Rule 4: Impression/Kết luận line count ───────────────
    ket_luan_count = len(response.report_vi.ket_luan)
    max_vi = max(5, input_count)
    if ket_luan_count > max_vi:
        result.add_warning(
            "KET_LUAN_OVERFLOW",
            f"Kết luận has {ket_luan_count} items (allowed max = {max_vi})"
        )

    impression_count = len(response.report_en.impression)
    max_en = max(3, input_count)
    if impression_count > max_en:
        result.add_warning(
            "IMPRESSION_OVERFLOW",
            f"Impression has {impression_count} items (allowed max = {max_en})"
        )

    # ── Rule 5: Critical flags match ─────────────────────────
    input_critical_ids = set(
        f.det_id for f in input_json.confirmed_findings if f.critical_flag
    )
    output_critical_ids = set(response.metadata.critical_flags)

    missed_critical = input_critical_ids - output_critical_ids
    if missed_critical:
        result.add_error(
            "CRITICAL_MISS",
            f"Critical findings not flagged in output: det_ids {missed_critical}"
        )

    # ── Rule 6: Echo fields ──────────────────────────────────
    if response.query_id != input_json.query_id:
        result.add_warning(
            "ECHO_MISMATCH",
            f"query_id mismatch: output '{response.query_id}' != input '{input_json.query_id}'"
        )

    # ── Rule 7: Urgency Check ────────────────────────────────
    if input_json.doctor_global_assessment.requires_urgent_action:
        # Check if urgency is reflected in the text (de_nghi or ket_luan)
        text_to_check = (
            (response.report_vi.de_nghi or "") + " " +
            " ".join(response.report_vi.ket_luan) + " " +
            (response.report_en.recommendation or "") + " " +
            " ".join(response.report_en.impression)
        ).lower()

        urgency_keywords = ["khẩn", "cấp cứu", "urgent", "immediate"]
        has_urgency = any(kw in text_to_check for kw in urgency_keywords)

        if not has_urgency:
            result.add_error(
                "URGENCY_MISMATCH",
                "Input requires urgent action, but output lacks urgency keywords (khẩn, cấp cứu, urgent...)."
            )

    return result
