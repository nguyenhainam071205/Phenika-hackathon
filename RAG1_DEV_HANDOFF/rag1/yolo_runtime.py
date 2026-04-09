"""
YOLO runtime helpers dedicated to the DICOM -> RAG1 pipeline.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from rag1.config import RAG1Config


CLASS_NAMES = [
    "Aortic enlargement",
    "Atelectasis",
    "Calcification",
    "Cardiomegaly",
    "Consolidation",
    "ILD",
    "Infiltration",
    "Lung Opacity",
    "Nodule/Mass",
    "Other lesion",
    "Pleural effusion",
    "Pleural thickening",
    "Pneumothorax",
    "Pulmonary fibrosis",
]

CLASS_CONF_THRESHOLD = {
    0: 0.20,
    1: 0.15,
    2: 0.20,
    3: 0.20,
    4: 0.15,
    5: 0.15,
    6: 0.15,
    7: 0.20,
    8: 0.15,
    9: 0.20,
    10: 0.20,
    11: 0.20,
    12: 0.15,
    13: 0.15,
}

YOLO_PREDICT_CFG = {
    "conf": 0.10,
    "iou": 0.45,
    "imgsz": 640,
    "device": "cpu",
    "half": False,
    "augment": True,
    "max_det": 300,
    "verbose": False,
}


def resolve_model_path(model_path: str | None = None, config: RAG1Config | None = None) -> Path:
    cfg = config or RAG1Config()

    if model_path:
        candidate = Path(model_path).expanduser()
        if not candidate.is_absolute():
            candidate = (cfg.repo_root / candidate).resolve()
        else:
            candidate = candidate.resolve()
    else:
        candidate = cfg.yolo_weights_path.resolve()

    if not candidate.exists():
        raise FileNotFoundError(f"YOLO weights not found: {candidate}")

    return candidate


def build_runtime_cfg(device: str = "cpu") -> dict[str, object]:
    runtime_cfg = dict(YOLO_PREDICT_CFG)
    runtime_cfg["device"] = device
    runtime_cfg["half"] = str(device).lower() != "cpu"
    return runtime_cfg


def apply_class_threshold(
    boxes: np.ndarray,
    scores: np.ndarray,
    labels: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    keep = []
    for index, (score, label) in enumerate(zip(scores, labels)):
        threshold = CLASS_CONF_THRESHOLD.get(int(label), 0.20)
        if float(score) >= threshold:
            keep.append(index)

    if not keep:
        return (
            np.zeros((0, 4), dtype=np.float32),
            np.zeros(0, dtype=np.float32),
            np.zeros(0, dtype=int),
        )

    return boxes[keep], scores[keep], labels[keep]
