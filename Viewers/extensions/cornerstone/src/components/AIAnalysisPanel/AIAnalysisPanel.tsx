import React, { useState, useEffect, useCallback } from 'react';
import AIAnnotationStore, { AIDetection, AI_LABEL_OPTIONS } from '../../AIAnnotationStore';

const CONFIDENCE_COLOR = (conf: number) => {
  if (conf < 0.25) return 'text-red-400';
  if (conf < 0.5) return 'text-yellow-400';
  return 'text-cyan-300';
};

function LabelSelect({
  detection,
  onUpdate,
}: {
  detection: AIDetection;
  onUpdate: (id: string, label: string) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        className="rounded border border-blue-600 bg-blue-900/30 px-2 py-0.5 text-xs text-blue-300 hover:bg-blue-800/50"
        onClick={() => setOpen(v => !v)}
      >
        Sửa nhãn ▾
      </button>
      {open && (
        <div className="absolute left-0 z-50 mt-1 max-h-48 overflow-auto rounded border border-neutral-600 bg-neutral-900 shadow-lg">
          {AI_LABEL_OPTIONS.map(opt => (
            <div
              key={opt}
              className={`cursor-pointer px-3 py-1.5 text-xs hover:bg-neutral-700 ${
                opt === detection.label ? 'text-blue-400' : 'text-white'
              }`}
              onClick={() => {
                onUpdate(detection.id, opt);
                setOpen(false);
              }}
            >
              {opt}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AIAnalysisPanel({ commandsManager, servicesManager }) {
  const [detections, setDetections] = useState<AIDetection[]>([]);
  const [isAnalysisRun, setIsAnalysisRun] = useState(false);
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    const refresh = () => {
      setDetections([...AIAnnotationStore.getDetections()]);
      setIsAnalysisRun(AIAnnotationStore.isAnalysisRun());
    };

    refresh();
    const unsubscribe = AIAnnotationStore.subscribe(refresh);
    return () => {
      unsubscribe();
    };
  }, []);

  const handleRunAnalysis = useCallback(async () => {
    setIsRunning(true);
    try {
      await commandsManager.runCommand('runAIAnalysis');
    } finally {
      setIsRunning(false);
    }
  }, [commandsManager]);

  const handleToggleVisibility = useCallback(
    (detectionId: string) => {
      commandsManager.runCommand('toggleAIAnnotationVisibility', { detectionId });
    },
    [commandsManager]
  );

  const handleRemove = useCallback(
    (detectionId: string) => {
      commandsManager.runCommand('removeAIAnnotation', { detectionId });
    },
    [commandsManager]
  );

  const handleUpdateLabel = useCallback(
    (detectionId: string, newLabel: string) => {
      commandsManager.runCommand('updateAIAnnotationLabel', { detectionId, newLabel });
    },
    [commandsManager]
  );

  const handleClearAll = useCallback(() => {
    commandsManager.runCommand('clearAllAIAnnotations');
  }, [commandsManager]);

  const handleConfirm = useCallback(() => {
    commandsManager.runCommand('confirmAIResults');
  }, [commandsManager]);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-neutral-950 text-white">
      {/* Header */}
      <div className="border-b border-neutral-700 p-3">
        <div className="mb-2 flex items-center gap-2">
          <span className="text-sm font-semibold text-blue-400">🤖 Phân tích AI</span>
        </div>

        <button
          className={`w-full rounded px-3 py-2 text-sm font-medium transition-colors ${
            isRunning
              ? 'cursor-not-allowed bg-blue-800/50 text-blue-300'
              : 'bg-blue-600 text-white hover:bg-blue-500'
          }`}
          onClick={handleRunAnalysis}
          disabled={isRunning}
        >
          {isRunning ? '⏳ Đang phân tích...' : '▶ Phân tích bằng AI'}
        </button>
      </div>

      {/* Result list */}
      <div className="flex-1 overflow-y-auto">
        {!isAnalysisRun && (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center text-neutral-500">
            <span className="text-2xl">🔍</span>
            <p className="text-sm">Nhấn "Phân tích bằng AI" để bắt đầu</p>
          </div>
        )}

        {isAnalysisRun && detections.length === 0 && (
          <div className="p-4 text-center text-sm text-neutral-400">
            Không còn kết quả nào.
          </div>
        )}

        {detections.map((det, idx) => (
          <div
            key={det.id}
            className={`border-b border-neutral-800 p-3 transition-opacity ${
              det.visible ? 'opacity-100' : 'opacity-40'
            }`}
          >
            {/* Row header */}
            <div className="mb-2 flex items-start justify-between gap-2">
              <div className="flex-1">
                <span className="text-sm font-medium text-white">
                  #{idx + 1} {det.label}
                </span>
                <div className={`mt-0.5 text-xs ${CONFIDENCE_COLOR(det.confidence)}`}>
                  Độ tin cậy: {Math.round(det.confidence * 100)}%
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex gap-1">
                <button
                  title={det.visible ? 'Ẩn' : 'Hiện'}
                  className="rounded border border-neutral-600 px-2 py-1 text-xs hover:bg-neutral-700"
                  onClick={() => handleToggleVisibility(det.id)}
                >
                  {det.visible ? '👁' : '🚫'}
                </button>
                <button
                  title="Xóa"
                  className="rounded border border-red-800 px-2 py-1 text-xs text-red-400 hover:bg-red-900/30"
                  onClick={() => handleRemove(det.id)}
                >
                  ✕
                </button>
              </div>
            </div>

            {/* Confidence bar */}
            <div className="mb-2 h-1.5 w-full overflow-hidden rounded-full bg-neutral-700">
              <div
                className={`h-full rounded-full transition-all ${
                  det.confidence < 0.25
                    ? 'bg-red-500'
                    : det.confidence < 0.5
                      ? 'bg-yellow-500'
                      : 'bg-cyan-500'
                }`}
                style={{ width: `${det.confidence * 100}%` }}
              />
            </div>

            {/* Bounding box info */}
            <div className="mb-2 rounded bg-neutral-900 p-1.5 font-mono text-xs text-neutral-400">
              x:{Math.round(det.x * 100)}% y:{Math.round(det.y * 100)}% w:
              {Math.round(det.width * 100)}% h:{Math.round(det.height * 100)}%
            </div>

            {/* Change label */}
            <LabelSelect detection={det} onUpdate={handleUpdateLabel} />
          </div>
        ))}
      </div>

      {/* Footer actions */}
      {isAnalysisRun && detections.length > 0 && (
        <div className="border-t border-neutral-700 p-3">
          <button
            className="mb-2 w-full rounded bg-green-700 px-3 py-2 text-sm font-medium text-white hover:bg-green-600"
            onClick={handleConfirm}
          >
            ✅ Xác nhận kết quả ({detections.length})
          </button>
          <button
            className="w-full rounded border border-neutral-600 px-3 py-1.5 text-xs text-neutral-400 hover:bg-neutral-800"
            onClick={handleClearAll}
          >
            🗑 Xóa tất cả
          </button>
        </div>
      )}
    </div>
  );
}

export default AIAnalysisPanel;
