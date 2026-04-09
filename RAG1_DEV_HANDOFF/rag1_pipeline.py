"""
RAG1 Pipeline CLI — Single entry point for indexing, running, and batch processing.

Usage:
    python rag1_pipeline.py index
    python rag1_pipeline.py run --dicom image_dicom/xxx.dicom --device cpu --language bilingual
    python rag1_pipeline.py batch --dicom-dir image_dicom --output-dir output_rag1 --device cpu
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

# Ensure repo root on sys.path
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _default_final_output_path(dicom_path: Path) -> Path:
    return dicom_path.with_suffix(".rag1_output.json")


def _derive_intermediate_paths(final_output_path: Path) -> tuple[Path, Path]:
    base_name = final_output_path.name
    if base_name.endswith(".rag1_output.json"):
        stem = base_name[:-len(".rag1_output.json")]
    elif final_output_path.suffix:
        stem = final_output_path.stem
    else:
        stem = base_name

    return (
        final_output_path.with_name(f"{stem}.rag1_input.json"),
        final_output_path.with_name(f"{stem}.png"),
    )


def cmd_index(args: argparse.Namespace) -> int:
    """Build the ChromaDB index from the knowledge base PDF."""
    from rag1.config import RAG1Config
    from rag1.kb_indexer import build_index

    config = RAG1Config()
    num_chunks, persist_dir = build_index(config)
    print(f"\n[OK] Index built: {num_chunks} chunks at {persist_dir}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run RAG1 on a single DICOM file."""
    from rag1.config import RAG1Config
    from rag1.engine import RAG1Engine

    try:
        from dicom_to_rag1_json import (
            build_rag1_input_payload,
            resolve_dicom_input,
            write_rag1_input_bundle,
        )

        dicom_path = resolve_dicom_input(args.dicom)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}")
        return 1

    config = RAG1Config()
    language = args.language or config.default_language
    model_path = args.model or str(config.yolo_weights_path)
    output_path = Path(args.output).resolve() if args.output else _default_final_output_path(dicom_path)
    input_json_path, input_image_path = _derive_intermediate_paths(output_path)

    # Step 1: Read DICOM and run YOLO
    print(f"\n{'='*60}")
    print(f"  RAG1 Pipeline - {dicom_path.name}")
    print(f"{'='*60}")

    print("[1/4] Reading DICOM and running YOLO...")
    device = args.device if hasattr(args, "device") and args.device else "cpu"
    request, image_rgb, runtime_bundle = build_rag1_input_payload(
        dicom_path=dicom_path,
        model_arg=model_path,
        device=device,
        query_id=args.query_id,
        language=language,
        rag_mode=args.rag_mode,
        top_k=args.top_k,
    )
    write_rag1_input_bundle(
        request=request,
        image_rgb=image_rgb,
        output_json_path=input_json_path,
        output_image_path=input_image_path,
    )
    dicom_block = runtime_bundle["dicom"]
    detector_block = runtime_bundle["detector"]
    print(f"  Model   : {detector_block['model_path']}")
    print(f"  Input   : {input_json_path}")
    print(f"  Image   : {input_image_path}")
    print(f"  Query   : {request.query_id}")
    print(f"  Detected {len(request.detections)} abnormalities")
    if not request.detections:
        print("  (No abnormalities detected - generating normal report)")

    # Step 2: RAG1 Engine
    print("[3/4] RAG1 Engine processing...")
    engine = RAG1Engine(config)

    response = engine.process(request)

    # Step 3: Output
    print("[4/4] Writing output...")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        response.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )

    print(f"\n{'='*60}")
    print("  [OK] RAG1 Complete")
    print(f"  Bundle  : {input_json_path} + {input_image_path}")
    print(f"  Output  : {output_path}")
    print(f"  Findings: {len(response.results_per_detection)}")
    print(f"  Overall : {response.overall_impression.overall_severity}")
    print(f"  Time    : {response.metadata.processing_time_ms}ms")
    print(f"{'='*60}\n")

    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    """Batch process all DICOM files in a directory."""
    dicom_dir = Path(args.dicom_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not dicom_dir.exists():
        print(f"[ERROR] DICOM directory not found: {dicom_dir}")
        return 1

    # Find all .dicom files (in subdirectories)
    dicom_files = []
    for sub in sorted(dicom_dir.iterdir()):
        if sub.is_dir() and sub.suffix == ".dicom":
            for f in sub.iterdir():
                if f.suffix == ".dicom":
                    dicom_files.append(f)

    if not dicom_files:
        print(f"[ERROR] No .dicom files found in {dicom_dir}")
        return 1

    print(f"\n[INFO] Found {len(dicom_files)} DICOM files in {dicom_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    for i, dicom_path in enumerate(dicom_files, 1):
        print(f"\n--- [{i}/{len(dicom_files)}] {dicom_path.stem} ---")
        out_path = output_dir / f"{dicom_path.stem}.rag1_output.json"
        # Reuse cmd_run logic
        run_args = argparse.Namespace(
            dicom=str(dicom_path),
            output=str(out_path),
            model=args.model if hasattr(args, "model") else None,
            device=args.device if hasattr(args, "device") else "cpu",
            language=args.language if hasattr(args, "language") else "vi",
            rag_mode=args.rag_mode if hasattr(args, "rag_mode") else "findings_draft",
            top_k=args.top_k if hasattr(args, "top_k") else 5,
            query_id=None,
        )
        try:
            cmd_run(run_args)
        except Exception as exc:
            print(f"  [WARN] Error: {exc}")
            continue

    print(f"\n[OK] Batch complete: {len(dicom_files)} files -> {output_dir}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Quick demo with synthetic detections (no DICOM/YOLO needed)."""
    from rag1.config import RAG1Config
    from rag1.engine import RAG1Engine
    from rag1.kb_schema import (
        Detection,
        ImageSize,
        PatientContext,
        RAG1Request,
    )

    config = RAG1Config()
    language = args.language if hasattr(args, "language") and args.language else "vi"

    print(f"\n{'='*60}")
    print("  RAG1 Demo - Synthetic detections")
    print(f"{'='*60}")

    # Create sample detections
    detections = [
        Detection(
            det_id=0,
            class_id=10,
            class_name="Pleural Effusion",
            bbox_xyxy=[100, 200, 400, 500],
            bbox_norm=[0.1, 0.2, 0.4, 0.5],
            confidence=0.87,
            laterality="Right",
            severity_hint="moderate",
        ),
        Detection(
            det_id=1,
            class_id=3,
            class_name="Cardiomegaly",
            bbox_xyxy=[200, 150, 600, 550],
            bbox_norm=[0.2, 0.15, 0.6, 0.55],
            confidence=0.72,
            laterality="Central",
            severity_hint="moderate",
        ),
    ]

    engine = RAG1Engine(config)
    request = RAG1Request(
        query_id=str(uuid.uuid4()),
        study_id="DEMO_STUDY",
        image_id="DEMO_IMAGE",
        image_size=ImageSize(width=1024, height=1024),
        detections=detections,
        patient_context=PatientContext(age=65, sex="M"),
        language=language,
        top_k=5,
    )

    response = engine.process(request)

    # Print response
    output_json = response.model_dump_json(indent=2, exclude_none=True)

    output_path = Path("demo_rag1_output.json")
    output_path.write_text(output_json, encoding="utf-8")

    print(f"\n[OK] Demo complete -> {output_path}")
    print(f"  Findings: {len(response.results_per_detection)}")
    print(f"  Overall: {response.overall_impression.overall_severity}")
    print(f"  Time: {response.metadata.processing_time_ms}ms")

    return 0


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RAG1 Pipeline — Medical X-ray Knowledge Retrieval",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # index
    sub.add_parser("index", help="Build ChromaDB index from knowledge base PDF")

    # run
    run_cmd = sub.add_parser("run", help="Process a single DICOM file")
    run_cmd.add_argument("--dicom", required=True, help="Path to DICOM file or .dicom wrapper directory")
    run_cmd.add_argument("--output", default=None, help="Final RAG1 output JSON path")
    run_cmd.add_argument("--model", default=None, help="YOLO model path; defaults to Results/v3/weights/best.pt")
    run_cmd.add_argument("--device", default="cpu", help="Device: 0 or cpu")
    run_cmd.add_argument("--language", default="vi", choices=["vi", "en"])
    run_cmd.add_argument("--rag-mode", default="findings_draft", choices=["findings_draft", "ddx_only", "severity_only"])
    run_cmd.add_argument("--top-k", type=int, default=5)
    run_cmd.add_argument("--query-id", default=None)

    # batch
    batch_cmd = sub.add_parser("batch", help="Batch process DICOM directory")
    batch_cmd.add_argument("--dicom-dir", required=True, help="DICOM directory")
    batch_cmd.add_argument("--output-dir", default="output_rag1", help="Output directory")
    batch_cmd.add_argument("--model", default=None, help="YOLO model path")
    batch_cmd.add_argument("--device", default="cpu", help="Device")
    batch_cmd.add_argument("--language", default="vi", choices=["vi", "en"])
    batch_cmd.add_argument("--rag-mode", default="findings_draft", choices=["findings_draft", "ddx_only", "severity_only"])
    batch_cmd.add_argument("--top-k", type=int, default=5)

    # demo
    demo_cmd = sub.add_parser("demo", help="Quick demo with synthetic detections")
    demo_cmd.add_argument("--language", default="vi", choices=["vi", "en"])

    return parser


def main() -> int:
    parser = build_cli()
    args = parser.parse_args()

    commands = {
        "index": cmd_index,
        "run": cmd_run,
        "batch": cmd_batch,
        "demo": cmd_demo,
    }

    handler = commands.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
