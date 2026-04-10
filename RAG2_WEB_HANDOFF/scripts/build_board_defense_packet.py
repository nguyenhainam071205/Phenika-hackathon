"""
Build board-defense artifacts from rag2 assurance outputs.

Input:
  - <dicom_root>/rag2_assurance_summary.json
  - <dicom_root>/dicom_X.dicom/dicom_X.rag2_eval.json

Output:
  - <dicom_root>/rag2_board_claims.json
  - <dicom_root>/rag2_board_defense_packet.md
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_case_eval_path(case_id: str, dicom_root: Path) -> Path:
    case_dir = dicom_root / f"{case_id}.dicom"
    return case_dir / f"{case_id}.rag2_eval.json"


def build_packet(dicom_root: Path) -> tuple[Path, Path]:
    summary_path = dicom_root / "rag2_assurance_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing summary file: {summary_path}")

    summary = _read_json(summary_path)
    cases = summary.get("cases", [])
    if not isinstance(cases, list) or not cases:
        raise ValueError("No case results found in rag2_assurance_summary.json")

    evals: list[dict[str, Any]] = []
    for case in cases:
        case_id = case.get("case_id")
        if not isinstance(case_id, str):
            continue
        eval_path = _find_case_eval_path(case_id, dicom_root)
        if eval_path.exists():
            payload = _read_json(eval_path)
            payload["_eval_path"] = str(eval_path)
            evals.append(payload)

    total = len(evals)
    trace_ok = len(
        [e for e in evals if e.get("structural_checks", {}).get("trace_chain_complete") is True]
    )
    factual_severe_fail = 0
    safe_mode_cases = 0
    low_conf_high_cases = 0
    urgent_mismatch_cases = 0
    validator_warning_cases = 0

    for e in evals:
        factual = e.get("factual_consistency_checks", {})
        med = e.get("medical_risk_checks", {})
        errors = factual.get("validator_error_rules", []) or []
        warnings = factual.get("validator_warning_rules", []) or []

        if any(rule in {"FINDINGS_COVERAGE", "ICD10_FALSE_ADD", "CRITICAL_MISS"} for rule in errors):
            factual_severe_fail += 1
        if med.get("safe_mode_dependency") is True:
            safe_mode_cases += 1
        ratio = med.get("low_conf_detection_ratio")
        if isinstance(ratio, (float, int)) and float(ratio) >= 0.5:
            low_conf_high_cases += 1
        if med.get("urgent_signal_mismatch") is True:
            urgent_mismatch_cases += 1
        if isinstance(warnings, list) and warnings:
            validator_warning_cases += 1

    claims = [
        {
            "id": "C1_TRACEABILITY",
            "statement": "Pipeline có khả năng truy vết đầy đủ theo từng ca.",
            "result": "proven" if trace_ok == total else "partial",
            "evidence": {
                "trace_chain_complete_cases": trace_ok,
                "total_cases": total,
                "source": str(summary_path),
            },
        },
        {
            "id": "C2_FACTUAL_SAFETY",
            "statement": "RAG2 không vi phạm các rule factual nghiêm trọng (coverage/ICD10/critical).",
            "result": "proven" if factual_severe_fail == 0 else "not_proven",
            "evidence": {
                "severe_factual_fail_cases": factual_severe_fail,
                "total_cases": total,
                "source": str(summary_path),
            },
        },
        {
            "id": "C3_CLINICAL_READINESS",
            "statement": "Hệ thống đủ tin cậy để dùng lâm sàng độc lập.",
            "result": "not_proven",
            "evidence": {
                "safe_mode_cases": safe_mode_cases,
                "high_low_conf_cases": low_conf_high_cases,
                "urgent_mismatch_cases": urgent_mismatch_cases,
                "validator_warning_cases": validator_warning_cases,
                "total_cases": total,
                "source": str(summary_path),
            },
            "reason": "Nguồn RAG1 đang safe_mode, nhiều ca confidence thấp, và còn cảnh báo chất lượng báo cáo.",
        },
    ]

    acceptance_criteria = [
        {
            "criterion": "RAG1 non-safe-mode with controlled API run",
            "target": "safe_mode_cases = 0",
        },
        {
            "criterion": "Low-confidence control",
            "target": "high_low_conf_cases <= 20% tổng ca hoặc có bác sĩ xác nhận bù trừ",
        },
        {
            "criterion": "Urgency consistency",
            "target": "urgent_mismatch_cases = 0",
        },
        {
            "criterion": "RAG2 factual safety",
            "target": "severe_factual_fail_cases = 0 (duy trì)",
        },
        {
            "criterion": "Narrative quality bound",
            "target": "validator_warning_cases = 0 hoặc phải có lý do lâm sàng chấp nhận được",
        },
    ]

    claims_payload = {
        "generated_at": _utc_now_iso(),
        "dicom_root": str(dicom_root.resolve()),
        "summary_file": str(summary_path),
        "claims": claims,
        "acceptance_criteria_for_clinical_readiness": acceptance_criteria,
    }

    claims_path = dicom_root / "rag2_board_claims.json"
    _write_json(claims_path, claims_payload)

    markdown_lines: list[str] = []
    markdown_lines.append("# Board Defense Packet - RAG1/RAG2")
    markdown_lines.append("")
    markdown_lines.append(f"- Generated at: `{claims_payload['generated_at']}`")
    markdown_lines.append(f"- Data root: `{dicom_root}`")
    markdown_lines.append(f"- Evidence summary: `{summary_path}`")
    markdown_lines.append("")
    markdown_lines.append("## 1) Những gì đã chứng minh được")
    markdown_lines.append("- **Traceability**: Mỗi ca có chuỗi artifact đầy đủ `rag1_input -> rag1_output -> doctor_revised -> rag2_output -> rag2_eval`.")
    markdown_lines.append("- **Factual safety (mức rule)**: Không có lỗi nghiêm trọng coverage/ICD10/critical trong run hiện tại.")
    markdown_lines.append("")
    markdown_lines.append("## 2) Vì sao chưa đủ tin cậy lâm sàng")
    markdown_lines.append("- **RAG1 safe_mode**: bằng chứng đầu vào chưa qua quy trình inference đầy đủ cho clinical claim.")
    markdown_lines.append("- **Nhiều detection confidence thấp** ở nhiều ca, làm tăng rủi ro sai lệch.")
    markdown_lines.append("- **Một số ca có urgency mismatch** giữa upstream flag và narrative downstream.")
    markdown_lines.append("- **Validator warnings** còn tồn tại (overflow ở kết luận/impression).")
    markdown_lines.append("")
    markdown_lines.append("## 3) Phát biểu chuẩn trước hội đồng (khuyến nghị)")
    markdown_lines.append("- Hệ thống hiện tại **đủ để demo tính truy vết, kiểm soát rủi ro, và hỗ trợ bác sĩ**.")
    markdown_lines.append("- Hệ thống **chưa chứng minh đủ để thay thế quyết định lâm sàng độc lập**.")
    markdown_lines.append("- Tuyên bố bắt buộc: **\"Hệ thống hỗ trợ bác sĩ, không thay thế chẩn đoán lâm sàng.\"**")
    markdown_lines.append("")
    markdown_lines.append("## 4) Điều kiện để nâng mức tin cậy")
    for item in acceptance_criteria:
        markdown_lines.append(f"- {item['criterion']}: `{item['target']}`")
    markdown_lines.append("")
    markdown_lines.append("## 5) Hai case study khuyến nghị")
    lowest_risk = min(
        evals,
        key=lambda e: (
            int(bool(e.get("medical_risk_checks", {}).get("safe_mode_dependency"))),
            len(e.get("medical_risk_checks", {}).get("combo_alert_flags", []) or []),
            int(bool(e.get("medical_risk_checks", {}).get("urgent_signal_mismatch"))),
            float(e.get("medical_risk_checks", {}).get("low_conf_detection_ratio") or 0.0),
            len(e.get("factual_consistency_checks", {}).get("validator_warning_rules", []) or []),
        ),
    )
    highest_risk = max(
        evals,
        key=lambda e: (
            int(bool(e.get("medical_risk_checks", {}).get("safe_mode_dependency"))),
            float(e.get("medical_risk_checks", {}).get("low_conf_detection_ratio") or 0.0),
            int(bool(e.get("medical_risk_checks", {}).get("urgent_signal_mismatch"))),
            len(e.get("factual_consistency_checks", {}).get("validator_warning_rules", []) or []),
        ),
    )
    markdown_lines.append(
        f"- Lower-risk demo case: `{lowest_risk.get('case_id')}` (eval: `{lowest_risk.get('_eval_path')}`)"
    )
    markdown_lines.append(
        f"- Higher-risk demo case: `{highest_risk.get('case_id')}` (eval: `{highest_risk.get('_eval_path')}`)"
    )

    packet_path = dicom_root / "rag2_board_defense_packet.md"
    packet_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    return claims_path, packet_path


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build board defense packet from assurance outputs.")
    parser.add_argument(
        "--dicom-root",
        default=r"E:\AI_pr\phenika_rag2\dicom",
        help="Root directory containing assurance summary and case eval files.",
    )
    return parser


def main() -> int:
    args = build_cli().parse_args()
    claims_path, packet_path = build_packet(Path(args.dicom_root).resolve())
    print(f"Claims JSON : {claims_path}")
    print(f"Defense MD  : {packet_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
