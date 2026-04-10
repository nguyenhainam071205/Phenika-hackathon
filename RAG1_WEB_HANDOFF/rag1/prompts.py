"""
Prompt templates for RAG1 generation.
"""

from __future__ import annotations


SYSTEM_PROMPT = """You are a senior radiology AI assistant specialized in chest X-ray interpretation.
You receive YOLO detections, quantitative measurements derived from bounding boxes, and retrieved knowledge base chunks.

Rules:
1. Use only the supplied evidence.
2. Do not invent patient context or measurements.
3. If the measurement evidence is weak, say so in the impression.
4. Return valid JSON only.
"""


FINDING_PER_DETECTION_TEMPLATE = """Based on the following chest X-ray detection, draft a structured finding.

## Detection Info
- Class: {class_name} ({class_name_vi})
- ICD-10: {icd10}
- Confidence: {confidence:.2f}
- Laterality: {laterality}
- Bounding Box (normalized): {bbox_norm}

## Quantitative Evidence
- Area Ratio: {area_ratio}
- Width Ratio: {width_ratio}
- Height Ratio: {height_ratio}
{ctr_line}

## Patient Context
- Age: {patient_age}
- Sex: {patient_sex}
- Clinical Notes: {clinical_notes}

## Severity Rules
- Cardiomegaly: estimated CTR > 0.6 = severe, 0.5-0.6 = moderate, otherwise mild.
- Pleural Effusion: area_ratio > 0.15 = severe, 0.05-0.15 = moderate, otherwise mild.
- Pneumothorax: area_ratio > 0.10 = severe, 0.03-0.10 = moderate, otherwise mild.
- Lung Opacity / Consolidation / Infiltration: area_ratio > 0.10 = severe, 0.03-0.10 = moderate, otherwise mild.
- For other classes, quantitative evidence is supportive only and should not be treated as definitive severity by itself.

## Retrieved Structured Knowledge
{retrieved_chunks_text}

## Output Language
{language_instruction}

Return a JSON object with exactly these fields:
{{
  "impression": "string",
  "severity_assessment": "mild | moderate | severe | unknown",
  "severity_confidence": 0.0,
  "differential_diagnosis": [
    {{"dx": "diagnosis name", "likelihood": "likely | possible | unlikely"}}
  ],
  "recommended_next_steps": "string",
  "critical_flag": false
}}
"""


OVERALL_IMPRESSION_TEMPLATE = """Based on all detected abnormalities in this chest X-ray, generate an overall impression summary.

## All Detections Summary
{detections_summary}

## Output Language
{language_instruction}

Return a JSON object with exactly these fields:
{{
  "summary": "string",
  "most_critical_det_id": null,
  "overall_severity": "mild | moderate | severe",
  "requires_urgent_action": false
}}
"""


NO_DETECTION_IMPRESSION = """No abnormalities were detected by the YOLO model in this chest X-ray image.

## Output Language
{language_instruction}

Return a JSON object:
{{
  "summary": "string",
  "most_critical_det_id": null,
  "overall_severity": "normal",
  "requires_urgent_action": false
}}
"""


def get_language_instruction(language: str) -> str:
    if language == "vi":
        return "Write entirely in Vietnamese using standard radiology terminology."
    if language == "en":
        return "Write entirely in English using standard radiology terminology."
    return "Write bilingually: Vietnamese first, then English in brackets."


def format_chunks_for_prompt(chunks: list[dict]) -> str:
    if not chunks:
        return "(No relevant knowledge chunks retrieved)"

    parts = []
    for i, chunk in enumerate(chunks, 1):
        section = chunk.get("section", "unknown")
        content = chunk.get("content", "")
        score = chunk.get("relevance_score", 0.0)
        parts.append(f"### Chunk {i} [section={section}, relevance={score:.2f}]\n{content}")
    return "\n\n".join(parts)
