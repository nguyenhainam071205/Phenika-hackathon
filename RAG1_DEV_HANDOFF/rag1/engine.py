"""
RAG1 Engine — Orchestrates retrieval → generation → response assembly.

Main entry point: RAG1Engine.process(request) → RAG1Response
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from rag1.config import RAG1Config
from rag1.flags import (
    generate_flags_for_detection,
    generate_flags_for_image,
    has_critical_flag,
)
from rag1.kb_schema import (
    CLASS_INFO,
    Detection,
    DetectionResult,
    FindingsDraft,
    DifferentialDiagnosis,
    Flag,
    OverallImpression,
    RAG1Metadata,
    RAG1Request,
    RAG1Response,
    RetrievedChunk,
)
from rag1.prompts import (
    FINDING_PER_DETECTION_TEMPLATE,
    NO_DETECTION_IMPRESSION,
    OVERALL_IMPRESSION_TEMPLATE,
    SYSTEM_PROMPT,
    format_chunks_for_prompt,
    get_language_instruction,
)
from rag1.retriever import HybridRetriever


def _find_class_info(class_id: int) -> dict[str, str]:
    for info in CLASS_INFO:
        if int(info["id"]) == class_id:
            return info
    return {"id": str(class_id), "en": f"Class_{class_id}", "vi": f"Lớp_{class_id}", "icd10": ""}


def _extract_json(text: str) -> dict[str, Any]:
    """
    Extract JSON from LLM response, handling markdown code blocks.
    """
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding JSON object in the text
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    # Fallback: return empty dict
    return {}


class RAG1Engine:
    """
    Main RAG1 orchestrator.

    Usage:
        engine = RAG1Engine()
        response = engine.process(request)
    """

    def __init__(self, config: RAG1Config | None = None) -> None:
        self.config = config or RAG1Config()
        self.config.validate()

        self._retriever = HybridRetriever(self.config)
        self._llm = OpenAI(
            base_url=self.config.api_base_url,
            api_key=self.config.github_token,
        )
        print(f"[RAG1 Engine] Initialized with model={self.config.llm_model}")

    def _call_llm(self, system: str, user: str) -> str:
        """Call LLM via OpenAI-compatible API."""
        response = self._llm.chat.completions.create(
            model=self.config.llm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        return response.choices[0].message.content or ""

    def _kb_timestamp(self) -> str:
        try:
            modified = self.config.kb_pdf_path.stat().st_mtime
        except FileNotFoundError:
            return ""
        return datetime.fromtimestamp(modified, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    def _generate_finding(
        self,
        detection: Detection,
        chunks: list[RetrievedChunk],
        language: str,
    ) -> FindingsDraft:
        """Generate findings draft for a single detection."""
        info = _find_class_info(detection.class_id)

        chunks_text = format_chunks_for_prompt([
            {
                "section": c.section,
                "content": c.content,
                "relevance_score": c.relevance_score,
            }
            for c in chunks
        ])

        prompt = FINDING_PER_DETECTION_TEMPLATE.format(
            class_name=info["en"],
            class_name_vi=info["vi"],
            icd10=info["icd10"],
            confidence=detection.confidence,
            laterality=detection.laterality,
            severity_hint=detection.severity_hint,
            bbox_norm=detection.bbox_norm or detection.bbox_xyxy,
            retrieved_chunks_text=chunks_text,
            language_instruction=get_language_instruction(language),
        )

        raw = self._call_llm(SYSTEM_PROMPT, prompt)
        parsed = _extract_json(raw)

        # Build DDx list
        ddx_list = []
        for ddx_item in parsed.get("differential_diagnosis", []):
            if isinstance(ddx_item, dict):
                ddx_list.append(DifferentialDiagnosis(
                    dx=ddx_item.get("dx", ""),
                    likelihood=ddx_item.get("likelihood", "possible"),
                ))

        severity = parsed.get("severity_assessment", "unknown")

        # Generate rule-based flags
        rule_flags = generate_flags_for_detection(detection, severity)

        return FindingsDraft(
            impression=parsed.get("impression", ""),
            severity_assessment=severity,
            severity_confidence=float(parsed.get("severity_confidence", 0.0)),
            differential_diagnosis=ddx_list,
            recommended_next_steps=parsed.get("recommended_next_steps", ""),
            critical_flag=parsed.get("critical_flag", False) or has_critical_flag(rule_flags),
            flags=rule_flags,
        )

    def _generate_overall(
        self,
        results: list[DetectionResult],
        language: str,
    ) -> OverallImpression:
        """Generate overall impression for all detections."""
        if not results:
            prompt = NO_DETECTION_IMPRESSION.format(
                language_instruction=get_language_instruction(language),
            )
        else:
            summary_parts = []
            for r in results:
                info = _find_class_info(r.class_id)
                finding = r.findings_draft
                summary_parts.append(
                    f"- det_id={r.det_id}: {info['en']} ({info['vi']}), "
                    f"laterality={r.laterality}, "
                    f"severity={finding.severity_assessment}, "
                    f"critical={finding.critical_flag}"
                )

            prompt = OVERALL_IMPRESSION_TEMPLATE.format(
                detections_summary="\n".join(summary_parts),
                language_instruction=get_language_instruction(language),
            )

        raw = self._call_llm(SYSTEM_PROMPT, prompt)
        parsed = _extract_json(raw)

        return OverallImpression(
            summary=parsed.get("summary", ""),
            most_critical_det_id=parsed.get("most_critical_det_id"),
            overall_severity=parsed.get("overall_severity", "unknown"),
            requires_urgent_action=parsed.get("requires_urgent_action", False),
        )

    def process(self, request: RAG1Request) -> RAG1Response:
        """
        Process a full RAG1 request: retrieve → generate → assemble response.
        """
        start_time = time.time()
        language = request.language or self.config.default_language

        detection_results: list[DetectionResult] = []

        for detection in request.detections:
            print(f"  [det-{detection.det_id:03d}] {detection.class_name} "
                  f"conf={detection.confidence:.2f} lat={detection.laterality}")

            # Retrieve knowledge
            chunks = self._retriever.retrieve(
                class_id=detection.class_id,
                class_name=detection.class_name,
                laterality=detection.laterality,
                severity_hint=detection.severity_hint,
                top_k=request.top_k,
            )
            print(f"    Retrieved {len(chunks)} chunks")

            # Generate finding
            finding = self._generate_finding(detection, chunks, language)
            print(f"    Severity={finding.severity_assessment}, "
                  f"critical={finding.critical_flag}")

            detection_results.append(DetectionResult(
                det_id=detection.det_id,
                class_id=detection.class_id,
                class_name=detection.class_name,
                laterality=detection.laterality,
                bbox_norm=detection.bbox_norm,
                retrieved_chunks=chunks,
                findings_draft=finding,
            ))

        # Image-level flags
        image_flags = generate_flags_for_image(request.detections, detection_results)
        if image_flags:
            # Attach image-level flags to the first detection result
            if detection_results:
                detection_results[0].findings_draft.flags.extend(image_flags)

        # Overall impression
        print("  [overall] Generating overall impression...")
        overall = self._generate_overall(detection_results, language)

        elapsed_ms = int((time.time() - start_time) * 1000)

        return RAG1Response(
            query_id=request.query_id,
            study_id=request.study_id,
            image_id=request.image_id,
            results_per_detection=detection_results,
            overall_impression=overall,
            metadata=RAG1Metadata(
                rag_version="2.0",
                kb_version="RAG1_KB_v2.0",
                model_used=self.config.llm_model,
                kb_timestamp=self._kb_timestamp(),
                processing_time_ms=elapsed_ms,
            ),
        )
