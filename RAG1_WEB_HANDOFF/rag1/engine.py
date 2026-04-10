"""
RAG1 Engine - retrieval, draft generation, quantitative adjudication, FE output.
"""

from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from rag1.config import RAG1Config
from rag1.flags import (
    generate_flags_for_detection,
    generate_image_flag_hits,
    has_critical_flag,
)
from rag1.kb_schema import (
    CLASS_INFO,
    Detection,
    DetectionAdjudication,
    DetectionResult,
    DifferentialDiagnosis,
    FinalFindingForFE,
    FinalForFE,
    FindingsDraft,
    Flag,
    OverallImpression,
    PatientContext,
    QuantitativeEvidence,
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
from rag1.runtime_support import JsonDiskCache, file_sha256, is_rate_limit_error, is_transient_api_error, stable_hash


SEVERITY_RANK = {
    "normal": 0,
    "mild": 1,
    "moderate": 2,
    "severe": 3,
    "unknown": -1,
}

QUANT_PRIMARY_CLASSES = {1, 3, 4, 6, 7, 10, 12}
SUPPORT_ONLY_CLASSES = {0, 2, 5, 8, 9, 11, 13}
IMAGE_LEVEL_ALERT_FLAGS = {"FLAG_CARDIO_AORTIC", "FLAG_EFFUSION_CARDIO", "FLAG_PNEUMO_EFFUSION"}


def _find_class_info(class_id: int) -> dict[str, str]:
    for info in CLASS_INFO:
        if int(info["id"]) == class_id:
            return info
    return {"id": str(class_id), "en": f"Class_{class_id}", "vi": f"Class_{class_id}", "icd10": ""}


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start:brace_end + 1])
        except json.JSONDecodeError:
            pass

    return {}


def _severity_max(left: str, right: str) -> str:
    return left if SEVERITY_RANK.get(left, -1) >= SEVERITY_RANK.get(right, -1) else right


def _compute_bbox_metrics(detection: Detection) -> dict[str, Any]:
    bbox = detection.bbox_norm if len(detection.bbox_norm) == 4 else [0.0, 0.0, 0.0, 0.0]
    width_ratio = round(abs(bbox[2] - bbox[0]), 4)
    height_ratio = round(abs(bbox[3] - bbox[1]), 4)
    area_ratio = round(width_ratio * height_ratio, 4)

    metrics: dict[str, Any] = {
        "width_ratio": width_ratio,
        "height_ratio": height_ratio,
        "area_ratio": area_ratio,
        "estimated_ctr": None,
        "ctr_assessment": "",
    }

    if detection.class_id == 3:
        estimated_ctr = round(width_ratio, 3)
        metrics["estimated_ctr"] = estimated_ctr
        if estimated_ctr > 0.6:
            metrics["ctr_assessment"] = "severe"
        elif estimated_ctr > 0.5:
            metrics["ctr_assessment"] = "moderate"
        else:
            metrics["ctr_assessment"] = "mild"

    return metrics


def _lookup_crop_path(request: RAG1Request, det_id: int) -> str:
    for crop in request.source_context.detection_crops:
        if crop.det_id == det_id:
            return crop.path
    return ""


def _language_templates(language: str) -> dict[str, str]:
    if language == "en":
        return {
            "review_note": "Needs physician review because draft and quantitative evidence do not align.",
            "normal_summary": "No abnormality was detected by the pipeline.",
            "urgent_note": "Urgent clinical review is recommended.",
            "metric_prefix": "Quantitative evidence:",
        }
    return {
        "review_note": "Can bac si xem lai vi draft va bang chung dinh luong khong khop.",
        "normal_summary": "Khong phat hien bat thuong nao boi pipeline.",
        "urgent_note": "Can uu tien danh gia lam sang som.",
        "metric_prefix": "Bang chung dinh luong:",
    }


def _build_metric_sentence(detection: Detection, evidence: QuantitativeEvidence, language: str) -> str:
    t = _language_templates(language)
    if detection.class_id == 3 and evidence.estimated_ctr is not None:
        if language == "en":
            return f"{t['metric_prefix']} estimated CTR {evidence.estimated_ctr:.3f}, consistent with {evidence.severity_final if hasattr(evidence, 'severity_final') else evidence.quantitative_severity} severity."
        return f"{t['metric_prefix']} uoc tinh CTR {evidence.estimated_ctr:.3f}, phu hop muc do {evidence.quantitative_severity}."
    if language == "en":
        return f"{t['metric_prefix']} area_ratio {evidence.area_ratio:.4f}, width_ratio {evidence.width_ratio:.4f}, height_ratio {evidence.height_ratio:.4f}."
    return f"{t['metric_prefix']} area_ratio {evidence.area_ratio:.4f}, width_ratio {evidence.width_ratio:.4f}, height_ratio {evidence.height_ratio:.4f}."


def _quantitative_primary_severity(
    detection: Detection,
    metrics: dict[str, Any],
    patient_context: PatientContext,
) -> tuple[str, str]:
    area_ratio = float(metrics["area_ratio"])

    if detection.class_id == 3:
        ctr = float(metrics.get("estimated_ctr") or 0.0)
        moderate_threshold = 0.5
        severe_threshold = 0.6
        if patient_context.age is not None and patient_context.age < 2:
            moderate_threshold = 0.55
        elif patient_context.sex == "F":
            moderate_threshold = 0.52
        if ctr > severe_threshold:
            return "severe", f"estimated CTR {ctr:.3f} > {severe_threshold:.2f}"
        if ctr > moderate_threshold:
            return "moderate", f"estimated CTR {ctr:.3f} > {moderate_threshold:.2f}"
        return "mild", f"estimated CTR {ctr:.3f} within mild range"

    if detection.class_id == 10:
        if area_ratio > 0.15:
            return "severe", f"pleural effusion area_ratio {area_ratio:.4f} > 0.15"
        if area_ratio >= 0.05:
            return "moderate", f"pleural effusion area_ratio {area_ratio:.4f} in 0.05-0.15"
        return "mild", f"pleural effusion area_ratio {area_ratio:.4f} < 0.05"

    if detection.class_id == 12:
        if area_ratio > 0.10:
            return "severe", f"pneumothorax area_ratio {area_ratio:.4f} > 0.10"
        if area_ratio >= 0.03:
            return "moderate", f"pneumothorax area_ratio {area_ratio:.4f} in 0.03-0.10"
        return "mild", f"pneumothorax area_ratio {area_ratio:.4f} < 0.03"

    if detection.class_id in {1, 4, 6, 7}:
        if area_ratio > 0.10:
            return "severe", f"area_ratio {area_ratio:.4f} > 0.10"
        if area_ratio >= 0.03:
            return "moderate", f"area_ratio {area_ratio:.4f} in 0.03-0.10"
        return "mild", f"area_ratio {area_ratio:.4f} < 0.03"

    return "unknown", "no primary quantitative rule"


class RAG1Engine:
    def __init__(self, config: RAG1Config | None = None) -> None:
        self.config = config or RAG1Config()
        self.config.validate()
        self._retriever = HybridRetriever(self.config)
        self._llm = None if self.config.safe_mode else OpenAI(base_url=self.config.api_base_url, api_key=self.config.github_token)
        self._cache = JsonDiskCache(self.config.cache_dir)
        print(
            f"[RAG1 Engine] Initialized with model={self.config.llm_model} "
            f"safe_mode={self.config.safe_mode} vision={self.config.enable_vision_verification}"
        )

    def _call_llm(self, system: str, user: str) -> str:
        if self.config.safe_mode or self._llm is None:
            return ""

        cache_key = stable_hash("llm", self.config.llm_model, system, user)
        if self.config.enable_response_cache:
            cached = self._cache.get("llm", cache_key)
            if isinstance(cached, dict):
                return str(cached.get("content", ""))

        last_exc: Exception | None = None
        try:
            for attempt in range(self.config.max_api_retries):
                try:
                    response = self._llm.chat.completions.create(
                        model=self.config.llm_model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=self.config.temperature,
                        max_tokens=self.config.max_tokens,
                    )
                    content = response.choices[0].message.content or ""
                    if self.config.enable_response_cache:
                        self._cache.set("llm", cache_key, {"content": content})
                    return content
                except Exception as exc:
                    last_exc = exc
                    if attempt == self.config.max_api_retries - 1 or not is_transient_api_error(exc):
                        break
                    time.sleep(self.config.initial_backoff_seconds * (2 ** attempt))
        except Exception as exc:
            last_exc = exc

        print(f"[RAG1 Engine] LLM unavailable, using fallback draft logic: {last_exc}")
        return ""

    def _kb_timestamp(self) -> str:
        try:
            modified = self.config.kb_pdf_path.stat().st_mtime
        except FileNotFoundError:
            return ""
        return datetime.fromtimestamp(modified, tz=timezone.utc).isoformat().replace("+00:00", "Z")

    def _vision_status_for_crop(self, crop_path: str) -> str:
        if self.config.safe_mode:
            return "safe_mode"
        if not self.config.enable_vision_verification:
            return "disabled"
        if not crop_path:
            return "no_crop"
        return "eligible"

    def _generate_finding(
        self,
        detection: Detection,
        chunks: list[RetrievedChunk],
        language: str,
        patient_context: PatientContext,
        metrics: dict[str, Any],
    ) -> FindingsDraft:
        info = _find_class_info(detection.class_id)
        chunks_text = format_chunks_for_prompt(
            [
                {
                    "section": c.section,
                    "content": c.content,
                    "relevance_score": c.relevance_score,
                }
                for c in chunks
            ]
        )

        ctr_line = ""
        if metrics.get("estimated_ctr") is not None:
            ctr_line = f"- Estimated CTR: {metrics['estimated_ctr']} ({metrics.get('ctr_assessment', 'unknown')})"

        prompt = FINDING_PER_DETECTION_TEMPLATE.format(
            class_name=info["en"],
            class_name_vi=info["vi"],
            icd10=info["icd10"],
            confidence=detection.confidence,
            laterality=detection.laterality,
            bbox_norm=detection.bbox_norm or detection.bbox_xyxy,
            area_ratio=metrics["area_ratio"],
            width_ratio=metrics["width_ratio"],
            height_ratio=metrics["height_ratio"],
            ctr_line=ctr_line,
            patient_age=patient_context.age if patient_context.age is not None else "unknown",
            patient_sex=patient_context.sex,
            clinical_notes=patient_context.clinical_notes or "N/A",
            retrieved_chunks_text=chunks_text,
            language_instruction=get_language_instruction(language),
        )

        raw = self._call_llm(SYSTEM_PROMPT, prompt)
        parsed = _extract_json(raw)
        if not parsed:
            fallback_severity, _ = _quantitative_primary_severity(detection, metrics, patient_context)
            parsed = {
                "impression": (
                    f"Phat hien {info['vi']} tren X-quang nguc."
                    if language == "vi"
                    else f"{info['en']} detected on chest X-ray."
                ),
                "severity_assessment": fallback_severity if fallback_severity != "unknown" else "unknown",
                "severity_confidence": 0.25,
                "differential_diagnosis": [],
                "recommended_next_steps": (
                    "Can doi chieu voi bac si chan doan hinh anh va boi canh lam sang."
                    if language == "vi"
                    else "Correlate with radiologist review and clinical context."
                ),
                "critical_flag": False,
            }

        ddx_list = []
        for ddx_item in parsed.get("differential_diagnosis", []):
            if isinstance(ddx_item, dict):
                ddx_list.append(
                    DifferentialDiagnosis(
                        dx=ddx_item.get("dx", ""),
                        likelihood=ddx_item.get("likelihood", "possible"),
                    )
                )

        severity = parsed.get("severity_assessment", "unknown")
        rule_flags = generate_flags_for_detection(detection, severity)

        return FindingsDraft(
            impression=parsed.get("impression", ""),
            severity_assessment=severity,
            severity_confidence=float(parsed.get("severity_confidence", 0.0) or 0.0),
            differential_diagnosis=ddx_list,
            recommended_next_steps=parsed.get("recommended_next_steps", ""),
            critical_flag=bool(parsed.get("critical_flag", False) or has_critical_flag(rule_flags)),
            flags=rule_flags,
        )

    def _generate_overall(self, results: list[DetectionResult], language: str) -> OverallImpression:
        if not results:
            prompt = NO_DETECTION_IMPRESSION.format(language_instruction=get_language_instruction(language))
        else:
            summary_parts = []
            for result in results:
                summary_parts.append(
                    f"- det_id={result.det_id}: {result.class_name}, laterality={result.laterality}, "
                    f"draft_severity={result.findings_draft.severity_assessment}, final_severity={result.adjudication.severity_final}, "
                    f"critical={result.adjudication.critical_flag_final}"
                )
            prompt = OVERALL_IMPRESSION_TEMPLATE.format(
                detections_summary="\n".join(summary_parts),
                language_instruction=get_language_instruction(language),
            )

        raw = self._call_llm(SYSTEM_PROMPT, prompt)
        parsed = _extract_json(raw)
        if not parsed:
            highest = "normal" if not results else "mild"
            most_critical = None
            requires_urgent = False
            for result in results:
                highest = _severity_max(highest, result.adjudication.severity_final)
                if result.adjudication.critical_flag_final and most_critical is None:
                    most_critical = result.det_id
                    requires_urgent = True
            parsed = {
                "summary": "",
                "most_critical_det_id": most_critical,
                "overall_severity": highest,
                "requires_urgent_action": requires_urgent,
            }
        return OverallImpression(
            summary=parsed.get("summary", ""),
            most_critical_det_id=parsed.get("most_critical_det_id"),
            overall_severity=parsed.get("overall_severity", "unknown"),
            requires_urgent_action=bool(parsed.get("requires_urgent_action", False)),
        )

    def _build_quantitative_evidence(
        self,
        detection: Detection,
        request: RAG1Request,
    ) -> QuantitativeEvidence:
        metrics = _compute_bbox_metrics(detection)
        quantitative_severity, rationale = _quantitative_primary_severity(detection, metrics, request.patient_context)
        crop_path = _lookup_crop_path(request, detection.det_id)
        return QuantitativeEvidence(
            width_ratio=metrics["width_ratio"],
            height_ratio=metrics["height_ratio"],
            area_ratio=metrics["area_ratio"],
            estimated_ctr=metrics.get("estimated_ctr"),
            ctr_assessment=metrics.get("ctr_assessment", ""),
            quantitative_severity=quantitative_severity,
            quantitative_supported=detection.class_id in QUANT_PRIMARY_CLASSES,
            rationale=rationale,
            crop_path=crop_path,
            vision_verification_status=self._vision_status_for_crop(crop_path),
        )

    def _adjudicate_detection(
        self,
        detection: Detection,
        draft: FindingsDraft,
        evidence: QuantitativeEvidence,
        language: str,
    ) -> DetectionAdjudication:
        draft_severity = draft.severity_assessment or "unknown"
        final_severity = draft_severity
        severity_source = "draft"
        needs_review = False
        rationale = []

        if detection.class_id in QUANT_PRIMARY_CLASSES and evidence.quantitative_severity != "unknown":
            final_severity = evidence.quantitative_severity
            severity_source = "quantitative_rule"
            rationale.append(evidence.rationale)
            if draft_severity not in {"unknown", evidence.quantitative_severity}:
                needs_review = True
                rationale.append(f"draft={draft_severity} differs from quantitative rule={evidence.quantitative_severity}")
        elif detection.class_id in SUPPORT_ONLY_CLASSES:
            rationale.append("bbox evidence is supportive only for this class")
            if draft_severity in {"moderate", "severe"} and evidence.quantitative_severity not in {"unknown", draft_severity}:
                final_severity = "unknown"
                severity_source = "support_only_conflict"
                needs_review = True
                rationale.append(
                    f"draft={draft_severity} is not supported by bbox evidence ({evidence.quantitative_severity})"
                )
            elif draft_severity == "mild" and evidence.quantitative_severity in {"moderate", "severe"}:
                final_severity = "unknown"
                severity_source = "support_only_conflict"
                needs_review = True
                rationale.append(
                    f"bbox suggests larger extent ({evidence.quantitative_severity}) but class does not support automatic escalation"
                )
            elif draft_severity in {"mild", "moderate", "severe"} and evidence.quantitative_severity == draft_severity:
                severity_source = "draft_plus_bbox_support"

        flags = generate_flags_for_detection(detection, final_severity)
        critical_flag_final = has_critical_flag(flags)

        impression_final = draft.impression.strip()
        metric_sentence = _build_metric_sentence(detection, evidence, language)
        if metric_sentence and metric_sentence not in impression_final:
            impression_final = f"{impression_final} {metric_sentence}".strip() if impression_final else metric_sentence

        next_steps_final = draft.recommended_next_steps.strip()
        if needs_review:
            review_note = _language_templates(language)["review_note"]
            next_steps_final = f"{next_steps_final} {review_note}".strip() if next_steps_final else review_note

        return DetectionAdjudication(
            severity_final=final_severity,
            severity_source=severity_source,
            needs_review=needs_review,
            rationale="; ".join(rationale).strip(),
            critical_flag_final=critical_flag_final,
            flag_codes=[flag.code for flag in flags],
            impression_final=impression_final,
            next_steps_final=next_steps_final,
        )

    def _vision_candidate_reasons(
        self,
        detection: Detection,
        result: DetectionResult,
    ) -> list[str]:
        reasons: list[str] = []
        if result.adjudication.needs_review:
            reasons.append("needs_review")
        if detection.confidence < self.config.vision_confidence_threshold:
            reasons.append("low_confidence")
        if detection.class_id in SUPPORT_ONLY_CLASSES:
            reasons.append("support_only_class")
        if result.findings_draft.severity_assessment not in {
            "unknown",
            result.adjudication.severity_final,
        }:
            reasons.append("draft_quant_conflict")
        if any(code in IMAGE_LEVEL_ALERT_FLAGS for code in result.adjudication.flag_codes):
            reasons.append("critical_combo_flag")
        return reasons

    def _vision_priority(
        self,
        detection: Detection,
        result: DetectionResult,
        reasons: list[str],
    ) -> tuple[int, float]:
        score = 0
        if "critical_combo_flag" in reasons:
            score += 50
        if "needs_review" in reasons:
            score += 30
        if "draft_quant_conflict" in reasons:
            score += 20
        if "support_only_class" in reasons:
            score += 10
        if "low_confidence" in reasons:
            score += 10
        return score, 1.0 - detection.confidence

    def _call_vision_verification(
        self,
        request: RAG1Request,
        detection: Detection,
        result: DetectionResult,
    ) -> dict[str, Any]:
        evidence = result.quantitative_evidence
        crop_path = evidence.crop_path

        if self.config.safe_mode:
            return {
                "status": "skipped_safe_mode",
                "support": "not_attempted",
                "explanation": "SAFE_MODE is enabled; multimodal verification is intentionally disabled for stable demo behavior.",
                "cache_hit": False,
            }
        if not self.config.enable_vision_verification:
            return {
                "status": "disabled",
                "support": "not_attempted",
                "explanation": "Vision verification is disabled by configuration.",
                "cache_hit": False,
            }
        if not crop_path:
            return {
                "status": "no_crop",
                "support": "not_attempted",
                "explanation": "No crop artifact is available for vision verification.",
                "cache_hit": False,
            }
        if self._llm is None:
            return {
                "status": "provider_unavailable",
                "support": "not_attempted",
                "explanation": "Vision model client is unavailable.",
                "cache_hit": False,
            }

        crop_hash = file_sha256(crop_path)
        cache_key = stable_hash(
            "vision",
            self.config.vision_model,
            crop_hash,
            detection.class_id,
            detection.bbox_norm,
            request.study_id,
        )
        if self.config.enable_response_cache:
            cached = self._cache.get("vision", cache_key)
            if isinstance(cached, dict):
                cached["cache_hit"] = True
                return cached

        image_bytes = Path(crop_path).read_bytes()
        data_url = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
        prompt = (
            "Assess whether the supplied crop is visually compatible with the proposed chest X-ray finding. "
            "Be conservative. Do not restate unsupported severity claims. Return JSON only with keys "
            "`finding_supported`, `suggested_review`, and `explanation`. "
            f"Finding class: {detection.class_name}. "
            f"Laterality: {detection.laterality}. "
            f"Confidence: {detection.confidence:.3f}. "
            f"Draft severity: {result.findings_draft.severity_assessment}. "
            f"Quantitative severity: {result.quantitative_evidence.quantitative_severity}. "
            f"Candidate reasons: {', '.join(result.quantitative_evidence.vision_candidate_reasons) or 'none'}."
        )

        last_exc: Exception | None = None
        for attempt in range(self.config.max_api_retries):
            try:
                response = self._llm.chat.completions.create(
                    model=self.config.vision_model,
                    messages=[
                        {"role": "system", "content": "You are a cautious radiology vision verifier. Return compact JSON only."},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ],
                        },
                    ],
                    temperature=0.0,
                    max_tokens=400,
                )
                content = response.choices[0].message.content or ""
                parsed = _extract_json(content)
                verdict = {
                    "status": "verified",
                    "support": str(parsed.get("finding_supported", "uncertain") or "uncertain"),
                    "explanation": str(parsed.get("explanation", "") or "").strip(),
                    "suggested_review": bool(parsed.get("suggested_review", False)),
                    "cache_hit": False,
                }
                if self.config.enable_response_cache:
                    self._cache.set("vision", cache_key, verdict)
                return verdict
            except Exception as exc:
                last_exc = exc
                if attempt == self.config.max_api_retries - 1 or not is_transient_api_error(exc):
                    break
                time.sleep(self.config.initial_backoff_seconds * (2 ** attempt))

        status = "failed_rate_limit" if last_exc and is_rate_limit_error(last_exc) else "provider_error"
        return {
            "status": status,
            "support": "not_attempted",
            "explanation": f"Vision verification failed: {last_exc}" if last_exc else "Vision verification failed.",
            "cache_hit": False,
        }

    def _apply_vision_result(
        self,
        result: DetectionResult,
        vision_result: dict[str, Any],
        language: str,
    ) -> None:
        evidence = result.quantitative_evidence
        evidence.vision_verification_status = str(vision_result.get("status", evidence.vision_verification_status))
        evidence.vision_support = str(vision_result.get("support", evidence.vision_support))
        evidence.vision_explanation = str(vision_result.get("explanation", "") or "")
        evidence.vision_cache_hit = bool(vision_result.get("cache_hit", False))

        explanation = evidence.vision_explanation.strip()
        if not explanation:
            return

        if evidence.vision_support == "conflict":
            result.adjudication.needs_review = True
            result.adjudication.rationale = "; ".join(
                part for part in [result.adjudication.rationale, f"vision conflict: {explanation}"] if part
            )
        elif evidence.vision_support == "supported":
            result.adjudication.rationale = "; ".join(
                part for part in [result.adjudication.rationale, f"vision support: {explanation}"] if part
            )
        elif vision_result.get("suggested_review"):
            result.adjudication.needs_review = True
            result.adjudication.rationale = "; ".join(
                part for part in [result.adjudication.rationale, f"vision review suggested: {explanation}"] if part
            )

        if result.adjudication.needs_review:
            review_note = _language_templates(language)["review_note"]
            if review_note not in result.adjudication.next_steps_final:
                result.adjudication.next_steps_final = (
                    f"{result.adjudication.next_steps_final} {review_note}".strip()
                    if result.adjudication.next_steps_final
                    else review_note
                )

    def _run_selective_vision(
        self,
        request: RAG1Request,
        detection_results: list[DetectionResult],
        language: str,
    ) -> None:
        scored_candidates: list[tuple[tuple[int, float], DetectionResult, Detection, list[str]]] = []
        detection_map = {d.det_id: d for d in request.detections}

        for result in detection_results:
            detection = detection_map[result.det_id]
            reasons = self._vision_candidate_reasons(detection, result)
            result.quantitative_evidence.vision_candidate = bool(reasons)
            result.quantitative_evidence.vision_candidate_reasons = reasons

            if not reasons and self.config.vision_only_on_review_cases:
                result.quantitative_evidence.vision_verification_status = (
                    "skipped_not_needed" if self.config.enable_vision_verification and not self.config.safe_mode else self._vision_status_for_crop(result.quantitative_evidence.crop_path)
                )
                continue

            if reasons:
                scored_candidates.append((self._vision_priority(detection, result, reasons), result, detection, reasons))

        if not scored_candidates:
            return

        scored_candidates.sort(key=lambda item: item[0], reverse=True)
        budget = max(0, self.config.vision_max_attempts_per_image)

        for index, (_, result, detection, _) in enumerate(scored_candidates):
            if index >= budget:
                result.quantitative_evidence.vision_verification_status = "skipped_budget"
                result.quantitative_evidence.vision_explanation = "Another detection was prioritized for the single-image vision budget."
                continue
            vision_result = self._call_vision_verification(request, detection, result)
            self._apply_vision_result(result, vision_result, language)

    def _apply_image_level_flags(
        self,
        request: RAG1Request,
        detection_results: list[DetectionResult],
    ) -> list[Flag]:
        hits = generate_image_flag_hits(request.detections)
        det_map = {result.det_id: result for result in detection_results}
        class_to_det_ids: dict[int, list[int]] = {}
        for detection in request.detections:
            class_to_det_ids.setdefault(detection.class_id, []).append(detection.det_id)

        overall_flags: list[Flag] = []
        for hit in hits:
            flag = Flag(code=hit["code"], level=hit["level"], message=hit["message"])
            overall_flags.append(flag)
            required = set(hit["required_class_ids"])
            target_det_ids: set[int] = set()
            if hit["code"] == "FLAG_MULTILESION":
                target_det_ids = {result.det_id for result in detection_results}
            else:
                for class_id in required:
                    target_det_ids.update(class_to_det_ids.get(class_id, []))

            for det_id in target_det_ids:
                result = det_map.get(det_id)
                if result is None:
                    continue
                if flag.code not in result.adjudication.flag_codes:
                    result.adjudication.flag_codes.append(flag.code)
                if flag.level == "critical":
                    result.adjudication.critical_flag_final = True

        return overall_flags

    def _build_final_for_fe(
        self,
        request: RAG1Request,
        detection_results: list[DetectionResult],
        overall: OverallImpression,
        image_flags: list[Flag],
        language: str,
    ) -> FinalForFE:
        findings: list[FinalFindingForFE] = []
        overall_flag_codes = [flag.code for flag in image_flags]
        most_critical_det_id = None
        overall_severity = "normal" if not detection_results else "mild"
        requires_urgent_action = bool(overall.requires_urgent_action)

        detection_map = {d.det_id: d for d in request.detections}

        for result in detection_results:
            detection = detection_map[result.det_id]
            findings.append(
                FinalFindingForFE(
                    det_id=result.det_id,
                    class_id=result.class_id,
                    class_name=result.class_name,
                    laterality=result.laterality,
                    confidence=detection.confidence,
                    bbox_xyxy=detection.bbox_xyxy,
                    bbox_norm=detection.bbox_norm,
                    severity_final=result.adjudication.severity_final,
                    severity_source=result.adjudication.severity_source,
                    needs_review=result.adjudication.needs_review,
                    impression_final=result.adjudication.impression_final,
                    next_steps_final=result.adjudication.next_steps_final,
                    critical_flag_final=result.adjudication.critical_flag_final,
                    flag_codes=result.adjudication.flag_codes,
                )
            )

            overall_severity = _severity_max(overall_severity, result.adjudication.severity_final)
            if result.adjudication.critical_flag_final and most_critical_det_id is None:
                most_critical_det_id = result.det_id
            if result.adjudication.critical_flag_final:
                requires_urgent_action = True
            if result.adjudication.flag_codes:
                overall_flag_codes.extend(result.adjudication.flag_codes)

        if most_critical_det_id is None:
            most_critical_det_id = overall.most_critical_det_id

        summary_final = self._build_summary_final(findings, overall, language, requires_urgent_action)

        return FinalForFE(
            study_id=request.study_id,
            image_id=request.image_id,
            findings=findings,
            summary_final=summary_final,
            overall_severity_final=overall_severity,
            requires_urgent_action_final=requires_urgent_action,
            most_critical_det_id_final=most_critical_det_id,
            flag_codes_final=sorted(set(overall_flag_codes)),
        )

    def _build_summary_final(
        self,
        findings: list[FinalFindingForFE],
        overall: OverallImpression,
        language: str,
        requires_urgent_action: bool,
    ) -> str:
        t = _language_templates(language)
        if not findings:
            return overall.summary or t["normal_summary"]

        summary_parts = []
        for finding in findings[:3]:
            if language == "en":
                summary_parts.append(
                    f"{finding.class_name} ({finding.laterality}) classified as {finding.severity_final}"
                )
            else:
                summary_parts.append(
                    f"{finding.class_name} ({finding.laterality}) duoc xep muc do {finding.severity_final}"
                )

        if len(findings) > 3:
            if language == "en":
                summary_parts.append(f"plus {len(findings) - 3} additional findings")
            else:
                summary_parts.append(f"kem {len(findings) - 3} phat hien khac")

        if any(f.needs_review for f in findings):
            summary_parts.append(t["review_note"])
        if requires_urgent_action:
            summary_parts.append(t["urgent_note"])

        base = ". ".join(part.strip().rstrip(".") for part in summary_parts if part.strip()).strip()
        return f"{base}.".strip()

    def process(self, request: RAG1Request) -> RAG1Response:
        start_time = time.time()
        language = request.language or self.config.default_language
        detection_results: list[DetectionResult] = []

        for detection in request.detections:
            print(
                f"  [det-{detection.det_id:03d}] {detection.class_name} "
                f"conf={detection.confidence:.2f} lat={detection.laterality}"
            )
            chunks = self._retriever.retrieve(
                class_id=detection.class_id,
                class_name=detection.class_name,
                laterality=detection.laterality,
                severity_hint=detection.severity_hint,
                top_k=request.top_k,
            )
            print(f"    Retrieved {len(chunks)} chunks")

            evidence = self._build_quantitative_evidence(detection, request)
            draft = self._generate_finding(
                detection=detection,
                chunks=chunks,
                language=language,
                patient_context=request.patient_context,
                metrics={
                    "area_ratio": evidence.area_ratio,
                    "width_ratio": evidence.width_ratio,
                    "height_ratio": evidence.height_ratio,
                    "estimated_ctr": evidence.estimated_ctr,
                    "ctr_assessment": evidence.ctr_assessment,
                },
            )
            adjudication = self._adjudicate_detection(
                detection=detection,
                draft=draft,
                evidence=evidence,
                language=language,
            )
            print(
                f"    Draft={draft.severity_assessment} Final={adjudication.severity_final} "
                f"review={adjudication.needs_review}"
            )

            detection_results.append(
                DetectionResult(
                    det_id=detection.det_id,
                    class_id=detection.class_id,
                    class_name=detection.class_name,
                    laterality=detection.laterality,
                    retrieved_chunks=chunks,
                    findings_draft=draft,
                    quantitative_evidence=evidence,
                    adjudication=adjudication,
                )
            )

        image_flags = self._apply_image_level_flags(request, detection_results)
        self._run_selective_vision(request, detection_results, language)

        print("  [overall] Generating overall impression...")
        overall = self._generate_overall(detection_results, language)
        final_for_fe = self._build_final_for_fe(request, detection_results, overall, image_flags, language)

        elapsed_ms = int((time.time() - start_time) * 1000)

        return RAG1Response(
            query_id=request.query_id,
            study_id=request.study_id,
            image_id=request.image_id,
            results_per_detection=detection_results,
            overall_impression=overall,
            final_for_fe=final_for_fe,
            metadata=RAG1Metadata(
                rag_version="2.1",
                kb_version="RAG1_KB_v2.0",
                model_used=self.config.llm_model,
                kb_timestamp=self._kb_timestamp(),
                processing_time_ms=elapsed_ms,
                safe_mode=self.config.safe_mode,
                response_cache_enabled=self.config.enable_response_cache,
                api_retry_policy=f"max_retries={self.config.max_api_retries}, initial_backoff={self.config.initial_backoff_seconds}s",
                vision_verification_mode=(
                    "safe_mode"
                    if self.config.safe_mode
                    else "disabled"
                    if not self.config.enable_vision_verification
                    else "selective_single_crop"
                ),
            ),
        )
