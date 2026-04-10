from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dicom_to_rag1_json import build_rag1_input_payload, write_rag1_input_bundle
from rag1.config import RAG1Config
from rag1.engine import RAG1Engine
from rag1.flags import generate_image_flag_hits
from rag1.kb_schema import SECTION_TYPES


EVAL_ROOT = ROOT / "RAG1_DEV_HANDOFF" / "evals" / "20260410_rag1_hybrid_v1"
DICOM_ROOT = ROOT / "dicom"


def _draft_view(response_dict: dict) -> dict:
    return {
        "query_id": response_dict["query_id"],
        "study_id": response_dict["study_id"],
        "image_id": response_dict["image_id"],
        "results_per_detection": [
            {
                "det_id": item["det_id"],
                "class_id": item["class_id"],
                "class_name": item["class_name"],
                "laterality": item["laterality"],
                "retrieved_chunks": item["retrieved_chunks"],
                "findings_draft": item["findings_draft"],
            }
            for item in response_dict["results_per_detection"]
        ],
        "overall_impression": response_dict["overall_impression"],
        "metadata": response_dict["metadata"],
    }


def _case_summary(sample: str, request_dict: dict, response_dict: dict) -> dict:
    findings = response_dict["final_for_fe"]["findings"]
    image_hits = generate_image_flag_hits(
        [type("Det", (), det) for det in request_dict["detections"]]
    )
    expected_combo_flags = sorted(hit["code"] for hit in image_hits if hit["code"] != "FLAG_MULTILESION")
    final_flag_codes = sorted(response_dict["final_for_fe"]["flag_codes_final"])
    structured_gaps = []
    severity_mismatches = []
    needs_review = []
    vision_statuses = []
    vision_candidates = []

    for item in response_dict["results_per_detection"]:
        sections = {chunk["section"] for chunk in item["retrieved_chunks"]}
        missing_sections = sorted(section for section in SECTION_TYPES if section not in sections)
        if missing_sections:
            structured_gaps.append({"det_id": item["det_id"], "missing_sections": missing_sections})
        draft = item["findings_draft"]["severity_assessment"]
        final = item["adjudication"]["severity_final"]
        if draft != final:
            severity_mismatches.append(
                {
                    "det_id": item["det_id"],
                    "class_name": item["class_name"],
                    "draft": draft,
                    "final": final,
                    "source": item["adjudication"]["severity_source"],
                }
            )
        if item["adjudication"]["needs_review"]:
            needs_review.append(
                {
                    "det_id": item["det_id"],
                    "class_name": item["class_name"],
                    "rationale": item["adjudication"]["rationale"],
                }
            )
        evidence = item.get("quantitative_evidence", {})
        vision_statuses.append(
            {
                "det_id": item["det_id"],
                "class_name": item["class_name"],
                "status": evidence.get("vision_verification_status", "unknown"),
                "support": evidence.get("vision_support", "unknown"),
                "explanation": evidence.get("vision_explanation", ""),
            }
        )
        if evidence.get("vision_candidate"):
            vision_candidates.append(
                {
                    "det_id": item["det_id"],
                    "class_name": item["class_name"],
                    "reasons": evidence.get("vision_candidate_reasons", []),
                }
            )

    return {
        "sample": sample,
        "study_id": request_dict["study_id"],
        "image_id": request_dict["image_id"],
        "patient_context_missing": (
            request_dict["patient_context"]["age"] is None
            and request_dict["patient_context"]["sex"] == "unknown"
            and not request_dict["patient_context"]["clinical_notes"]
        ),
        "det_count": len(request_dict["detections"]),
        "overall_severity_final": response_dict["final_for_fe"]["overall_severity_final"],
        "requires_urgent_action_final": response_dict["final_for_fe"]["requires_urgent_action_final"],
        "most_critical_det_id_final": response_dict["final_for_fe"]["most_critical_det_id_final"],
        "expected_combo_flags": expected_combo_flags,
        "final_flag_codes": final_flag_codes,
        "severity_mismatches": severity_mismatches,
        "needs_review": needs_review,
        "vision_candidates": vision_candidates,
        "vision_statuses": vision_statuses,
        "structured_section_gaps": structured_gaps,
        "findings_count": len(findings),
        "safe_mode": response_dict["metadata"].get("safe_mode", False),
        "vision_verification_mode": response_dict["metadata"].get("vision_verification_mode", "unknown"),
        "api_retry_policy": response_dict["metadata"].get("api_retry_policy", ""),
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    config = RAG1Config()
    engine = RAG1Engine(config)
    EVAL_ROOT.mkdir(parents=True, exist_ok=True)

    rows = []
    for wrapper_dir in sorted(DICOM_ROOT.glob("dicom_*.dicom")):
        dicom_path = wrapper_dir / f"{wrapper_dir.stem}.dicom"
        if not dicom_path.exists():
            continue

        sample = wrapper_dir.stem
        case_root = EVAL_ROOT / sample
        input_dir = case_root / "input"
        draft_dir = case_root / "draft"
        final_dir = case_root / "final"

        request, image_rgb, runtime_bundle = build_rag1_input_payload(
            dicom_path=dicom_path,
            model_arg=str(config.yolo_weights_path),
            device="cpu",
            language="vi",
            rag_mode="findings_draft",
            top_k=5,
        )
        input_json_path = input_dir / f"{sample}.rag1_input.json"
        input_png_path = input_dir / f"{sample}.png"
        write_rag1_input_bundle(
            request=request,
            image_rgb=image_rgb,
            output_json_path=input_json_path,
            output_image_path=input_png_path,
        )

        response = engine.process(request)
        response_dict = response.model_dump(mode="json", exclude_none=False)
        request_dict = request.model_dump(mode="json", exclude_none=False)
        draft_payload = _draft_view(response_dict)
        qa_payload = _case_summary(sample, request_dict, response_dict)

        _write_json(draft_dir / f"{sample}.rag1_output.draft.json", draft_payload)
        _write_json(draft_dir / f"{sample}.rag1_output.full.json", response_dict)
        _write_json(final_dir / "final_for_fe.json", response_dict["final_for_fe"])
        _write_json(case_root / "qa.json", qa_payload)

        rows.append(
            {
                "sample": sample,
                "study_id": request.study_id,
                "image_id": request.image_id,
                "patient_context_missing": qa_payload["patient_context_missing"],
                "det_count": qa_payload["det_count"],
                "overall_severity_final": qa_payload["overall_severity_final"],
                "requires_urgent_action_final": qa_payload["requires_urgent_action_final"],
                "most_critical_det_id_final": qa_payload["most_critical_det_id_final"],
                "expected_combo_flags": "|".join(qa_payload["expected_combo_flags"]),
                "final_flag_codes": "|".join(qa_payload["final_flag_codes"]),
                "needs_review_count": len(qa_payload["needs_review"]),
                "vision_candidate_count": len(qa_payload["vision_candidates"]),
                "severity_mismatch_count": len(qa_payload["severity_mismatches"]),
                "structured_gap_count": len(qa_payload["structured_section_gaps"]),
                "safe_mode": qa_payload["safe_mode"],
                "vision_mode": qa_payload["vision_verification_mode"],
                "detector_model": runtime_bundle["detector"]["model_name"],
            }
        )

    csv_path = EVAL_ROOT / "summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)

    md_lines = [
        "# RAG1 Hybrid Evaluation",
        "",
        f"- Cases: {len(rows)}",
        f"- Output root: `{EVAL_ROOT}`",
        "",
        "| sample | study_id | image_id | det_count | overall_final | urgent | expected_combo_flags | final_flag_codes | needs_review | vision_candidates | severity_mismatch | retrieval_gaps | safe_mode | vision_mode |",
        "| --- | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        md_lines.append(
            f"| {row['sample']} | {row['study_id']} | {row['image_id']} | {row['det_count']} | "
            f"{row['overall_severity_final']} | {row['requires_urgent_action_final']} | "
            f"{row['expected_combo_flags'] or '-'} | {row['final_flag_codes'] or '-'} | "
            f"{row['needs_review_count']} | {row['vision_candidate_count']} | {row['severity_mismatch_count']} | {row['structured_gap_count']} | "
            f"{row['safe_mode']} | {row['vision_mode']} |"
        )

    (EVAL_ROOT / "summary.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"Evaluation written to {EVAL_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
