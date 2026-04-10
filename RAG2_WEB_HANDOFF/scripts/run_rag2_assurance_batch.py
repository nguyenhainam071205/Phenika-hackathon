"""
Batch runner for:
1) RAG1 output -> Doctor-Revised -> RAG2 output
2) Per-case trust/evidence evaluation (demo-safe gate)
3) Consolidated assurance reports for presentation
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import APIConnectionError, APITimeoutError, RateLimitError

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Prevent Unicode logging failures on Windows console codepages.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from rag1.kb_schema import RAG1Request, RAG1Response
from rag2.adapter import rag1_to_doctor_revised
from rag2.config import RAG2Config
from rag2.engine import RAG2Engine
from rag2.validator import validate_rag2_response


LOW_CONF_THRESHOLD = 0.50
COMBO_ALERT_FLAGS = {
    "FLAG_CARDIO_AORTIC",
    "FLAG_EFFUSION_CARDIO",
    "FLAG_PNEUMO_EFFUSION",
}
SEVERE_FACTUAL_RULES = {
    "FINDINGS_COVERAGE",
    "ICD10_FALSE_ADD",
    "CRITICAL_MISS",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    no_diacritics = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return no_diacritics.lower()


def _discover_case_dirs(dicom_root: Path) -> list[Path]:
    pattern = re.compile(r"^dicom_(\d+)\.dicom$")
    case_dirs: list[Path] = []
    for item in dicom_root.iterdir():
        if item.is_dir() and pattern.match(item.name):
            case_dirs.append(item)
    case_dirs.sort(key=lambda p: int(pattern.match(p.name).group(1)))  # type: ignore[union-attr]
    return case_dirs


def _case_stem(case_dir: Path) -> str:
    return case_dir.name.replace(".dicom", "")


def _contains_urgency_signal(rag2_output_obj: dict[str, Any]) -> bool:
    report_vi = rag2_output_obj.get("report_vi", {}) if isinstance(rag2_output_obj, dict) else {}
    report_en = rag2_output_obj.get("report_en", {}) if isinstance(rag2_output_obj, dict) else {}

    vi_ket_luan = report_vi.get("ket_luan", [])
    en_impression = report_en.get("impression", [])

    pieces: list[str] = []
    pieces.append(str(report_vi.get("de_nghi") or ""))
    pieces.append(str(report_en.get("recommendation") or ""))
    if isinstance(vi_ket_luan, list):
        pieces.extend(str(x) for x in vi_ket_luan if x is not None)
    if isinstance(en_impression, list):
        pieces.extend(str(x) for x in en_impression if x is not None)

    text = _normalize_text(" ".join(pieces))
    keywords = [
        "khan",
        "uu tien",
        "cap cuu",
        "urgent",
        "immediate",
        "emergency",
    ]
    return any(word in text for word in keywords)


def _run_case(
    case_dir: Path,
    engine: RAG2Engine,
    *,
    language: str,
    max_retries: int,
    retry_delay_seconds: float,
) -> dict[str, Any]:
    case_id = _case_stem(case_dir)
    rag1_output_path = case_dir / f"{case_id}.rag1_output.json"
    rag1_input_path = case_dir / f"{case_id}.rag1_input.json"
    doctor_revised_path = case_dir / f"{case_id}.doctor_revised.json"
    rag2_output_path = case_dir / f"{case_id}.rag2_output.json"
    eval_path = case_dir / f"{case_id}.rag2_eval.json"

    structural_checks = {
        "rag1_output_exists": rag1_output_path.exists(),
        "rag1_output_parsed": False,
        "rag1_input_exists": rag1_input_path.exists(),
        "rag1_input_parsed": False,
        "doctor_revised_written": False,
        "rag2_output_written": False,
        "rag2_output_parsed": False,
        "trace_chain_complete": False,
    }

    factual_checks: dict[str, Any] = {
        "validator_error_rules": [],
        "validator_warning_rules": [],
        "findings_count_input": None,
        "findings_count_output": None,
        "ket_luan_count": None,
        "impression_count": None,
        "icd10_subset_ok": None,
        "critical_flag_consistency_ok": None,
        "confidence_notes_error_count": 0,
    }

    medical_risk_checks: dict[str, Any] = {
        "safe_mode_dependency": None,
        "detection_count": None,
        "low_conf_threshold": LOW_CONF_THRESHOLD,
        "low_conf_detection_count": None,
        "low_conf_detection_ratio": None,
        "combo_alert_flags": [],
        "requires_urgent_action_from_rag1": None,
        "urgent_signal_reflected_in_rag2": None,
        "urgent_signal_mismatch": None,
    }

    explainability_checks: dict[str, Any] = {
        "artifact_paths": {
            "rag1_input": str(rag1_input_path),
            "rag1_output": str(rag1_output_path),
            "doctor_revised": str(doctor_revised_path),
            "rag2_output": str(rag2_output_path),
            "rag2_eval": str(eval_path),
        },
        "trace_chain_complete": False,
        "verdict_reasons_present": False,
    }

    verdict_reasons: list[str] = []
    severe_reasons: list[str] = []

    raw_rag1_output: dict[str, Any] | None = None
    raw_rag1_input: dict[str, Any] | None = None

    if not structural_checks["rag1_output_exists"]:
        severe_reasons.append("Missing RAG1 output artifact.")
    else:
        try:
            raw_rag1_output = _read_json(rag1_output_path)
            rag1_response = RAG1Response(**raw_rag1_output)
            structural_checks["rag1_output_parsed"] = True
        except Exception as exc:
            severe_reasons.append(f"RAG1 output parse failed: {exc}")
            rag1_response = None  # type: ignore[assignment]

    if structural_checks["rag1_input_exists"]:
        try:
            raw_rag1_input = _read_json(rag1_input_path)
            rag1_request = RAG1Request(**raw_rag1_input)
            structural_checks["rag1_input_parsed"] = True
        except Exception:
            rag1_request = None
            verdict_reasons.append("RAG1 input exists but cannot be parsed; medical risk checks are partial.")
    else:
        rag1_request = None
        verdict_reasons.append("RAG1 input missing; medical risk checks are partial.")

    if raw_rag1_output is not None:
        metadata = raw_rag1_output.get("metadata", {})
        final_for_fe = raw_rag1_output.get("final_for_fe", {})
        if isinstance(metadata, dict):
            medical_risk_checks["safe_mode_dependency"] = bool(metadata.get("safe_mode", False))
        if isinstance(final_for_fe, dict):
            flags = final_for_fe.get("flag_codes_final", [])
            if isinstance(flags, list):
                medical_risk_checks["combo_alert_flags"] = [
                    x for x in flags if isinstance(x, str) and x in COMBO_ALERT_FLAGS
                ]
            medical_risk_checks["requires_urgent_action_from_rag1"] = bool(
                final_for_fe.get("requires_urgent_action_final", False)
            )
        else:
            overall = raw_rag1_output.get("overall_impression", {})
            if isinstance(overall, dict):
                medical_risk_checks["requires_urgent_action_from_rag1"] = bool(
                    overall.get("requires_urgent_action", False)
                )

    if raw_rag1_input is not None:
        detections = raw_rag1_input.get("detections", [])
        if isinstance(detections, list):
            det_count = len(detections)
            low_conf_count = 0
            for det in detections:
                if isinstance(det, dict):
                    try:
                        conf = float(det.get("confidence", 0.0))
                    except Exception:
                        conf = 0.0
                    if conf < LOW_CONF_THRESHOLD:
                        low_conf_count += 1
            medical_risk_checks["detection_count"] = det_count
            medical_risk_checks["low_conf_detection_count"] = low_conf_count
            medical_risk_checks["low_conf_detection_ratio"] = (
                (low_conf_count / det_count) if det_count else 0.0
            )

    rag2_response_obj: dict[str, Any] | None = None
    if "rag1_response" in locals() and rag1_response is not None:
        try:
            revised = rag1_to_doctor_revised(
                rag1_response,
                rag1_request,  # type: ignore[arg-type]
                language=language,
            )
            doctor_revised_path.write_text(
                revised.model_dump_json(indent=2, exclude_none=False),
                encoding="utf-8",
            )
            structural_checks["doctor_revised_written"] = True
        except Exception as exc:
            severe_reasons.append(f"RAG1 -> Doctor-Revised conversion failed: {exc}")
            revised = None

        response = None
        if revised is not None:
            for attempt in range(max_retries):
                try:
                    response = engine.process(revised)
                    break
                except (RateLimitError, APIConnectionError, APITimeoutError) as exc:
                    if attempt == max_retries - 1:
                        severe_reasons.append(
                            f"RAG2 API call failed after {max_retries} attempts: {exc}"
                        )
                    else:
                        sleep_s = retry_delay_seconds * (2 ** attempt)
                        print(f"[{case_id}] transient API error; retrying in {sleep_s:.1f}s...")
                        time.sleep(sleep_s)
                except Exception as exc:
                    severe_reasons.append(f"RAG2 processing failed: {exc}")
                    break

        if response is not None:
            rag2_output_path.write_text(
                response.model_dump_json(indent=2, exclude_none=False),
                encoding="utf-8",
            )
            structural_checks["rag2_output_written"] = True
            try:
                rag2_response_obj = _read_json(rag2_output_path)
                structural_checks["rag2_output_parsed"] = True
            except Exception as exc:
                severe_reasons.append(f"RAG2 output parse failed: {exc}")

            validation = validate_rag2_response(revised, response)
            validator_error_rules = [err.rule for err in validation.errors]
            validator_warning_rules = [warn.rule for warn in validation.warnings]
            factual_checks["validator_error_rules"] = validator_error_rules
            factual_checks["validator_warning_rules"] = validator_warning_rules

            input_count = len(revised.confirmed_findings)
            output_count = response.metadata.findings_count_output
            factual_checks["findings_count_input"] = input_count
            factual_checks["findings_count_output"] = output_count
            factual_checks["ket_luan_count"] = len(response.report_vi.ket_luan)
            factual_checks["impression_count"] = len(response.report_en.impression)

            confirmed_icd = {
                f.icd10_confirmed for f in revised.confirmed_findings if f.icd10_confirmed
            }
            output_icd = {x.ma for x in response.report_vi.icd10} | {x.code for x in response.report_en.icd10}
            icd10_subset_ok = True if not confirmed_icd else output_icd.issubset(confirmed_icd)
            factual_checks["icd10_subset_ok"] = icd10_subset_ok

            input_critical = {f.det_id for f in revised.confirmed_findings if f.critical_flag}
            output_critical = set(response.metadata.critical_flags)
            critical_ok = input_critical == output_critical
            factual_checks["critical_flag_consistency_ok"] = critical_ok

            notes_error_count = len(
                [note for note in response.metadata.confidence_notes if note.startswith("[ERROR:")]
            )
            factual_checks["confidence_notes_error_count"] = notes_error_count

            if input_count != output_count:
                severe_reasons.append("Findings coverage mismatch between input and output.")
            if not icd10_subset_ok:
                severe_reasons.append("ICD-10 output is not a subset of confirmed ICD-10 input.")
            if not critical_ok:
                severe_reasons.append("Critical flag mismatch between input and output metadata.")

            severe_rules_hit = [rule for rule in validator_error_rules if rule in SEVERE_FACTUAL_RULES]
            if severe_rules_hit:
                severe_reasons.append(f"Severe validator rules failed: {', '.join(severe_rules_hit)}")

            if notes_error_count > 0:
                verdict_reasons.append(f"RAG2 emitted {notes_error_count} confidence error note(s).")

            if validator_warning_rules:
                verdict_reasons.append(f"Validator warnings present: {', '.join(validator_warning_rules)}")

            non_severe_errors = [r for r in validator_error_rules if r not in SEVERE_FACTUAL_RULES]
            if non_severe_errors:
                verdict_reasons.append(f"Non-severe validator errors present: {', '.join(non_severe_errors)}")

    if rag2_response_obj is not None:
        urgent_from_rag1 = bool(medical_risk_checks["requires_urgent_action_from_rag1"])
        urgent_reflected = _contains_urgency_signal(rag2_response_obj)
        urgent_mismatch = bool(urgent_from_rag1 and not urgent_reflected)
        medical_risk_checks["urgent_signal_reflected_in_rag2"] = urgent_reflected
        medical_risk_checks["urgent_signal_mismatch"] = urgent_mismatch
        if urgent_mismatch:
            verdict_reasons.append(
                "RAG1 marks urgent action but urgency signal is weak/absent in RAG2 narrative."
            )

    low_conf_ratio = medical_risk_checks["low_conf_detection_ratio"]
    low_conf_count = medical_risk_checks["low_conf_detection_count"]
    safe_mode_dependency = bool(medical_risk_checks["safe_mode_dependency"])
    combo_flags = medical_risk_checks["combo_alert_flags"] or []

    if safe_mode_dependency:
        verdict_reasons.append("RAG1 source was generated in safe_mode; clinical trust is limited.")
    if isinstance(low_conf_ratio, float) and low_conf_ratio >= 0.50:
        verdict_reasons.append(
            f"Low-confidence detections are high ({low_conf_count}/{medical_risk_checks['detection_count']})."
        )
    if combo_flags:
        verdict_reasons.append(f"Critical/combo alert flags detected: {', '.join(combo_flags)}")

    structural_checks["trace_chain_complete"] = all(
        [
            structural_checks["rag1_output_exists"],
            structural_checks["rag1_output_parsed"],
            structural_checks["doctor_revised_written"],
            structural_checks["rag2_output_written"],
            structural_checks["rag2_output_parsed"],
        ]
    )
    explainability_checks["trace_chain_complete"] = structural_checks["trace_chain_complete"]

    status: str
    if not structural_checks["trace_chain_complete"] or severe_reasons:
        status = "fail"
    else:
        if verdict_reasons:
            status = "warn"
        else:
            status = "pass"
            verdict_reasons.append("No critical structural/factual issues; risk within demo-safe threshold.")

    explainability_checks["verdict_reasons_present"] = bool(verdict_reasons or severe_reasons)

    final_reasons = severe_reasons + verdict_reasons
    if status == "fail":
        next_actions = [
            "Block automated downstream usage for this case.",
            "Require manual doctor review before report acceptance.",
            "Re-run with strict validation gate and corrected upstream findings.",
        ]
    elif status == "warn":
        next_actions = [
            "Proceed only in demo/support mode with clear disclaimer.",
            "Route case through human-in-the-loop confirmation before clinical use.",
            "Prioritize this case for stricter validation and model calibration review.",
        ]
    else:
        next_actions = [
            "Eligible for demo presentation with support-only disclaimer.",
            "Keep trace artifacts for audit and defense Q&A.",
        ]

    eval_payload: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "mode": "demo-safe-gate",
        "language": language,
        "case_id": case_id,
        "status": status,
        "structural_checks": structural_checks,
        "factual_consistency_checks": factual_checks,
        "medical_risk_checks": medical_risk_checks,
        "explainability_checks": explainability_checks,
        "verdict_reasons": final_reasons,
        "recommended_next_actions": next_actions,
    }
    _write_json(eval_path, eval_payload)

    return {
        "case_id": case_id,
        "status": status,
        "paths": explainability_checks["artifact_paths"],
        "summary": {
            "findings_count_input": factual_checks["findings_count_input"],
            "findings_count_output": factual_checks["findings_count_output"],
            "low_conf_ratio": medical_risk_checks["low_conf_detection_ratio"],
            "safe_mode_dependency": medical_risk_checks["safe_mode_dependency"],
            "combo_alert_flags": medical_risk_checks["combo_alert_flags"],
            "urgent_signal_mismatch": medical_risk_checks["urgent_signal_mismatch"],
        },
        "verdict_reasons": final_reasons,
    }


def _build_markdown_report(
    *,
    summary_payload: dict[str, Any],
    report_path: Path,
) -> None:
    cases: list[dict[str, Any]] = summary_payload["cases"]
    totals = summary_payload["totals"]

    pass_case = next((c for c in cases if c["status"] == "pass"), None)
    warn_or_fail_case = next((c for c in cases if c["status"] in {"warn", "fail"}), None)

    lines: list[str] = []
    lines.append("# RAG2 Assurance Report (Demo-safe gate)")
    lines.append("")
    lines.append(f"- Generated at: `{summary_payload['generated_at']}`")
    lines.append(f"- DICOM root: `{summary_payload['dicom_root']}`")
    lines.append("- Positioning: Explainability-first, support-only clinical usage.")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append(
        f"- Total cases: **{totals['total']}** | pass: **{totals['pass']}** | warn: **{totals['warn']}** | fail: **{totals['fail']}**"
    )
    lines.append("- Gate policy: structural/factual severe issues => fail; elevated medical risk => warn.")
    lines.append("- Clinical disclaimer: **He thong ho tro bac si, khong thay the chan doan lam sang.**")
    lines.append("")
    lines.append("## Case Matrix")
    lines.append("")
    lines.append("| Case | Status | Findings in/out | Low-conf ratio | Safe mode | Urgent mismatch | Top reason |")
    lines.append("|---|---|---:|---:|---|---|---|")
    for case in cases:
        s = case["summary"]
        reasons = case.get("verdict_reasons") or []
        first_reason = reasons[0] if reasons else "-"
        lines.append(
            "| {case_id} | {status} | {fi}/{fo} | {lr:.2f} | {sm} | {um} | {reason} |".format(
                case_id=case["case_id"],
                status=case["status"],
                fi=s.get("findings_count_input"),
                fo=s.get("findings_count_output"),
                lr=float(s.get("low_conf_ratio") or 0.0),
                sm=bool(s.get("safe_mode_dependency")),
                um=bool(s.get("urgent_signal_mismatch")),
                reason=first_reason.replace("|", "/"),
            )
        )
    lines.append("")
    lines.append("## Explainability Narrative")
    lines.append("- Trace chain per case: `rag1_output -> doctor_revised -> rag2_output -> rag2_eval`.")
    lines.append("- Factual checks: findings coverage, ICD-10 subset, critical flag consistency, validator errors.")
    lines.append("- Medical-risk checks: low-confidence ratio, combo flags, urgency reflection, safe_mode dependency.")
    lines.append("- Every verdict includes explicit reasons and recommended next actions.")
    lines.append("")
    lines.append("## Trust Gaps and Correction Plan")
    lines.append("- Add human-in-the-loop gate for all `warn/fail` cases before any clinical-facing usage.")
    lines.append("- Upgrade RAG2 validation to strict blocking mode for severe factual rules.")
    lines.append("- Keep per-case audit bundle for defense: source, transformation, output, and verdict reasons.")
    lines.append("- Prepare two defense case studies (one lower risk and one higher risk) with full trace evidence.")
    lines.append("")
    lines.append("## Suggested Case Studies")
    if pass_case is not None:
        lines.append(
            f"- Lower-risk example: `{pass_case['case_id']}` (status={pass_case['status']}). "
            f"Artifacts: `{pass_case['paths']['doctor_revised']}`, `{pass_case['paths']['rag2_output']}`."
        )
    else:
        lines.append("- Lower-risk example: none reached `pass` in this run.")
    if warn_or_fail_case is not None:
        lines.append(
            f"- Higher-risk example: `{warn_or_fail_case['case_id']}` (status={warn_or_fail_case['status']}). "
            f"Reason: {(warn_or_fail_case.get('verdict_reasons') or ['-'])[0]}"
        )
    else:
        lines.append("- Higher-risk example: none.")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_batch(
    *,
    dicom_root: Path,
    language: str,
    max_retries: int,
    retry_delay_seconds: float,
) -> int:
    config = RAG2Config()
    engine = RAG2Engine(config)

    case_dirs = _discover_case_dirs(dicom_root)
    if not case_dirs:
        raise FileNotFoundError(f"No case directory found at: {dicom_root}")

    cases: list[dict[str, Any]] = []
    for idx, case_dir in enumerate(case_dirs, start=1):
        print(f"\n[{idx}/{len(case_dirs)}] Processing {case_dir.name}")
        case_result = _run_case(
            case_dir,
            engine,
            language=language,
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
        )
        print(f"  -> status={case_result['status']}")
        cases.append(case_result)

    totals = {
        "total": len(cases),
        "pass": len([c for c in cases if c["status"] == "pass"]),
        "warn": len([c for c in cases if c["status"] == "warn"]),
        "fail": len([c for c in cases if c["status"] == "fail"]),
    }

    summary_payload = {
        "generated_at": _utc_now_iso(),
        "mode": "demo-safe-gate",
        "language": language,
        "dicom_root": str(dicom_root.resolve()),
        "totals": totals,
        "cases": cases,
        "recommended_global_actions": [
            "Human-in-the-loop gate for all warn/fail cases.",
            "Strict-mode validation for severe factual errors.",
            "Support-only disclaimer in every demo and report export.",
            "Keep full artifact trace for audit and defense Q&A.",
        ],
    }

    summary_path = dicom_root / "rag2_assurance_summary.json"
    report_path = dicom_root / "rag2_assurance_report.md"

    _write_json(summary_path, summary_payload)
    _build_markdown_report(summary_payload=summary_payload, report_path=report_path)

    print("\nBatch complete.")
    print(f"Summary JSON: {summary_path}")
    print(f"Report MD   : {report_path}")
    print(f"Totals      : {totals}")
    return 0


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run RAG2 batch + assurance evaluation for DICOM case folders.",
    )
    parser.add_argument(
        "--dicom-root",
        default=r"E:\AI_pr\phenika_rag2\dicom",
        help="Root directory containing dicom_X.dicom folders.",
    )
    parser.add_argument(
        "--language",
        default="vi+en",
        choices=["vi", "en", "vi+en"],
        help="RAG2 output language.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retries for RAG2 API calls on rate-limit.",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=2.0,
        help="Initial retry delay in seconds; exponential backoff per retry.",
    )
    return parser


def main() -> int:
    args = build_cli().parse_args()
    return run_batch(
        dicom_root=Path(args.dicom_root).resolve(),
        language=args.language,
        max_retries=args.max_retries,
        retry_delay_seconds=args.retry_delay_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
