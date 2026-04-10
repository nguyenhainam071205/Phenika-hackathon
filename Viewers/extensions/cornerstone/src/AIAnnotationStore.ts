/**
 * AIAnnotationStore - Stores AI detection results and tracks annotation UIDs added to Cornerstone.
 * Acts as a lightweight in-memory state manager for AI analysis in OHIF.
 */

// ── RAG1 Response Types ──────────────────────────────────────────────────────

export interface RAG1DifferentialDiagnosis {
  dx: string;
  likelihood: string;
}

export interface RAG1FindingsDraft {
  impression: string;
  severity_assessment: string;
  severity_confidence: number;
  differential_diagnosis: RAG1DifferentialDiagnosis[];
  recommended_next_steps: string;
  critical_flag: boolean;
  flags: string[];
}

export interface RAG1RetrievedChunk {
  chunk_id: string;
  source: string;
  section: string;
  relevance_score: number;
  content: string;
  icd10: string;
  references: string[];
}

export interface RAG1DetectionResult {
  det_id: number;
  class_id: number;
  class_name: string;
  laterality: string;
  bbox_norm: number[];
  retrieved_chunks: RAG1RetrievedChunk[];
  findings_draft: RAG1FindingsDraft;
}

export interface RAG1OverallImpression {
  summary: string;
  overall_severity: string;
  requires_urgent_action: boolean;
}

export interface RAG1Metadata {
  rag_version: string;
  kb_version: string;
  model_used: string;
  kb_timestamp: string;
  processing_time_ms: number;
}

export interface RAG1FinalFindingForFE {
  det_id: number;
  class_id: number;
  class_name: string;
  laterality: string;
  confidence: number;
  bbox_xyxy: number[];
  bbox_norm: number[];
  severity_final: string;
  severity_source: string;
  needs_review: boolean;
  impression_final: string;
  next_steps_final: string;
  critical_flag_final: boolean;
  flag_codes: string[];
}

export interface RAG1FinalForFE {
  study_id: string;
  image_id: string;
  findings: RAG1FinalFindingForFE[];
  summary_final: string;
  overall_severity_final: string;
  requires_urgent_action_final: boolean;
  most_critical_det_id_final: number | null;
  flag_codes_final: string[];
}

export interface RAG1Response {
  query_id: string;
  study_id: string;
  image_id: string;
  results_per_detection: RAG1DetectionResult[];
  overall_impression: RAG1OverallImpression;
  metadata: RAG1Metadata;
  final_for_fe?: RAG1FinalForFE;
}

// ── RAG2 Response Types ──────────────────────────────────────────────────────

export interface RAG2ICD10En {
  code: string;
  description: string;
}

export interface RAG2Findings {
  cardiac_mediastinum: string;
  lungs: string;
  pleura: string;
  bones_soft_tissue: string;
}

export interface RAG2ReportEn {
  technique: string;
  findings: RAG2Findings;
  impression: string[];
  recommendation: string | null;
  icd10: RAG2ICD10En[];
}

export interface RAG2Metadata {
  rag_version: string;
  kb_version: string;
  llm_model: string;
  report_standard: string;
  language: string;
  chunks_used: number;
  processing_time_ms: number;
  critical_flags: number[];
  requires_urgent_review: boolean;
  confidence_notes: string[];
  findings_count_input: number;
  findings_count_output: number;
}

export interface RAG2Response {
  query_id: string;
  study_id: string;
  image_id: string;
  revision_id: string;
  report_id: string;
  generated_at: string;
  report_en: RAG2ReportEn;
  metadata: RAG2Metadata;
}

/** Full API response from /rag1/run-orthanc */
export interface RAG1APIResponse {
  job_id: string;
  source_name: string;
  dicom_path: string;
  artifacts: {
    input_json: string;
    input_png: string;
    output_json: string;
  };
  detector: {
    model_name: string;
    model_path: string;
    threshold_policy: string;
  };
  result: RAG1Response;
}

// ── AI Detection (for bounding boxes on viewport) ────────────────────────────

export interface AIDetection {
  id: string;
  label: string;
  confidence: number;
  /** Normalized image coordinates (0-1) */
  x: number;
  y: number;
  width: number;
  height: number;
  /** Cornerstone annotationUID after rendering */
  annotationUID?: string;
  visible: boolean;
  /** World-space corner points [topLeft, topRight, bottomRight, bottomLeft] stored after canvasToWorld conversion */
  worldPoints?: number[][];
  /** Array of RAG1DetectionResult.det_id corresponding to this grouped detection */
  ragDetIds?: number[];
}

export const MOCK_AI_RESULTS: Omit<AIDetection, 'visible'>[] = [
  { id: 'ai-1', label: 'Nodule / Mass', confidence: 0.92, x: 0.18, y: 0.28, width: 0.14, height: 0.12 },
  { id: 'ai-2', label: 'Nodule / Mass', confidence: 0.78, x: 0.52, y: 0.42, width: 0.22, height: 0.19 },
  { id: 'ai-3', label: 'Infiltration', confidence: 0.65, x: 0.08, y: 0.58, width: 0.28, height: 0.16 },
  { id: 'ai-4', label: 'Nodule / Mass', confidence: 0.55, x: 0.72, y: 0.35, width: 0.10, height: 0.09 },
];

export const AI_LABEL_OPTIONS = [
  'Aortic enlargement',
  'Atelectasis',
  'Calcification',
  'Cardiomegaly',
  'Consolidation',
  'ILD',
  'Infiltration',
  'Lung Opacity',
  'Nodule / Mass',
  'Other lesion',
  'Pleural effusion',
  'Pleural thickening',
  'Pneumothorax',
  'Pulmonary fibrosis',
];

class AIAnnotationStoreClass {
  private _detections: AIDetection[] = [];
  private _studyInstanceUID: string | null = null;
  private _analysisRun = false;
  private _ragResult: RAG1Response | null = null;
  private _ragAPIResponse: RAG1APIResponse | null = null;
  private _rag2Report: RAG2Response | null = null;
  private _listeners: Set<() => void> = new Set();

  subscribe(listener: () => void) {
    this._listeners.add(listener);
    return () => this._listeners.delete(listener);
  }

  private _notify() {
    this._listeners.forEach(l => l());
  }

  isAnalysisRun() {
    return this._analysisRun;
  }

  getStudyInstanceUID() {
    return this._studyInstanceUID;
  }

  getDetections(): AIDetection[] {
    return this._detections;
  }

  setDetections(studyInstanceUID: string, detections: AIDetection[]) {
    this._studyInstanceUID = studyInstanceUID;
    this._detections = detections;
    this._analysisRun = true;
    this._notify();
  }

  // ── RAG1 result storage ─────────────────────────────────────────────────

  setRAGResult(apiResponse: RAG1APIResponse) {
    this._ragAPIResponse = apiResponse;
    this._ragResult = apiResponse.result;
    this._notify();
  }

  getRAGResult(): RAG1Response | null {
    return this._ragResult;
  }

  getRAGAPIResponse(): RAG1APIResponse | null {
    return this._ragAPIResponse;
  }

  // ── RAG2 result storage ─────────────────────────────────────────────────

  setRAG2Report(report: RAG2Response) {
    this._rag2Report = report;
    this._notify();
  }

  getRAG2Report(): RAG2Response | null {
    return this._rag2Report;
  }

  // ── Detection manipulation ──────────────────────────────────────────────

  updateDetectionAnnotationUID(detectionId: string, annotationUID: string) {
    const det = this._detections.find(d => d.id === detectionId);
    if (det) {
      det.annotationUID = annotationUID;
      this._notify();
    }
  }

  updateDetectionLabel(detectionId: string, newLabel: string) {
    const det = this._detections.find(d => d.id === detectionId);
    if (det) {
      det.label = newLabel;
      this._notify();
    }
  }

  toggleDetectionVisibility(detectionId: string) {
    const det = this._detections.find(d => d.id === detectionId);
    if (det) {
      det.visible = !det.visible;
      this._notify();
    }
  }

  updateDetectionBounds(
    detectionId: string,
    bounds: { x: number; y: number; width: number; height: number; worldPoints?: number[][] }
  ) {
    const det = this._detections.find(d => d.id === detectionId);
    if (det) {
      det.x = bounds.x;
      det.y = bounds.y;
      det.width = bounds.width;
      det.height = bounds.height;
      if (bounds.worldPoints) {
        det.worldPoints = bounds.worldPoints;
      }
      this._notify();
    }
  }

  removeDetection(detectionId: string) {
    this._detections = this._detections.filter(d => d.id !== detectionId);
    this._notify();
  }

  clear() {
    this._detections = [];
    this._studyInstanceUID = null;
    this._analysisRun = false;
    this._ragResult = null;
    this._ragAPIResponse = null;
    this._rag2Report = null;
    this._notify();
  }
}

const AIAnnotationStore = new AIAnnotationStoreClass();
export default AIAnnotationStore;
