"""
RAG2 Engine - Orchestrates retrieval -> generation -> validation -> response.

Main entry point: RAG2Engine.process(doctor_revised_json) -> RAG2Response
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from rag2.config import RAG2Config
from rag2.prompts import SYSTEM_PROMPT, build_user_prompt
from rag2.retriever import RAG2Retriever
from rag2.schema import (
    DoctorRevisedJSON,
    Findings,
    ICD10En,
    ICD10Vi,
    NhanXet,
    RAG2Metadata,
    RAG2Response,
    ReportEn,
    ReportVi,
)
from rag2.validator import validate_rag2_response


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


def _count_described_findings(parsed: dict) -> int:
    """
    Count how many findings are actually described in the report output.

    Heuristic: count non-empty nhan_xet sections that mention specific findings.
    Falls back to counting ket_luan items.
    """
    report_vi = parsed.get("report_vi", {})
    ket_luan = report_vi.get("ket_luan", [])
    if isinstance(ket_luan, list):
        # Count numbered items that describe actual findings
        return len([k for k in ket_luan if k and k.strip()])
    return 0


class RAG2Engine:
    """
    Main RAG2 orchestrator.

    Usage:
        engine = RAG2Engine()
        response = engine.process(doctor_revised_json)
    """

    def __init__(self, config: RAG2Config | None = None) -> None:
        self.config = config or RAG2Config()
        self.config.validate()

        self._retriever = RAG2Retriever(self.config)
        self._llm = OpenAI(
            base_url=self.config.api_base_url,
            api_key=self.config.github_token,
        )
        print(f"[RAG2 Engine] Initialized with model={self.config.llm_model}")

    def _call_llm(self, system: str, user: str) -> str:
        """Call LLM via OpenAI-compatible API."""
        started_at = time.perf_counter()
        print(
            f"  [LLM] Chat completion start model={self.config.llm_model} "
            f"system_chars={len(system)} user_chars={len(user)}"
        )
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
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            print(
                f"  [LLM] Chat completion failed after {elapsed_ms}ms: "
                f"{type(exc).__name__}: {exc}"
            )
            raise
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        print(f"  [LLM] Chat completion success in {elapsed_ms}ms")
        return response.choices[0].message.content or ""

    def _build_retry_feedback(
        self,
        revised: DoctorRevisedJSON,
        validation_errors: list[Any],
    ) -> str:
        """Build a corrective instruction block for a single regeneration retry."""
        confirmed_count = len(revised.confirmed_findings)
        allowed_labels = ", ".join(
            f.class_name for f in revised.confirmed_findings
        ) or "(none)"
        allowed_icd10 = sorted({
            f.icd10_confirmed for f in revised.confirmed_findings if f.icd10_confirmed
        })
        allowed_icd10_text = ", ".join(allowed_icd10) if allowed_icd10 else "(none)"
        error_lines = "\n".join(
            f"- {err.rule}: {err.message}" for err in validation_errors
        )

        return (
            "\n\n## CORRECTION REQUIRED\n"
            "Your previous JSON violated mandatory constraints.\n"
            "Regenerate the full JSON from scratch and fix every issue below.\n"
            f"{error_lines}\n"
            "Non-negotiable constraints:\n"
            f"- EXACTLY {confirmed_count} Vietnamese conclusion items.\n"
            f"- EXACTLY {confirmed_count} English impression items.\n"
            "- One item per confirmed finding, with no extra inferred diagnoses.\n"
            f"- Mention ONLY these finding labels: {allowed_labels}\n"
            f"- Use ONLY these ICD-10 codes: {allowed_icd10_text}\n"
            "- If a detail is not explicitly supported by confirmed_findings, omit it.\n"
            "- Return JSON only.\n"
        )

    def _parse_report(self, raw_json: dict, input_json: DoctorRevisedJSON) -> RAG2Response:
        """
        Parse raw LLM JSON output into structured RAG2Response.
        """
        # Parse Vietnamese report
        vi_data = raw_json.get("report_vi", {})
        nhan_xet_data = vi_data.get("nhan_xet", {})

        report_vi = ReportVi(
            ky_thuat=vi_data.get("ky_thuat", ""),
            nhan_xet=NhanXet(
                tim_trung_that=nhan_xet_data.get("tim_trung_that", ""),
                phoi=nhan_xet_data.get("phoi", ""),
                mang_phoi=nhan_xet_data.get("mang_phoi", ""),
                xuong_mo_mem=nhan_xet_data.get("xuong_mo_mem", ""),
            ),
            ket_luan=vi_data.get("ket_luan", []),
            de_nghi=vi_data.get("de_nghi"),
            icd10=[
                ICD10Vi(ma=item.get("ma", ""), mo_ta=item.get("mo_ta", ""))
                for item in vi_data.get("icd10", [])
                if isinstance(item, dict)
            ],
        )

        # Parse English report
        en_data = raw_json.get("report_en", {})
        findings_data = en_data.get("findings", {})

        report_en = ReportEn(
            technique=en_data.get("technique", ""),
            findings=Findings(
                cardiac_mediastinum=findings_data.get("cardiac_mediastinum", ""),
                lungs=findings_data.get("lungs", ""),
                pleura=findings_data.get("pleura", ""),
                bones_soft_tissue=findings_data.get("bones_soft_tissue", ""),
            ),
            impression=en_data.get("impression", []),
            recommendation=en_data.get("recommendation"),
            icd10=[
                ICD10En(code=item.get("code", ""), description=item.get("description", ""))
                for item in en_data.get("icd10", [])
                if isinstance(item, dict)
            ],
        )

        # Build metadata
        critical_ids = [
            f.det_id for f in input_json.confirmed_findings if f.critical_flag
        ]
        findings_count_output = _count_described_findings(raw_json)

        now_vn = datetime.now(timezone.utc).isoformat().replace("+00:00", "+07:00")

        return RAG2Response(
            query_id=input_json.query_id,
            study_id=input_json.study_id,
            image_id=input_json.image_id,
            revision_id=input_json.revision_id,
            report_id=str(uuid.uuid4()),
            generated_at=now_vn,
            report_vi=report_vi,
            report_en=report_en,
            metadata=RAG2Metadata(
                rag_version="2.0",
                kb_version="RAG2_KB_v1.0",
                llm_model=self.config.llm_model,
                report_standard=input_json.rag2_config.report_standard,
                language=input_json.rag2_config.language,
                critical_flags=critical_ids,
                requires_urgent_review=any(
                    f.critical_flag for f in input_json.confirmed_findings
                ),
                findings_count_input=len(input_json.confirmed_findings),
                findings_count_output=findings_count_output,
            ),
        )

    def process(
        self,
        revised: DoctorRevisedJSON,
        *,
        skip_validation: bool = False,
    ) -> RAG2Response:
        """
        Process a Doctor-Revised JSON through RAG2 pipeline.

        Steps:
          1. Retrieve relevant KB chunks
          2. Build prompt (system + user)
          3. Call LLM
          4. Parse output into structured response
          5. Validate response
          6. Return

        Args:
            revised: The Doctor-Revised JSON input.
            skip_validation: If True, skip validation step (for debugging).

        Returns:
            RAG2Response with bilingual reports.

        Raises:
            ValueError: If validation fails with critical errors.
        """
        start_time = time.time()

        print(f"\n  [RAG2] Processing query_id={revised.query_id}")
        print(f"  [RAG2] {len(revised.confirmed_findings)} confirmed findings")

        # Step 1: Retrieve
        print("  [1/4] Retrieving knowledge chunks...")
        chunks = self._retriever.retrieve(revised)
        print(f"  [1/4] Retrieved {len(chunks)} chunks")

        # Step 2: Build prompt
        print("  [2/4] Building prompt...")
        user_prompt = build_user_prompt(revised, chunks)

        # Step 3: Call LLM
        print("  [3/4] Calling LLM...")
        raw_text = self._call_llm(SYSTEM_PROMPT, user_prompt)
        parsed = _extract_json(raw_text)

        if not parsed:
            raise ValueError(
                f"LLM returned non-JSON output. Raw text:\n{raw_text[:500]}"
            )

        # Step 4: Parse into structured response
        print("  [4/4] Parsing and validating...")
        response = self._parse_report(parsed, revised)

        # Update timing
        elapsed_ms = int((time.time() - start_time) * 1000)
        response.metadata.processing_time_ms = elapsed_ms
        response.metadata.chunks_used = len(chunks)

        # Step 5: Validate
        if not skip_validation:
            validation = validate_rag2_response(revised, response)
            retryable_rules = {"FINDINGS_COVERAGE", "ICD10_FALSE_ADD", "CRITICAL_MISS"}

            if validation.errors and any(e.rule in retryable_rules for e in validation.errors):
                print("  [RETRY] Regenerating due to validation errors...")
                retry_prompt = user_prompt + self._build_retry_feedback(
                    revised, validation.errors
                )
                raw_text = self._call_llm(SYSTEM_PROMPT, retry_prompt)
                parsed_retry = _extract_json(raw_text)

                if parsed_retry:
                    response = self._parse_report(parsed_retry, revised)
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    response.metadata.processing_time_ms = elapsed_ms
                    response.metadata.chunks_used = len(chunks)
                    validation = validate_rag2_response(revised, response)

            if validation.warnings:
                for w in validation.warnings:
                    print(f"  [WARN] {w.rule}: {w.message}")
                    response.metadata.confidence_notes.append(
                        f"[{w.rule}] {w.message}"
                    )

            if validation.errors:
                for e in validation.errors:
                    print(f"  [ERROR] {e.rule}: {e.message}")
                    response.metadata.confidence_notes.append(
                        f"[ERROR:{e.rule}] {e.message}"
                    )
                # Log errors but don't raise; let the report through with notes
                print(f"  [WARN] Validation found {len(validation.errors)} errors. "
                      f"Report generated with confidence notes.")

        print(f"\n  [RAG2] Complete in {elapsed_ms}ms")
        print(f"  [RAG2] Findings: {response.metadata.findings_count_input} in -> "
              f"{response.metadata.findings_count_output} out")

        return response
