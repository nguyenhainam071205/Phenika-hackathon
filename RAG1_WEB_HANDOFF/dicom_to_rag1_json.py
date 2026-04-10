"""
DICOM -> YOLO -> RAG 1 JSON exporter.

This script reads a single DICOM chest X-ray, extracts DICOM metadata,
renders the image for YOLO inference, runs the detector, derives
geometry and image-plane measurements from bounding boxes, and writes
the intermediate RAG1 input bundle: one JSON file plus one rendered PNG.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rag1.config import RAG1Config
from rag1.kb_schema import (
    Detection,
    DetectionCropArtifact,
    ImageSize,
    PatientContext,
    RAG1Request,
    SourceContext,
)
from rag1.yolo_runtime import (
    CLASS_NAMES,
    apply_class_threshold,
    build_runtime_cfg,
    resolve_model_path,
)


SCHEMA_VERSION = "rag1.input.from_dicom.v1"
THRESHOLD_POLICY = "per_class_v1"
OPPOSITE_MARKER = {
    "L": "R",
    "R": "L",
    "A": "P",
    "P": "A",
    "H": "F",
    "F": "H",
    "S": "I",
    "I": "S",
    "U": "U",
    "B": "B",
}


def _lazy_import_dicom() -> tuple[Any, Any]:
    try:
        import pydicom
        from pydicom.pixel_data_handlers.util import apply_voi_lut
    except ImportError as exc:
        raise RuntimeError(
            "pydicom is required to read DICOM files. Install pydicom in the Python "
            "environment that will run this script."
        ) from exc
    return pydicom, apply_voi_lut


def _lazy_import_yolo() -> Any:
    try:
        from ultralytics import YOLO
    except Exception as exc:
        raise RuntimeError(
            "ultralytics is unavailable. "
            "Install the dependencies from requirements_rag1.txt in the active Python environment."
        ) from exc
    return YOLO


def _lazy_import_pil_image() -> Any:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required to save rendered PNG files for the RAG1 input bundle."
        ) from exc
    return Image


def resolve_dicom_input(path_value: str | Path) -> Path:
    """Accept either a DICOM file or a `.dicom` wrapper directory."""
    dicom_path = Path(path_value).expanduser().resolve()
    if not dicom_path.exists():
        raise FileNotFoundError(f"Could not find DICOM input: {dicom_path}")

    if dicom_path.is_dir():
        nested_files = sorted(
            item for item in dicom_path.iterdir() if item.is_file() and item.suffix.lower() == ".dicom"
        )
        if len(nested_files) == 1:
            return nested_files[0]
        raise FileNotFoundError(
            f"Expected a single .dicom file inside wrapper directory: {dicom_path}"
        )

    return dicom_path


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _round_float(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _to_float_list(value: Any) -> list[float] | None:
    if value is None:
        return None
    try:
        items = list(value)
    except TypeError:
        items = [value]

    converted: list[float] = []
    for item in items:
        try:
            converted.append(float(item))
        except (TypeError, ValueError):
            return None
    return converted


def _to_str_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    try:
        items = list(value)
    except TypeError:
        items = [value]

    converted = []
    for item in items:
        text = _safe_text(item)
        if text is None:
            return None
        converted.append(text)
    return converted


def _normalize_to_uint8(data: np.ndarray) -> np.ndarray:
    data = np.asarray(data, dtype=np.float32)
    min_value = float(np.min(data))
    max_value = float(np.max(data))
    if max_value <= min_value:
        return np.zeros(data.shape, dtype=np.uint8)
    scaled = (data - min_value) / (max_value - min_value)
    scaled = np.clip(scaled * 255.0, 0, 255)
    return scaled.astype(np.uint8)


def _as_posix_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def _opposite_marker(marker: str | None) -> str | None:
    if marker is None:
        return None
    return OPPOSITE_MARKER.get(marker.upper())


def _primary_orientation_from_vector(vector: list[float]) -> str | None:
    arr = np.asarray(vector, dtype=np.float32)
    if arr.shape != (3,) or not np.all(np.isfinite(arr)):
        return None

    idx = int(np.argmax(np.abs(arr)))
    magnitude = float(abs(arr[idx]))
    if magnitude < 0.5:
        return None

    if idx == 0:
        return "L" if arr[idx] > 0 else "R"
    if idx == 1:
        return "P" if arr[idx] > 0 else "A"
    return "H" if arr[idx] > 0 else "F"


def _markers_from_patient_orientation(patient_orientation: list[str] | None) -> dict[str, Any] | None:
    if not patient_orientation or len(patient_orientation) < 2:
        return None

    left = _safe_text(patient_orientation[0])
    bottom = _safe_text(patient_orientation[1])
    if left is None or bottom is None:
        return None

    left = left.upper()
    bottom = bottom.upper()
    right = _opposite_marker(left)
    top = _opposite_marker(bottom)
    if right is None or top is None:
        return None

    return {
        "left": left,
        "right": right,
        "top": top,
        "bottom": bottom,
        "status": "from_dicom",
    }


def _markers_from_image_orientation(image_orientation_patient: list[float] | None) -> dict[str, Any] | None:
    if not image_orientation_patient or len(image_orientation_patient) != 6:
        return None

    right = _primary_orientation_from_vector(image_orientation_patient[:3])
    bottom = _primary_orientation_from_vector(image_orientation_patient[3:])
    left = _opposite_marker(right)
    top = _opposite_marker(bottom)

    if right is None or bottom is None or left is None or top is None:
        return None

    return {
        "left": left,
        "right": right,
        "top": top,
        "bottom": bottom,
        "status": "from_dicom",
    }


def _resolve_display_markers(
    patient_orientation: list[str] | None,
    image_orientation_patient: list[float] | None,
) -> dict[str, Any]:
    markers = _markers_from_image_orientation(image_orientation_patient)
    if markers is not None:
        markers["source"] = "image_orientation_patient"
        return markers

    markers = _markers_from_patient_orientation(patient_orientation)
    if markers is not None:
        markers["source"] = "patient_orientation"
        return markers

    return {
        "left": None,
        "right": None,
        "top": None,
        "bottom": None,
        "status": "unknown",
        "source": "unavailable",
    }


def _parse_view_code(sequence_value: Any) -> dict[str, Any] | None:
    if not sequence_value:
        return None

    try:
        first_item = sequence_value[0]
    except (TypeError, IndexError):
        return None

    code_value = _safe_text(first_item.get("CodeValue"))
    coding_scheme_designator = _safe_text(first_item.get("CodingSchemeDesignator"))
    code_meaning = _safe_text(first_item.get("CodeMeaning"))

    if code_value is None and coding_scheme_designator is None and code_meaning is None:
        return None

    return {
        "code_value": code_value,
        "coding_scheme_designator": coding_scheme_designator,
        "code_meaning": code_meaning,
    }


def _read_and_render_dicom(dicom_path: Path) -> dict[str, Any]:
    pydicom, apply_voi_lut = _lazy_import_dicom()
    dataset = pydicom.dcmread(str(dicom_path))

    try:
        pixel_array = dataset.pixel_array
    except Exception as exc:
        raise RuntimeError(f"Failed to decode pixel data from DICOM: {dicom_path}") from exc

    if np.asarray(pixel_array).ndim == 3:
        if np.asarray(pixel_array).shape[0] == 1:
            pixel_array = np.asarray(pixel_array)[0]
        else:
            raise ValueError("Multi-frame DICOM is not supported in v1.")

    voi_lut_applied = False
    try:
        if hasattr(dataset, "VOILUTSequence") or hasattr(dataset, "WindowCenter") or hasattr(dataset, "WindowWidth"):
            pixel_array = apply_voi_lut(pixel_array, dataset)
            voi_lut_applied = True
    except Exception:
        pixel_array = dataset.pixel_array

    image = np.asarray(pixel_array, dtype=np.float32)
    if image.ndim != 2:
        raise ValueError("Only 2D single-frame DICOM images are supported in v1.")

    photometric_interpretation = (_safe_text(dataset.get("PhotometricInterpretation")) or "").upper()
    presentation_lut_shape = (_safe_text(dataset.get("PresentationLUTShape")) or "").upper()

    monochrome_inversion_applied = False
    if photometric_interpretation == "MONOCHROME1":
        image = np.max(image) - image
        monochrome_inversion_applied = True

    if presentation_lut_shape == "INVERSE":
        image = np.max(image) - image

    image_uint8 = _normalize_to_uint8(image)
    image_rgb = np.repeat(image_uint8[..., None], 3, axis=2)

    patient_orientation = _to_str_list(dataset.get("PatientOrientation"))
    image_orientation_patient = _to_float_list(dataset.get("ImageOrientationPatient"))
    image_position_patient = _to_float_list(dataset.get("ImagePositionPatient"))
    pixel_spacing_mm = _to_float_list(dataset.get("PixelSpacing"))
    imager_pixel_spacing_mm = _to_float_list(dataset.get("ImagerPixelSpacing"))

    display_markers = _resolve_display_markers(
        patient_orientation=patient_orientation,
        image_orientation_patient=image_orientation_patient,
    )

    dicom_block = {
        "path": _as_posix_path(dicom_path),
        "study_instance_uid": _safe_text(dataset.get("StudyInstanceUID")),
        "series_instance_uid": _safe_text(dataset.get("SeriesInstanceUID")),
        "sop_instance_uid": _safe_text(dataset.get("SOPInstanceUID")),
        "modality": _safe_text(dataset.get("Modality")),
        "body_part_examined": _safe_text(dataset.get("BodyPartExamined")),
        "view_position": _safe_text(dataset.get("ViewPosition")),
        "view_code": _parse_view_code(dataset.get("ViewCodeSequence")),
        "patient_orientation": patient_orientation,
        "image_orientation_patient": image_orientation_patient,
        "image_position_patient": image_position_patient,
        "image_laterality": _safe_text(dataset.get("ImageLaterality")),
        "photometric_interpretation": _safe_text(dataset.get("PhotometricInterpretation")),
        "presentation_lut_shape": _safe_text(dataset.get("PresentationLUTShape")),
        "pixel_spacing_mm": pixel_spacing_mm,
        "imager_pixel_spacing_mm": imager_pixel_spacing_mm,
        "rows": int(getattr(dataset, "Rows", image_uint8.shape[0])),
        "columns": int(getattr(dataset, "Columns", image_uint8.shape[1])),
    }

    display_block = {
        "display_markers": display_markers,
        "rendering": {
            "voi_lut_applied": voi_lut_applied,
            "monochrome_inversion_applied": monochrome_inversion_applied,
        },
    }

    return {
        "dicom": dicom_block,
        "display": display_block,
        "image_rgb": image_rgb,
    }


def _derive_model_name(model_path: Path) -> str:
    pattern = re.compile(r"(yolo\d+[a-z])", re.IGNORECASE)
    for part in reversed(model_path.parts):
        match = pattern.search(part)
        if match:
            return match.group(1).lower()
    return model_path.stem


def _clip_box(box: np.ndarray, width: int, height: int) -> list[int]:
    x1, y1, x2, y2 = [float(v) for v in box.tolist()]
    x1 = max(0.0, min(x1, float(width)))
    y1 = max(0.0, min(y1, float(height)))
    x2 = max(0.0, min(x2, float(width)))
    y2 = max(0.0, min(y2, float(height)))
    return [int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))]


def _horizontal_bucket(center_x: float, image_width: int) -> str:
    if center_x < image_width / 3.0:
        return "left"
    if center_x > (2.0 * image_width / 3.0):
        return "right"
    return "midline"


def _vertical_bucket_simple(center_y: float, image_height: int) -> str:
    if center_y < image_height / 3.0:
        return "upper"
    if center_y > (2.0 * image_height / 3.0):
        return "lower"
    return "mid"


def _vertical_bucket_span(y1: int, y2: int, image_height: int) -> str:
    boundaries = [0.0, image_height / 3.0, 2.0 * image_height / 3.0, float(image_height)]
    labels = ["upper", "mid", "lower"]
    touched: list[str] = []

    for idx, label in enumerate(labels):
        zone_start = boundaries[idx]
        zone_end = boundaries[idx + 1]
        if y2 > zone_start and y1 < zone_end:
            touched.append(label)

    if not touched:
        return "unknown"
    if len(touched) == 1:
        return touched[0]
    if touched == ["upper", "mid"]:
        return "upper_mid"
    if touched == ["mid", "lower"]:
        return "mid_lower"
    if touched == ["upper", "mid", "lower"]:
        return "diffuse"
    return "_".join(touched)


def _patient_side_from_markers(horizontal_bucket: str, display_markers: dict[str, Any]) -> str:
    if horizontal_bucket == "midline":
        return "midline"

    edge_marker = display_markers.get(horizontal_bucket)
    if edge_marker == "L":
        return "left"
    if edge_marker == "R":
        return "right"
    return horizontal_bucket


def _location_context(
    bbox_xyxy_px: list[int],
    image_width: int,
    image_height: int,
    display_markers: dict[str, Any],
) -> dict[str, Any]:
    x1, y1, x2, y2 = bbox_xyxy_px
    center_x = (x1 + x2) / 2.0
    center_y = (y1 + y2) / 2.0

    horizontal_region_guess = _horizontal_bucket(center_x, image_width)
    patient_side_guess = _patient_side_from_markers(horizontal_region_guess, display_markers)
    vertical_region_guess = _vertical_bucket_span(y1, y2, image_height)
    vertical_region_simple = _vertical_bucket_simple(center_y, image_height)

    if patient_side_guess == "midline":
        region_label = "midline"
    else:
        region_label = f"{patient_side_guess}_{vertical_region_simple}"

    return {
        "patient_side_guess": patient_side_guess,
        "horizontal_region_guess": horizontal_region_guess,
        "vertical_region_guess": vertical_region_guess,
        "region_label": region_label,
        "bbox_region_guess": region_label,
        "source": "dicom_orientation_plus_bbox"
        if display_markers.get("status") == "from_dicom"
        else "bbox_only_fallback",
    }


def _geometry_from_bbox(bbox_xyxy_px: list[int], image_width: int, image_height: int) -> dict[str, Any]:
    x1, y1, x2, y2 = bbox_xyxy_px
    width_px = max(0, x2 - x1)
    height_px = max(0, y2 - y1)
    area_px2 = width_px * height_px
    center_px = [int(round((x1 + x2) / 2.0)), int(round((y1 + y2) / 2.0))]

    return {
        "width_px": width_px,
        "height_px": height_px,
        "area_px2": area_px2,
        "center_px": center_px,
        "width_norm": _round_float(width_px / image_width if image_width else 0.0),
        "height_norm": _round_float(height_px / image_height if image_height else 0.0),
        "area_ratio": _round_float(area_px2 / float(image_width * image_height) if image_width and image_height else 0.0),
    }


def _image_plane_measurements(
    bbox_xyxy_px: list[int],
    pixel_spacing_mm: list[float] | None,
) -> dict[str, Any]:
    x1, y1, x2, y2 = bbox_xyxy_px
    width_px = max(0, x2 - x1)
    height_px = max(0, y2 - y1)

    if pixel_spacing_mm and len(pixel_spacing_mm) >= 2:
        row_spacing_mm = float(pixel_spacing_mm[0])
        col_spacing_mm = float(pixel_spacing_mm[1])
        width_mm = width_px * col_spacing_mm
        height_mm = height_px * row_spacing_mm
        return {
            "width_mm": _round_float(width_mm, 4),
            "height_mm": _round_float(height_mm, 4),
            "max_diameter_mm": _round_float(max(width_mm, height_mm), 4),
            "area_mm2": _round_float(width_mm * height_mm, 4),
            "measurement_basis": "pixel_spacing_image_plane",
        }

    return {
        "width_mm": None,
        "height_mm": None,
        "max_diameter_mm": None,
        "area_mm2": None,
        "measurement_basis": "unavailable_without_pixel_spacing",
    }


def _build_detection_records(
    boxes_xyxy: np.ndarray,
    scores: np.ndarray,
    labels: np.ndarray,
    image_width: int,
    image_height: int,
    class_names: list[str],
    pixel_spacing_mm: list[float] | None,
    display_markers: dict[str, Any],
) -> list[dict[str, Any]]:
    if len(labels) == 0:
        return []

    order = sorted(
        range(len(labels)),
        key=lambda idx: (-float(scores[idx]), int(labels[idx]), idx),
    )

    detections: list[dict[str, Any]] = []
    for det_index, source_index in enumerate(order, start=1):
        bbox_xyxy_px = _clip_box(boxes_xyxy[source_index], image_width, image_height)
        class_id = int(labels[source_index])
        class_name = class_names[class_id] if 0 <= class_id < len(class_names) else str(class_id)
        confidence = _round_float(float(scores[source_index]), 6)

        detections.append(
            {
                "detection_id": f"det-{det_index:03d}",
                "class_id": class_id,
                "class_name": class_name,
                "confidence": confidence,
                "bbox_xyxy_px": bbox_xyxy_px,
                "geometry_from_bbox": _geometry_from_bbox(bbox_xyxy_px, image_width, image_height),
                "image_plane_measurements": _image_plane_measurements(
                    bbox_xyxy_px=bbox_xyxy_px,
                    pixel_spacing_mm=pixel_spacing_mm,
                ),
                "location_context": _location_context(
                    bbox_xyxy_px=bbox_xyxy_px,
                    image_width=image_width,
                    image_height=image_height,
                    display_markers=display_markers,
                ),
            }
        )

    return detections


def _run_detector(
    image_rgb: np.ndarray,
    model_arg: str | None,
    device: str,
    dicom_block: dict[str, Any],
    display_markers: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    YOLO = _lazy_import_yolo()
    resolved_model_path = resolve_model_path(model_path=model_arg, config=RAG1Config())
    runtime_cfg = build_runtime_cfg(device=device)

    model = YOLO(str(resolved_model_path))
    result = model.predict(source=image_rgb, **runtime_cfg)[0]

    if len(result.boxes):
        boxes_xyxy = result.boxes.xyxy.cpu().numpy()
        scores = result.boxes.conf.cpu().numpy()
        labels = result.boxes.cls.cpu().numpy().astype(int)
        boxes_xyxy, scores, labels = apply_class_threshold(boxes_xyxy, scores, labels)
    else:
        boxes_xyxy = np.zeros((0, 4), dtype=np.float32)
        scores = np.zeros(0, dtype=np.float32)
        labels = np.zeros(0, dtype=int)

    detections = _build_detection_records(
        boxes_xyxy=boxes_xyxy,
        scores=scores,
        labels=labels,
        image_width=int(dicom_block["columns"]),
        image_height=int(dicom_block["rows"]),
        class_names=CLASS_NAMES,
        pixel_spacing_mm=dicom_block.get("pixel_spacing_mm"),
        display_markers=display_markers,
    )

    detector_block = {
        "model_name": _derive_model_name(resolved_model_path),
        "model_path": _as_posix_path(resolved_model_path),
        "threshold_policy": THRESHOLD_POLICY,
    }
    return detector_block, detections


def _build_request_id(dicom_path: Path, explicit_request_id: str | None) -> str:
    if explicit_request_id:
        return explicit_request_id
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"req-{timestamp}-{dicom_path.stem}"


def _unsupported_clinical_indices() -> dict[str, Any]:
    return {
        "cardiothoracic_ratio": None,
        "aortic_width_index": None,
        "pneumothorax_size_index": None,
        "reason": "requires dedicated landmark_or_segmentation_module",
    }


def _default_output_path(dicom_path: Path) -> Path:
    return dicom_path.with_suffix(".rag1_input.json")


def _default_image_output_path(json_path: Path) -> Path:
    base_name = json_path.name
    if base_name.endswith(".rag1_input.json"):
        stem = base_name[:-len(".rag1_input.json")]
    elif json_path.suffix:
        stem = json_path.stem
    else:
        stem = base_name
    return json_path.with_name(f"{stem}.png")


def _default_crop_dir(output_image_path: Path) -> Path:
    return output_image_path.with_name(f"{output_image_path.stem}_crops")


def _laterality_from_location_context(location_context: dict[str, Any] | None) -> str:
    patient_side = (location_context or {}).get("patient_side_guess", "N/A")
    laterality_map = {
        "left": "Left",
        "right": "Right",
        "midline": "Central",
    }
    return laterality_map.get(str(patient_side).lower(), "N/A")


def _bbox_norm_from_xyxy(
    bbox_xyxy_px: list[int],
    image_width: int,
    image_height: int,
) -> list[float]:
    if not image_width or not image_height:
        return [0.0, 0.0, 0.0, 0.0]
    x1, y1, x2, y2 = bbox_xyxy_px
    return [
        round(x1 / image_width, 4),
        round(y1 / image_height, 4),
        round(x2 / image_width, 4),
        round(y2 / image_height, 4),
    ]


def _to_rag1_request(
    raw_detections: list[dict[str, Any]],
    dicom_block: dict[str, Any],
    image_width: int,
    image_height: int,
    query_id: str,
    language: str,
    rag_mode: str,
    top_k: int,
    patient_context: PatientContext | None = None,
) -> RAG1Request:
    detections: list[Detection] = []
    for det_index, det in enumerate(raw_detections):
        bbox_xyxy = list(det["bbox_xyxy_px"])
        detections.append(
            Detection(
                det_id=det_index,
                class_id=det["class_id"],
                class_name=det["class_name"],
                bbox_xyxy=bbox_xyxy,
                bbox_norm=_bbox_norm_from_xyxy(bbox_xyxy, image_width, image_height),
                confidence=det["confidence"],
                laterality=_laterality_from_location_context(det.get("location_context")),
                severity_hint="unknown",
            )
        )

    dicom_stem = Path(dicom_block.get("path", "unknown")).stem
    study_id = dicom_block.get("study_instance_uid") or f"study_{dicom_stem}"
    image_id = dicom_block.get("sop_instance_uid") or f"image_{dicom_stem}"

    if patient_context is None:
        patient_context = PatientContext(
            age=dicom_block.get("patient_age"),
            sex=dicom_block.get("patient_sex", "unknown"),
            clinical_notes=dicom_block.get("study_description", ""),
        )

    return RAG1Request(
        query_id=query_id,
        study_id=study_id,
        image_id=image_id,
        image_size=ImageSize(width=image_width, height=image_height),
        detections=detections,
        patient_context=patient_context,
        rag_mode=rag_mode,
        language=language,
        top_k=top_k,
        source_context=SourceContext(
            dicom_path=_as_posix_path(Path(dicom_block.get("path", dicom_stem))),
        ),
    )


def build_rag1_input_payload(
    dicom_path: Path,
    model_arg: str | None,
    device: str,
    query_id: str | None = None,
    language: str = "vi",
    rag_mode: str = "findings_draft",
    top_k: int = 5,
    patient_context: PatientContext | None = None,
) -> tuple[RAG1Request, np.ndarray, dict[str, Any]]:
    resolved_dicom_path = resolve_dicom_input(dicom_path)
    dicom_payload = _read_and_render_dicom(resolved_dicom_path)
    detector_block, detections = _run_detector(
        image_rgb=dicom_payload["image_rgb"],
        model_arg=model_arg,
        device=device,
        dicom_block=dicom_payload["dicom"],
        display_markers=dicom_payload["display"]["display_markers"],
    )
    image_rgb = dicom_payload["image_rgb"]
    image_height, image_width = image_rgb.shape[:2]

    request = _to_rag1_request(
        raw_detections=detections,
        dicom_block=dicom_payload["dicom"],
        image_width=image_width,
        image_height=image_height,
        query_id=_build_request_id(resolved_dicom_path, query_id),
        language=language,
        rag_mode=rag_mode,
        top_k=top_k,
        patient_context=patient_context,
    )
    runtime_bundle = {
        "dicom": dicom_payload["dicom"],
        "display": dicom_payload["display"],
        "detector": detector_block,
        "raw_detections": detections,
        "unsupported_clinical_indices": _unsupported_clinical_indices(),
    }
    return request, image_rgb, runtime_bundle


def write_rag1_input_bundle(
    request: RAG1Request,
    image_rgb: np.ndarray,
    output_json_path: Path,
    output_image_path: Path | None = None,
) -> tuple[Path, Path]:
    output_json_path = output_json_path.expanduser().resolve()
    output_image_path = (
        output_image_path.expanduser().resolve()
        if output_image_path is not None
        else _default_image_output_path(output_json_path)
    )

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_image_path.parent.mkdir(parents=True, exist_ok=True)

    Image = _lazy_import_pil_image()
    Image.fromarray(image_rgb).save(output_image_path)

    crop_dir = _default_crop_dir(output_image_path)
    crop_dir.mkdir(parents=True, exist_ok=True)
    crop_artifacts: list[DetectionCropArtifact] = []
    image_height, image_width = image_rgb.shape[:2]
    for detection in request.detections:
        x1, y1, x2, y2 = detection.bbox_xyxy
        x1 = max(0, min(int(x1), image_width))
        y1 = max(0, min(int(y1), image_height))
        x2 = max(x1 + 1, min(int(x2), image_width))
        y2 = max(y1 + 1, min(int(y2), image_height))
        crop = image_rgb[y1:y2, x1:x2]
        crop_path = crop_dir / f"det_{detection.det_id:03d}.png"
        Image.fromarray(crop).save(crop_path)
        crop_artifacts.append(
            DetectionCropArtifact(det_id=detection.det_id, path=_as_posix_path(crop_path))
        )

    request.source_context.rendered_image_path = _as_posix_path(output_image_path)
    request.source_context.crop_dir = _as_posix_path(crop_dir)
    request.source_context.detection_crops = crop_artifacts

    output_json_path.write_text(
        json.dumps(request.model_dump(mode="json", exclude_none=False), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_json_path, output_image_path


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read one DICOM, run YOLO, and export a JSON payload for RAG 1."
    )
    parser.add_argument(
        "--dicom",
        required=True,
        help="Path to a single DICOM file or a .dicom wrapper directory.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output JSON path. Defaults to <same_stem>.rag1_input.json next to the DICOM.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional YOLO model path. Defaults to Results/v3/weights/best.pt.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Device passed to YOLO, for example: 0 or cpu.",
    )
    parser.add_argument(
        "--language",
        default="vi",
        choices=["vi", "en"],
        help="Language stored in the RAG1 Request JSON.",
    )
    parser.add_argument(
        "--rag-mode",
        default="findings_draft",
        choices=["findings_draft", "ddx_only", "severity_only"],
        help="RAG mode stored in the RAG1 Request JSON.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="top_k stored in the RAG1 Request JSON.",
    )
    parser.add_argument(
        "--query-id",
        "--request-id",
        dest="query_id",
        default=None,
        help="Optional query identifier written into the RAG1 Request JSON.",
    )
    return parser


def main() -> None:
    args = build_cli().parse_args()

    dicom_path = resolve_dicom_input(args.dicom)
    output_json_path = (
        Path(args.output).expanduser().resolve() if args.output else _default_output_path(dicom_path)
    )

    request, image_rgb, _runtime_bundle = build_rag1_input_payload(
        dicom_path=dicom_path,
        model_arg=args.model,
        device=args.device,
        query_id=args.query_id,
        language=args.language,
        rag_mode=args.rag_mode,
        top_k=args.top_k,
    )
    output_json_path, output_image_path = write_rag1_input_bundle(
        request=request,
        image_rgb=image_rgb,
        output_json_path=output_json_path,
    )
    print(f"Wrote RAG1 Request JSON: {output_json_path}")
    print(f"Wrote rendered image : {output_image_path}")


if __name__ == "__main__":
    main()
