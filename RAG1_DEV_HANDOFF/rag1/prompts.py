"""
Prompt templates for RAG1 Gemini/OpenAI generation.

All prompts support bilingual (vi/en) output.
"""

from __future__ import annotations

SYSTEM_PROMPT = """You are a senior radiologist AI assistant specialized in chest X-ray interpretation.
You analyze YOLO-detected abnormalities on chest X-rays and generate structured medical findings.

CRITICAL RULES:
1. Base your analysis ONLY on the provided knowledge base chunks and detection data
2. Never fabricate medical information — if uncertain, say so explicitly
3. Use standard radiology reporting language (ACR BI-RADS style)
4. Always include severity assessment, differential diagnosis, and next steps
5. Flag critical findings that require urgent clinical action

OUTPUT FORMAT: You must respond in valid JSON only. No markdown, no explanation outside JSON.
"""

FINDING_PER_DETECTION_TEMPLATE = """Based on the following YOLO detection and retrieved medical knowledge, generate a structured finding.

## Detection Info
- Class: {class_name} ({class_name_vi})
- ICD-10: {icd10}
- Confidence: {confidence:.2f}
- Laterality: {laterality}
- Severity Hint: {severity_hint}
- Bounding Box (normalized): {bbox_norm}

## Retrieved Knowledge Base Chunks
{retrieved_chunks_text}

## Output Language
{language_instruction}

Generate a JSON object with these exact fields:
{{
  "impression": "string — X-ray description for this detection (2-4 sentences)",
  "severity_assessment": "mild | moderate | severe",
  "severity_confidence": 0.0 to 1.0,
  "differential_diagnosis": [
    {{"dx": "diagnosis name", "likelihood": "likely | possible | unlikely"}}
  ],
  "recommended_next_steps": "string — clinical recommendations",
  "critical_flag": true/false
}}

Respond with ONLY the JSON object, no other text.
"""

OVERALL_IMPRESSION_TEMPLATE = """Based on all detected abnormalities in this chest X-ray, generate an overall impression summary.

## All Detections Summary
{detections_summary}

## Output Language
{language_instruction}

Generate a JSON object with these exact fields:
{{
  "summary": "string — comprehensive summary of ALL findings (3-5 sentences)",
  "most_critical_det_id": integer or null,
  "overall_severity": "mild | moderate | severe",
  "requires_urgent_action": true/false
}}

Respond with ONLY the JSON object, no other text.
"""

NO_DETECTION_IMPRESSION = """No abnormalities were detected by the YOLO model in this chest X-ray image.

## Output Language
{language_instruction}

Generate a JSON object:
{{
  "summary": "string — normal findings statement",
  "most_critical_det_id": null,
  "overall_severity": "normal",
  "requires_urgent_action": false
}}

Respond with ONLY the JSON object, no other text.
"""


def get_language_instruction(language: str) -> str:
    """Return instruction for output language."""
    if language == "vi":
        return "Viết hoàn toàn bằng TIẾNG VIỆT. Dùng thuật ngữ y khoa tiếng Việt chuẩn."
    elif language == "en":
        return "Write entirely in ENGLISH. Use standard medical radiology terminology."
    else:  # bilingual
        return (
            "Viết SONG NGỮ: mỗi trường text viết tiếng Việt trước, "
            "sau đó tiếng Anh trong ngoặc vuông [English]. "
            "Ví dụ: 'Tràn dịch màng phổi phải mức độ trung bình [Moderate right pleural effusion]'"
        )


def format_chunks_for_prompt(chunks: list[dict]) -> str:
    """Format retrieved chunks into readable text for the prompt."""
    if not chunks:
        return "(No relevant knowledge chunks retrieved)"

    parts = []
    for i, chunk in enumerate(chunks, 1):
        section = chunk.get("section", "unknown")
        content = chunk.get("content", "")
        score = chunk.get("relevance_score", 0.0)
        parts.append(
            f"### Chunk {i} [section={section}, relevance={score:.2f}]\n{content}"
        )
    return "\n\n".join(parts)
