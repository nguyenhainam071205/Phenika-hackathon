"""
RAG2 Pipeline CLI - Entry point for indexing, generating, and demo.

Usage:
    python rag2_pipeline.py index
    python rag2_pipeline.py generate --input doctor_revised.json --output report.json
    python rag2_pipeline.py demo [--language vi+en]
    python rag2_pipeline.py demo-from-rag1 --rag1-output demo_rag1_output.json
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

# Ensure repo root on sys.path
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def cmd_index(args: argparse.Namespace) -> int:
    """Build the ChromaDB index from RAG2 knowledge base."""
    from rag2.config import RAG2Config
    from rag2.kb_builder import build_index

    config = RAG2Config()
    num_chunks, persist_dir = build_index(config)
    print(f"\n[OK] RAG2 index built: {num_chunks} chunks at {persist_dir}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate a report from a Doctor-Revised JSON file."""
    from rag2.config import RAG2Config
    from rag2.engine import RAG2Engine
    from rag2.schema import DoctorRevisedJSON

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        print(f"[ERROR] Input file not found: {input_path}")
        return 1

    # Load Doctor-Revised JSON
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    revised = DoctorRevisedJSON(**raw)

    # Process
    config = RAG2Config()
    engine = RAG2Engine(config)
    response = engine.process(revised)

    # Write output
    output_path = Path(args.output).resolve() if args.output else input_path.with_suffix(
        ".rag2_output.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        response.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )

    print(f"\n[OK] Report generated -> {output_path}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Quick demo with synthetic Doctor-Revised JSON."""
    from rag2.config import RAG2Config
    from rag2.engine import RAG2Engine
    from rag2.schema import (
        ConfirmedFinding,
        DoctorGlobalAssessment,
        DoctorRevisedJSON,
        Measurements,
        PatientContext,
        RAG2RequestConfig,
        Technique,
    )

    config = RAG2Config()
    language = args.language if hasattr(args, "language") and args.language else "vi+en"

    print(f"\n{'='*60}")
    print("  RAG2 Demo - Synthetic Doctor-Revised JSON")
    print(f"{'='*60}")

    # Create a demo Doctor-Revised JSON matching spec Section 9
    revised = DoctorRevisedJSON(
        query_id=str(uuid.uuid4()),
        study_id="DEMO_STUDY_001",
        image_id="DEMO_IMAGE_001",
        revision_id=str(uuid.uuid4()),
        revised_at="2026-04-07T10:30:00+07:00",
        revised_by="DR-DEMO",
        technique=Technique(
            view="PA", position="erect", image_quality="adequate"
        ),
        confirmed_findings=[
            ConfirmedFinding(
                det_id=0,
                class_id=10,
                class_name="Pleural Effusion",
                source="ai_confirmed",
                laterality="Right",
                severity="moderate",
                severity_source="doctor",
                bbox_xyxy=[600, 700, 950, 980],
                doctor_note="Tràn dịch màng phổi phải mức độ vừa, góc sườn hoành phải tù rõ.",
                measurements=Measurements(max_depth_mm=45),
                icd10_suggested="J90",
                icd10_confirmed="J90",
            ),
            ConfirmedFinding(
                det_id=1,
                class_id=3,
                class_name="Cardiomegaly",
                source="ai_modified",
                laterality="Central",
                severity="mild",
                severity_source="doctor",
                bbox_xyxy=[380, 290, 680, 650],
                rag1_impression_accepted=False,
                rag1_impression_override="Bóng tim to nhẹ, chỉ số tim/lồng ngực (CTR) khoảng 0,52.",
                measurements=Measurements(ctr=0.52),
                icd10_suggested="I51.7",
                icd10_confirmed="I51.7",
            ),
            ConfirmedFinding(
                det_id=2,
                class_id=4,
                class_name="Consolidation",
                source="doctor_added",
                laterality="Right",
                severity="moderate",
                severity_source="doctor",
                bbox_xyxy=[600, 500, 950, 700],
                doctor_note="Đám mờ đồng nhất thùy dưới phổi phải kèm dấu hiệu khí phế quản đồ.",
                measurements=Measurements(length_mm=80),
                icd10_suggested="J18.9",
                icd10_confirmed="J18.9",
            ),
        ],
        normal_structures=["Aorta", "Bones", "Soft tissue", "Trachea"],
        doctor_global_assessment=DoctorGlobalAssessment(
            overall_severity="moderate",
            requires_urgent_action=False,
            free_text_summary="Tràn dịch màng phổi phải vừa kết hợp đám mờ thùy dưới phải, nghi viêm phổi. Tim to nhẹ.",
        ),
        patient_context=PatientContext(
            age=65,
            sex="M",
            clinical_notes="Sốt 38,5°C, ho có đờm 5 ngày. Tiền sử tăng huyết áp.",
        ),
        rag2_config=RAG2RequestConfig(language=language),
    )

    engine = RAG2Engine(config)
    response = engine.process(revised)

    # Write output
    output_path = Path("demo_rag2_output.json")
    output_path.write_text(
        response.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )

    print(f"\n{'='*60}")
    print("  [OK] RAG2 Demo Complete")
    print(f"  Output  : {output_path}")
    print(f"  Vi KL   : {len(response.report_vi.ket_luan)} items")
    print(f"  En IMP  : {len(response.report_en.impression)} items")
    print(f"  Time    : {response.metadata.processing_time_ms}ms")
    print(f"{'='*60}\n")

    return 0


def cmd_demo_from_rag1(args: argparse.Namespace) -> int:
    """
    Run RAG2 from existing RAG1 output - full auto pipeline.

    RAG1 output -> adapter -> RAG2 -> report
    """
    from rag1.kb_schema import RAG1Request, RAG1Response
    from rag2.adapter import rag1_to_doctor_revised
    from rag2.config import RAG2Config
    from rag2.engine import RAG2Engine

    rag1_output_path = Path(args.rag1_output).resolve()
    if not rag1_output_path.exists():
        print(f"[ERROR] RAG1 output file not found: {rag1_output_path}")
        return 1

    language = args.language if hasattr(args, "language") and args.language else "vi+en"

    print(f"\n{'='*60}")
    print("  RAG2 Demo from RAG1 Output - Auto Pipeline")
    print(f"{'='*60}")

    # Load RAG1 output
    print("[1/3] Loading RAG1 output...")
    raw = json.loads(rag1_output_path.read_text(encoding="utf-8"))
    rag1_response = RAG1Response(**raw)
    print(f"  RAG1 findings: {len(rag1_response.results_per_detection)}")

    # Load RAG1 input if available (for patient context)
    rag1_request = None
    rag1_input_path = rag1_output_path.with_name(
        rag1_output_path.name.replace(".rag1_output.", ".rag1_input.")
    )
    if rag1_input_path.exists():
        try:
            raw_req = json.loads(rag1_input_path.read_text(encoding="utf-8"))
            rag1_request = RAG1Request(**raw_req)
            print(f"  RAG1 input loaded: {rag1_input_path.name}")
        except Exception:
            print("  RAG1 input not loadable, using defaults")

    # Adapter: RAG1 -> Doctor-Revised JSON
    print("[2/3] Converting via adapter...")
    revised = rag1_to_doctor_revised(
        rag1_response, rag1_request, language=language
    )
    print(f"  Confirmed findings: {len(revised.confirmed_findings)}")

    # Save intermediate Doctor-Revised JSON for inspection
    revised_path = rag1_output_path.with_suffix(".doctor_revised.json")
    revised_path.write_text(
        revised.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )
    print(f"  Doctor-Revised JSON -> {revised_path.name}")

    # RAG2 Engine
    print("[3/3] Running RAG2 Engine...")
    config = RAG2Config()
    engine = RAG2Engine(config)
    response = engine.process(revised)

    # Write output
    output_path = (
        Path(args.output).resolve()
        if args.output
        else rag1_output_path.with_suffix(".rag2_output.json")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        response.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )

    print(f"\n{'='*60}")
    print("  [OK] RAG2 Auto Pipeline Complete")
    print(f"  RAG1 input : {rag1_output_path.name}")
    print(f"  Adapter    : {revised_path.name}")
    print(f"  Report     : {output_path.name}")
    print(f"  Vi KL      : {len(response.report_vi.ket_luan)} items")
    print(f"  En IMP     : {len(response.report_en.impression)} items")
    print(f"  Time       : {response.metadata.processing_time_ms}ms")
    print(f"{'='*60}\n")

    return 0


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RAG2 Pipeline - Medical X-ray Report Generation (BYT Standard)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # index
    sub.add_parser("index", help="Build ChromaDB index from RAG2 knowledge base")

    # generate
    gen_cmd = sub.add_parser("generate", help="Generate report from Doctor-Revised JSON")
    gen_cmd.add_argument("--input", required=True, help="Path to Doctor-Revised JSON file")
    gen_cmd.add_argument("--output", default=None, help="Output report JSON path")

    # demo
    demo_cmd = sub.add_parser("demo", help="Quick demo with synthetic data")
    demo_cmd.add_argument("--language", default="vi+en", choices=["vi", "en", "vi+en"])

    # demo-from-rag1
    rag1_cmd = sub.add_parser(
        "demo-from-rag1",
        help="Auto pipeline: RAG1 output -> adapter -> RAG2 report"
    )
    rag1_cmd.add_argument(
        "--rag1-output", required=True,
        help="Path to RAG1 output JSON file"
    )
    rag1_cmd.add_argument("--output", default=None, help="Output report JSON path")
    rag1_cmd.add_argument("--language", default="vi+en", choices=["vi", "en", "vi+en"])

    return parser


def main() -> int:
    parser = build_cli()
    args = parser.parse_args()

    commands = {
        "index": cmd_index,
        "generate": cmd_generate,
        "demo": cmd_demo,
        "demo-from-rag1": cmd_demo_from_rag1,
    }

    handler = commands.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
