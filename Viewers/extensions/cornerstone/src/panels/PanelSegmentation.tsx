import React, { useCallback, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
// @ts-ignore
import html2pdf from 'html2pdf.js';
import {
  IconPresentationProvider,
  Popover,
  PopoverAnchor,
  PopoverContent,
  SegmentationTable,
  ToolSettings,
} from '@ohif/ui-next';
import { useActiveViewportSegmentationRepresentations } from '../hooks/useActiveViewportSegmentationRepresentations';
import { useActiveToolOptions, useSystem } from '@ohif/core/src';
import { SegmentationRepresentations } from '@cornerstonejs/tools/enums';
import { Toolbar, useUIStateStore } from '@ohif/extension-default';
import SegmentationUtilityButton from '../components/SegmentationUtilityButton';
import { useSelectedSegmentationsForViewportStore } from '../stores';
import {
  hasExportableLabelMapData,
  hasExportableContourData,
} from '../utils/segmentationExportUtils';
import AIAnnotationStore, { AI_LABEL_OPTIONS, AIDetection, RAG1Response, RAG2Response } from '../AIAnnotationStore';

type PanelSegmentationProps = {
  children?: React.ReactNode;

  // The representation types for this segmentation panel. Undefined means all types.
  // The first element is the primary type. Additional elements are secondary types.
  segmentationRepresentationTypes?: SegmentationRepresentations[];
} & withAppTypes;

export default function PanelSegmentation({
  children,
  segmentationRepresentationTypes,
}: PanelSegmentationProps) {
  const { commandsManager, servicesManager } = useSystem();
  const {
    customizationService,
    displaySetService,
    viewportGridService,
    toolbarService,
    segmentationService,
  } = servicesManager.services;
  const { activeViewportId } = viewportGridService.getState();

  const utilitiesSectionMap = {
    [SegmentationRepresentations.Labelmap]: toolbarService.sections.labelMapSegmentationUtilities,
    [SegmentationRepresentations.Contour]: toolbarService.sections.contourSegmentationUtilities,
  };

  const selectedSegmentationsForViewportMap = useSelectedSegmentationsForViewportStore(
    store => store.selectedSegmentationsForViewport[activeViewportId]
  );

  const selectedSegmentationIdForType = segmentationRepresentationTypes
    ? segmentationRepresentationTypes.reduce(
        (selectedSegmentation, type) =>
          selectedSegmentation ||
          (selectedSegmentationsForViewportMap?.has(type)
            ? selectedSegmentationsForViewportMap?.get(type)
            : undefined),
        undefined
      )
    : segmentationService?.getActiveSegmentation(activeViewportId)?.segmentationId;

  const buttonSection = segmentationRepresentationTypes?.[0]
    ? utilitiesSectionMap[segmentationRepresentationTypes[0]]
    : undefined;

  const { activeToolOptions: activeUtilityOptions } = useActiveToolOptions({
    buttonSectionId: buttonSection,
  });

  const { segmentationsWithRepresentations, disabled } =
    useActiveViewportSegmentationRepresentations();
  const [aiDetections, setAiDetections] = useState<AIDetection[]>([]);
  const [ragResult, setRagResult] = useState<RAG1Response | null>(null);
  const [rag2Report, setRag2Report] = useState<RAG2Response | null>(null);
  const [showAiControls, setShowAiControls] = useState(false);
  const [showReportModal, setShowReportModal] = useState(false);
  const [isGeneratingTarget, setIsGeneratingTarget] = useState(false);
  const [isExportingPDF, setIsExportingPDF] = useState(false);
  const [expandedJsonDetId, setExpandedJsonDetId] = useState<string | null>(null);
  const [editableDetections, setEditableDetections] = useState<any[]>([]);
  const [activeDetId, setActiveDetId] = useState<number | null>(null);
  const [patientInfo, setPatientInfo] = useState({
    id: 'Unknown',
    name: 'Unknown',
    sex: 'Unknown',
    birthDate: 'Unknown',
    description: 'Unknown',
  });

  useEffect(() => {
    if (showReportModal) {
      try {
        const activeDisplaySets = displaySetService.activeDisplaySets || [];
        if (activeDisplaySets.length > 0) {
          const ds = activeDisplaySets[0];
          const instance = ds.instances ? ds.instances[0] : ds;
          
          let pName = instance.PatientName || ds.PatientName || 'Unknown';
          if (typeof pName === 'object' && pName.Alphabetic) pName = pName.Alphabetic;
          
          setPatientInfo({
            id: instance.PatientID || ds.PatientID || 'Unknown',
            name: String(pName),
            sex: instance.PatientSex || ds.PatientSex || 'Unknown',
            birthDate: instance.PatientBirthDate || ds.PatientBirthDate || 'Unknown',
            description: instance.StudyDescription || ds.StudyDescription || 'No description',
          });
        }
      } catch (e) {
        console.warn('Could not fetch patient info:', e);
      }
    }
  }, [showReportModal, displaySetService]);

  const setUIState = useUIStateStore(store => store.setUIState);

  // useEffect for handling clicks on any of the non-active viewports.
  // The ViewportGrid stops the propagation of pointer/mouse events
  // for non-active viewports so the Popover below
  // is not closed when clicking on any of the non-active viewports.
  useEffect(() => {
    setUIState('activeSegmentationUtility', null);
    toolbarService.refreshToolbarState({ viewportId: activeViewportId });
  }, [activeViewportId, setUIState, toolbarService]);

  useEffect(() => {
    const refresh = () => {
      setAiDetections([...AIAnnotationStore.getDetections()]);
      setRagResult(AIAnnotationStore.getRAGResult());
      setRag2Report(AIAnnotationStore.getRAG2Report());
    };
    refresh();
    const unsubscribe = AIAnnotationStore.subscribe(refresh);
    return () => {
      unsubscribe();
    };
  }, []);

  // The callback for handling clicks outside of the Popover and, the SegmentationUtilityButton
  // that triggered it to open. Clicks outside those components must close the Popover.
  // The Popover is made visible whenever the options associated with the
  // activeSegmentationUtility exist. Thus clearing the activeSegmentationUtility
  // clears the associated options and will keep the Popover closed.
  const handlePopoverOpenChange = useCallback(
    (open: boolean) => {
      if (!open) {
        setUIState('activeSegmentationUtility', null);
        toolbarService.refreshToolbarState({ viewportId: activeViewportId });
      }
    },
    [activeViewportId, setUIState, toolbarService]
  );

  // Extract customization options
  const segmentationTableMode = customizationService.getCustomization(
    'panelSegmentation.tableMode'
  ) as unknown as string;
  const onSegmentationAdd = customizationService.getCustomization(
    'panelSegmentation.onSegmentationAdd'
  );
  const disableEditing = customizationService.getCustomization('panelSegmentation.disableEditing');
  const showAddSegment = customizationService.getCustomization('panelSegmentation.showAddSegment');
  const CustomDropdownMenuContent = customizationService.getCustomization(
    'panelSegmentation.customDropdownMenuContent'
  ) as unknown as React.FC<any>;

  const CustomSegmentStatisticsHeader = customizationService.getCustomization(
    'panelSegmentation.customSegmentStatisticsHeader'
  ) as unknown as React.FC<any>;

  // Create handlers object for all command runs
  const handlers = {
    onSegmentationClick: (segmentationId: string) => {
      commandsManager.run('setActiveSegmentation', { segmentationId });
    },
    onSegmentAdd: segmentationId => {
      commandsManager.run('addSegment', { segmentationId });
      commandsManager.run('setActiveSegmentation', { segmentationId });
    },
    onSegmentClick: (segmentationId, segmentIndex) => {
      commandsManager.run('setActiveSegmentAndCenter', { segmentationId, segmentIndex });
    },
    onSegmentEdit: (segmentationId, segmentIndex) => {
      commandsManager.run('editSegmentLabel', { segmentationId, segmentIndex });
    },
    onSegmentationEdit: segmentationId => {
      commandsManager.run('editSegmentationLabel', { segmentationId });
    },
    onSegmentColorClick: (segmentationId, segmentIndex) => {
      commandsManager.run('editSegmentColor', { segmentationId, segmentIndex });
    },
    onSegmentDelete: (segmentationId, segmentIndex) => {
      commandsManager.run('deleteSegment', { segmentationId, segmentIndex });
    },
    onSegmentCopy:
      segmentationRepresentationTypes?.[0] === SegmentationRepresentations.Contour
        ? (segmentationId, segmentIndex) => {
            commandsManager.run('copyContourSegment', {
              sourceSegmentInfo: { segmentationId, segmentIndex },
            });
          }
        : undefined,
    onToggleSegmentVisibility: (segmentationId, segmentIndex, type) => {
      commandsManager.run('toggleSegmentVisibility', { segmentationId, segmentIndex, type });
    },
    onToggleSegmentLock: (segmentationId, segmentIndex) => {
      commandsManager.run('toggleSegmentLock', { segmentationId, segmentIndex });
    },
    onToggleSegmentationRepresentationVisibility: (segmentationId, type) => {
      commandsManager.run('toggleSegmentationVisibility', { segmentationId, type });
    },
    onSegmentationDownload: segmentationId => {
      commandsManager.run('downloadSegmentation', { segmentationId });
    },
    setStyle: (segmentationId, type, key, value) => {
      commandsManager.run('setSegmentationStyle', { segmentationId, type, key, value });
    },
    toggleRenderInactiveSegmentations: () => {
      commandsManager.run('toggleRenderInactiveSegmentations');
    },
    onSegmentationRemoveFromViewport: segmentationId => {
      commandsManager.run('removeSegmentationFromViewport', { segmentationId });
    },
    onSegmentationDelete: segmentationId => {
      commandsManager.run('deleteSegmentation', { segmentationId });
    },
    setFillAlpha: ({ type }, value) => {
      commandsManager.run('activateSelectedSegmentationOfType', {
        segmentationRepresentationType: type,
      });
      commandsManager.run('setFillAlpha', { type, value });
    },
    setOutlineWidth: ({ type }, value) => {
      commandsManager.run('activateSelectedSegmentationOfType', {
        segmentationRepresentationType: type,
      });
      commandsManager.run('setOutlineWidth', { type, value });
    },
    setRenderFill: ({ type }, value) => {
      commandsManager.run('activateSelectedSegmentationOfType', {
        segmentationRepresentationType: type,
      });
      commandsManager.run('setRenderFill', { type, value });
    },
    setRenderFillInactive: ({ type }, value) => {
      commandsManager.run('setRenderFillInactive', { type, value });
    },
    setRenderOutline: ({ type }, value) => {
      commandsManager.run('activateSelectedSegmentationOfType', {
        segmentationRepresentationType: type,
      });
      commandsManager.run('setRenderOutline', { type, value });
    },
    setRenderOutlineInactive: ({ type }, value) => {
      commandsManager.run('setRenderOutlineInactive', { type, value });
    },
    setFillAlphaInactive: ({ type }: { type?: string }, value) => {
      commandsManager.run('setFillAlphaInactive', { type, value });
    },
    getRenderInactiveSegmentations: () => {
      return commandsManager.run('getRenderInactiveSegmentations');
    },
  };

  // Generate export options
  // Map each segmentation to an export option for it.
  // A segmentation is exportable if it has any labelmap or contour data.
  const exportOptions = segmentationsWithRepresentations.map(({ segmentation }) => {
    const { representationData, segmentationId } = segmentation;
    const { Labelmap, Contour } = representationData;

    if (!Labelmap && !Contour) {
      return { segmentationId, isExportable: true };
    }

    if (
      !hasExportableLabelMapData(Labelmap, displaySetService) &&
      !hasExportableContourData(Contour)
    ) {
      return { segmentationId, isExportable: false };
    }

    return {
      segmentationId,
      isExportable: true,
    };
  });

  // Common props for SegmentationTable
  const tableProps = {
    disabled,
    data: segmentationsWithRepresentations,
    mode: segmentationTableMode,
    title: `${segmentationRepresentationTypes?.[0] ? `${segmentationRepresentationTypes[0]} ` : ''}Segmentations`,
    exportOptions,
    disableEditing,
    onSegmentationAdd,
    showAddSegment,
    renderInactiveSegmentations: handlers.getRenderInactiveSegmentations(),
    segmentationRepresentationTypes,
    selectedSegmentationIdForType,
    ...handlers,
  };

  const renderUtilitiesToolbar = () => {
    if (!buttonSection) {
      return null;
    }

    return (
      <IconPresentationProvider
        size="large"
        IconContainer={SegmentationUtilityButton}
      >
        <div className="flex flex-wrap gap-[3px] bg-transparent pb-[2px] pl-[8px] pt-[6px]">
          <Toolbar buttonSection={buttonSection} />
        </div>
      </IconPresentationProvider>
    );
  };

  const renderSegments = () => {
    return (
      <SegmentationTable.Segments>
        <SegmentationTable.SegmentStatistics.Header>
          <CustomSegmentStatisticsHeader />
        </SegmentationTable.SegmentStatistics.Header>
        <SegmentationTable.SegmentStatistics.Body />
      </SegmentationTable.Segments>
    );
  };

  // Render content based on mode
  const renderModeContent = () => {
    if (tableProps.mode === 'collapsed') {
      return (
        <SegmentationTable.Collapsed>
          {renderUtilitiesToolbar()}
          <SegmentationTable.Collapsed.Header>
            <SegmentationTable.Collapsed.DropdownMenu>
              <CustomDropdownMenuContent />
            </SegmentationTable.Collapsed.DropdownMenu>
            <SegmentationTable.Collapsed.Selector />
            <SegmentationTable.Collapsed.Info />
          </SegmentationTable.Collapsed.Header>
          <SegmentationTable.Collapsed.Content>
            <SegmentationTable.AddSegmentRow />
            {renderSegments()}
          </SegmentationTable.Collapsed.Content>
        </SegmentationTable.Collapsed>
      );
    }

    return (
      <>
        <SegmentationTable.Expanded>
          {renderUtilitiesToolbar()}
          <SegmentationTable.Expanded.Header>
            <SegmentationTable.Expanded.DropdownMenu>
              <CustomDropdownMenuContent />
            </SegmentationTable.Expanded.DropdownMenu>
            <SegmentationTable.Expanded.Label />
            <SegmentationTable.Expanded.Info />
          </SegmentationTable.Expanded.Header>

          <SegmentationTable.Expanded.Content>
            <SegmentationTable.AddSegmentRow />
            {renderSegments()}
          </SegmentationTable.Expanded.Content>
        </SegmentationTable.Expanded>
      </>
    );
  };

  return (
    <div className="relative h-full">
      <Popover
        open={!!activeUtilityOptions}
        onOpenChange={handlePopoverOpenChange}
      >
        <PopoverAnchor>
          {/* @ts-expect-error Types for SegmentationTable in OHIF might be missing or mismatched */}
          <SegmentationTable {...tableProps}>
            {children}
            <SegmentationTable.Config />
            <SegmentationTable.AddSegmentationRow />
            {renderModeContent()}
          </SegmentationTable>
        </PopoverAnchor>
        {activeUtilityOptions && (
          <PopoverContent
            side="left"
            align="start"
            className="w-auto"
          >
            <ToolSettings options={activeUtilityOptions} />
          </PopoverContent>
        )}
      </Popover>

      {showAiControls && createPortal(
        <div 
          className="fixed bottom-16 right-3 z-[99999] max-h-[45%] w-[300px] overflow-auto rounded-md border border-neutral-700 p-2 text-white shadow-xl"
          style={{ backgroundColor: '#000000' }}
        >
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-semibold">AI Box Management ({aiDetections.length})</span>
            <button
              type="button"
              className="rounded border border-neutral-700 px-2 py-0.5 text-xs hover:bg-neutral-800"
              onClick={() => setShowAiControls(false)}
            >
              Close
            </button>
          </div>

          {aiDetections.length === 0 && (
            <div className="py-2 text-xs text-neutral-400">No AI results yet.</div>
          )}

          {aiDetections.map((det, index) => (
            <div
              key={det.id}
              className="mb-2 rounded border border-neutral-800 p-2"
              style={{ backgroundColor: '#1a1a1a' }}
            >
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="font-medium">#{index + 1} {det.label}</span>
                <span className={det.confidence < 0.25 ? 'text-red-400' : det.confidence < 0.5 ? 'text-yellow-400' : 'text-cyan-300'}>
                  {Math.round(det.confidence * 100)}%
                </span>
              </div>

              <div className="mb-2 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="rounded border border-neutral-700 px-2 py-1 text-[10px] hover:bg-neutral-800"
                  onClick={() =>
                    commandsManager.runCommand('toggleAIAnnotationVisibility', {
                      detectionId: det.id,
                    })
                  }
                >
                  {det.visible ? 'Hide' : 'Show'}
                </button>

                <button
                  type="button"
                  className="rounded border border-red-800 px-2 py-1 text-[10px] text-red-300 hover:bg-red-900/30"
                  onClick={() =>
                    commandsManager.runCommand('removeAIAnnotation', {
                      detectionId: det.id,
                    })
                  }
                >
                  Delete
                </button>

                <button
                  type="button"
                  className="rounded border border-blue-800 px-2 py-1 text-[10px] text-blue-300 hover:bg-blue-900/30"
                  onClick={() => {
                    setExpandedJsonDetId(det.id);
                    const result = AIAnnotationStore.getRAGResult();
                    if (result && result.results_per_detection) {
                      setEditableDetections(JSON.parse(JSON.stringify(result.results_per_detection))); // Load all
                      if (det.ragDetIds && det.ragDetIds.length > 0) {
                        setActiveDetId(det.ragDetIds[0]);
                      } else {
                        setActiveDetId(result.results_per_detection[0]?.det_id ?? null);
                      }
                    } else {
                      setEditableDetections([]);
                      setActiveDetId(null);
                    }
                  }}
                >
                  Edit Info
                </button>
              </div>

              <select
                className="mb-2 w-full rounded border border-neutral-700 px-2 py-1 text-[10px]"
                style={{ backgroundColor: '#222222', color: '#ffffff' }}
                value={det.label}
                onChange={event =>
                  commandsManager.runCommand('updateAIAnnotationLabel', {
                    detectionId: det.id,
                    newLabel: event.target.value,
                  })
                }
              >
                {AI_LABEL_OPTIONS.map(label => (
                  <option
                    key={label}
                    value={label}
                    style={{ backgroundColor: '#222222', color: '#ffffff' }}
                  >
                    {label}
                  </option>
                ))}
              </select>


            </div>
          ))}

          {aiDetections.length > 0 && (
            <button
              type="button"
              className="w-full rounded bg-red-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-600"
              onClick={() => commandsManager.runCommand('clearAllAIAnnotations')}
            >
              Delete All
            </button>
          )}
        </div>,
        document.body
      )}

      <button
        type="button"
        className="absolute bottom-14 right-3 z-50 rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white shadow-md hover:bg-blue-500"
        onClick={() => commandsManager.runCommand('runAIAnalysis')}
      >
        Analyze with AI
      </button>

      <button
        type="button"
        className="absolute bottom-14 right-[160px] z-50 rounded-md bg-neutral-800 px-3 py-2 text-sm font-medium text-white shadow-md hover:bg-neutral-700"
        onClick={() => setShowAiControls(v => !v)}
      >
        Manage AI
      </button>

      <button
        type="button"
        className="absolute bottom-3 right-3 z-50 rounded-md bg-green-700 px-3 py-2 text-sm font-medium text-white shadow-md hover:bg-green-600 w-[260px]"
        disabled={isGeneratingTarget}
        onClick={async () => {
          setShowReportModal(true);
          
          const currentRag1 = AIAnnotationStore.getRAGResult();
          if (!currentRag1) {
            console.warn('No RAG1 result to export');
            return;
          }

          setIsGeneratingTarget(true);
          try {
            const response = await fetch('/rag2/demo-from-rag1', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                ...currentRag1,
                _language: 'en'
              }),
            });

            if (!response.ok) {
              throw new Error(`RAG2 API failed: ${response.statusText}`);
            }

            const data = await response.json();
            AIAnnotationStore.setRAG2Report(data.result);
          } catch (error) {
            console.error('Error generating RAG2 report:', error);
            alert('Failed to generate AI report. Please ensure RAG2 backend is running.');
          } finally {
            setIsGeneratingTarget(false);
          }
        }}
      >
        {isGeneratingTarget ? 'Generating Report...' : 'Export Medical Record (AI)'}
      </button>

      {/* REPORT MODAL SIMULATION */}
      {showReportModal && createPortal(
        <div className="fixed inset-0 z-[999999] flex items-center justify-center bg-black/60 p-4">
          <div id="medical-report-container" className="flex w-full max-w-2xl flex-col rounded-lg border shadow-2xl bg-white text-gray-900 border-gray-300">
            <div className="flex items-center justify-between border-b border-gray-200 p-4 bg-gray-50 rounded-t-lg">
              <h2 className="text-lg font-bold text-blue-800">MEDICAL IMAGING RECORD (AI SUGGESTED)</h2>
              <button 
                type="button" 
                className="text-gray-500 hover:text-gray-800 font-bold text-xl"
                onClick={() => setShowReportModal(false)}
                data-html2canvas-ignore="true"
              >
                ✕
              </button>
            </div>
            <div className="p-6 text-sm text-gray-800">
               {isGeneratingTarget ? (
                 <div className="flex flex-col items-center justify-center py-10">
                   <div className="mb-4 h-8 w-8 animate-spin rounded-full border-b-2 border-t-2 border-blue-600"></div>
                   <div className="animate-pulse text-blue-700 font-medium">
                     [LLM + RAG] Synthesizing medical history and analyzing JSON...
                   </div>
                 </div>
               ) : (
                 <div className="whitespace-pre-wrap leading-relaxed text-base">
                    <div className="mb-5 text-gray-800 text-sm border-2 border-gray-200 rounded p-4 bg-gray-50">
                      <p className="font-bold text-blue-800 border-b pb-2 mb-3 border-gray-200 uppercase tracking-wide">PATIENT INFORMATION</p>
                      <div className="grid grid-cols-2 gap-3">
                        <p><span className="text-gray-500">Patient ID:</span> <span className="font-bold text-gray-900">{patientInfo.id}</span></p>
                        <p><span className="text-gray-500">Full Name:</span> <span className="font-bold text-gray-900">{patientInfo.name}</span></p>
                        <p><span className="text-gray-500">Gender:</span> <span className="font-bold text-gray-900">{patientInfo.sex}</span></p>
                        <p><span className="text-gray-500">Study Description:</span> <span className="font-bold text-gray-900 line-clamp-1" title={patientInfo.description}>{patientInfo.description}</span></p>
                      </div>
                    </div>

                     {rag2Report ? (
                      <div className="max-h-[60vh] overflow-y-auto pr-2 custom-scrollbar">
                        {/* Technique */}
                        <div className="mb-4">
                          <p className="font-bold text-blue-800 border-b pb-1 mb-2 uppercase text-xs tracking-wider">TECHNIQUE</p>
                          <p className="text-gray-700 text-sm italic">{rag2Report.report_en.technique}</p>
                        </div>

                        {/* Findings */}
                        <div className="mb-4">
                          <p className="font-bold text-blue-800 border-b pb-1 mb-2 uppercase text-xs tracking-wider">FINDINGS</p>
                          <div className="space-y-3">
                            <div>
                              <span className="font-semibold text-gray-900 text-sm">Cardiac & Mediastinum: </span>
                              <span className="text-gray-700 text-sm">{rag2Report.report_en.findings.cardiac_mediastinum}</span>
                            </div>
                            <div>
                              <span className="font-semibold text-gray-900 text-sm">Lungs: </span>
                              <span className="text-gray-700 text-sm">{rag2Report.report_en.findings.lungs}</span>
                            </div>
                            <div>
                              <span className="font-semibold text-gray-900 text-sm">Pleura: </span>
                              <span className="text-gray-700 text-sm">{rag2Report.report_en.findings.pleura}</span>
                            </div>
                            <div>
                              <span className="font-semibold text-gray-900 text-sm">Bones & Soft Tissue: </span>
                              <span className="text-gray-700 text-sm">{rag2Report.report_en.findings.bones_soft_tissue}</span>
                            </div>
                          </div>
                        </div>

                        {/* Impression */}
                        <div className="mb-4 rounded border-2 border-blue-100 bg-blue-50/50 p-3">
                          <p className="font-bold text-blue-800 border-b pb-1 mb-2 border-blue-200 uppercase text-xs tracking-wider">IMPRESSION</p>
                          <ul className="list-disc list-inside space-y-1">
                            {rag2Report.report_en.impression.map((imp, i) => (
                              <li key={i} className="text-gray-800 text-sm font-medium">{imp}</li>
                            ))}
                          </ul>
                        </div>

                        {/* Recommendation */}
                        {rag2Report.report_en.recommendation && (
                          <div className="mb-4">
                            <p className="font-bold text-blue-800 border-b pb-1 mb-2 uppercase text-xs tracking-wider">RECOMMENDATION</p>
                            <p className="text-gray-700 text-sm">{rag2Report.report_en.recommendation}</p>
                          </div>
                        )}

                        {/* ICD-10 */}
                        <div className="mb-4">
                          <p className="font-bold text-blue-800 border-b pb-1 mb-2 uppercase text-xs tracking-wider">ICD-10 CODES</p>
                          <div className="flex flex-wrap gap-2">
                            {rag2Report.report_en.icd10.map((code, i) => (
                              <span key={i} className="inline-block rounded bg-gray-200 px-2 py-1 text-xs font-mono text-gray-800 border border-gray-300">
                                <strong>{code.code}</strong>: {code.description}
                              </span>
                            ))}
                          </div>
                        </div>

                        {/* Metadata */}
                        <div className="mt-6 border-t border-gray-200 pt-3 text-[10px] text-gray-400 flex justify-between">
                          <p>Model: {rag2Report.metadata.llm_model}</p>
                          <p>Processing: {rag2Report.metadata.processing_time_ms}ms</p>
                        </div>
                      </div>
                    ) : ragResult ? (
                      <div className="max-h-[50vh] overflow-y-auto pr-2 custom-scrollbar">
                        {/* Fallback to RAG1 if RAG2 is not yet generated */}
                        <div className="mb-4 rounded border border-yellow-200 bg-yellow-50 p-3 text-yellow-800 text-sm">
                          <p className="font-bold mb-1">Notice:</p>
                          <p>Currently showing RAG1 draft results. Click the "Export" button to generate the final professional RAG2 report.</p>
                        </div>
                        
                        <div className="mb-5 rounded border-2 border-blue-200 bg-blue-50 p-4">
                          <p className="font-bold text-blue-800 border-b pb-2 mb-3 border-blue-200 uppercase tracking-wide">DRAFT IMPRESSION</p>
                          <p className="text-gray-700 mb-2">{ragResult.overall_impression.summary}</p>
                          <div className="flex gap-4 mt-2">
                            <span className={`inline-block rounded px-3 py-1 text-xs font-bold uppercase ${
                              ragResult.overall_impression.overall_severity === 'severe' ? 'bg-red-100 text-red-800' :
                              ragResult.overall_impression.overall_severity === 'moderate' ? 'bg-yellow-100 text-yellow-800' :
                              'bg-green-100 text-green-800'
                            }`}>
                              Severity: {ragResult.overall_impression.overall_severity}
                            </span>
                          </div>
                        </div>

                        <div className="space-y-4">
                          {ragResult.results_per_detection.map((det, idx) => (
                            <div key={det.det_id} className="rounded border border-gray-200 p-3 bg-gray-50/50">
                              <p className="font-bold text-gray-900 mb-1">#{idx + 1} {det.class_name}</p>
                              <p className="text-gray-700 text-sm">{det.findings_draft.impression}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      /* Fallback when no RAG result available */
                      <>
                        <div className="mb-4 rounded border border-yellow-200 bg-yellow-50 p-3 text-yellow-800 text-sm">
                          No AI analysis results available. Please click "Analyze with AI" first to run the YOLO + RAG + LLM pipeline.
                        </div>
                        <p className="mb-2"><strong className="text-gray-900">Detected Annotations:</strong></p>
                        <div className="bg-gray-50 border border-gray-200 p-3 rounded text-gray-700 font-mono text-xs">
                          {aiDetections.map((det, idx) => (
                            <div key={det.id} className="mb-1">
                              👉 [{idx+1}] Coordinates ({Math.round(det.x*100)}, {Math.round(det.y*100)}): <span className="font-bold text-gray-900">{det.label}</span>
                            </div>
                          ))}
                          {aiDetections.length === 0 && <span className="text-gray-500 italic">No lesions marked.</span>}
                        </div>
                      </>
                    )}
                  </div>
               )}
            </div>
            <div className="flex justify-end gap-3 border-t border-gray-200 p-4 bg-gray-50 rounded-b-lg" data-html2canvas-ignore="true">
              <button 
                type="button" 
                className="rounded border border-gray-300 bg-white px-5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 transition-colors" 
                onClick={() => setShowReportModal(false)}
                disabled={isExportingPDF}
              >
                Close
              </button>
              <button 
                type="button" 
                className={`rounded px-5 py-2 text-sm font-medium text-white shadow min-w-[150px] transition-colors flex items-center justify-center ${isExportingPDF ? 'bg-blue-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700 shadow-blue-600/30'}`}
                disabled={isExportingPDF}
                onClick={() => {
                   const element = document.getElementById('medical-report-container');
                   if (!element) return;
                   
                   setIsExportingPDF(true);

                   const opt = {
                     margin:       10,
                     filename:     `MedicalRecord_${patientInfo.id || 'Unknown'}.pdf`,
                     image:        { type: 'jpeg', quality: 0.98 },
                     html2canvas:  { scale: 2 },
                     jsPDF:        { unit: 'mm', format: 'a4', orientation: 'portrait' }
                   };

                   html2pdf().set(opt).from(element).save().then(() => {
                      setIsExportingPDF(false);
                   }).catch((err: any) => {
                      setIsExportingPDF(false);
                      console.error("PDF generation failed", err);
                      alert("An error occurred while exporting PDF!");
                   });
                }}
              >
                {isExportingPDF ? (
                  <>
                    <div className="h-4 w-4 animate-spin rounded-full border-b-2 border-t-2 border-white mr-2"></div>
                    Exporting PDF...
                  </>
                ) : (
                  'Save / Print Medical Record'
                )}
              </button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* Edit Disease Information Modal / Unified Dashboard */}
      {expandedJsonDetId && createPortal(
        <div className="fixed inset-0 z-[1000000] flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="flex w-full h-[90vh] max-w-7xl flex-col rounded-xl border border-neutral-700 bg-neutral-900 shadow-2xl text-white overflow-hidden">
            
            {/* Zone A: Urgency Dashboard */}
            <div className="flex shrink-0 items-center justify-between border-b border-neutral-700 p-4" style={{ backgroundColor: '#253550' }}>
              <div className="flex items-center gap-4">
                <h2 className="text-lg font-bold text-white uppercase tracking-wide">Bảng điều khiển Nguy cấp (Urgency Dashboard)</h2>
                {ragResult?.overall_impression && (
                  <>
                    <span className="text-sm px-3 py-1 font-semibold rounded bg-blue-900/40 border border-blue-400/30 text-blue-100">
                      Mức độ: {ragResult.overall_impression.overall_severity}
                    </span>
                    {ragResult.overall_impression.requires_urgent_action && (
                      <span className="text-sm font-bold px-3 py-1 rounded bg-red-600 text-white shadow shadow-red-600/50">
                        Cần xử trí khẩn
                      </span>
                    )}
                  </>
                )}
              </div>
              <button 
                type="button" 
                className="text-neutral-400 hover:text-white font-bold text-2xl leading-none transition-colors"
                onClick={() => setExpandedJsonDetId(null)}
              >
                ✕
              </button>
            </div>
            
            <div className="flex flex-1 overflow-hidden">
              {/* Zone B: AI Findings List (Sidebar) */}
              <div className="w-1/3 min-w-[250px] max-w-[350px] border-r border-neutral-700 bg-neutral-900/50 overflow-y-auto custom-scrollbar p-3 space-y-2">
                <h3 className="text-xs font-bold text-neutral-400 uppercase tracking-wide mb-3 pl-1 border-b border-neutral-800 pb-2">Danh sách Tổn thương AI (Findings)</h3>
                {editableDetections.map((det) => (
                  <div 
                    key={det.det_id} 
                    onClick={() => setActiveDetId(det.det_id)}
                    className={`p-3 rounded-lg border cursor-pointer transition-colors ${
                      activeDetId === det.det_id 
                        ? 'bg-blue-900/30 border-blue-500 shadow-inner' 
                        : 'bg-neutral-800 border-neutral-700 hover:border-neutral-500 hover:bg-neutral-800/80'
                    }`}
                  >
                    <div className="font-bold text-sm text-blue-100">{det.class_name}</div>
                    <div className="text-xs mt-1 flex justify-between items-center text-neutral-400">
                      <span>{det.laterality}</span>
                      {det.findings_draft?.severity_assessment && (
                        <span className={`uppercase text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          det.findings_draft.severity_assessment === 'severe' ? 'bg-red-900/50 text-red-300' :
                          det.findings_draft.severity_assessment === 'moderate' ? 'bg-orange-900/50 text-orange-300' :
                          'bg-neutral-700 text-neutral-300'
                        }`}>
                          {det.findings_draft.severity_assessment}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
                {editableDetections.length === 0 && (
                  <div className="text-neutral-500 text-sm p-2 text-center italic">Không có tổn thương nào</div>
                )}
              </div>

              {/* Main Content Pane */}
              <div className="flex-1 flex flex-col overflow-hidden bg-black/40">
                {activeDetId != null && editableDetections.some(d => d.det_id === activeDetId) ? (() => {
                  const idx = editableDetections.findIndex(d => d.det_id === activeDetId);
                  const det = editableDetections[idx];
                  
                  return (
                    <>
                      {/* Zone C: Evidence-Based Viewer */}
                      <div className="shrink-0 p-4 border-b border-neutral-800/80 bg-neutral-900/80">
                        <h3 className="text-xs font-bold text-blue-400 mb-3 uppercase tracking-wide flex justify-between">
                          <span>Bằng chứng Định lượng & Hình ảnh (Evidence)</span>
                          <span className="text-neutral-500 font-mono">ID: {det.det_id}</span>
                        </h3>
                        <div className="flex flex-col md:flex-row gap-4">
                          <div className="h-28 w-28 bg-black border border-neutral-700 flex items-center justify-center shrink-0 rounded overflow-hidden shadow-inner">
                            {det.quantitative_evidence && det.quantitative_evidence.crop_path ? (
                              <img 
                                src={`/${det.quantitative_evidence.crop_path}`} 
                                alt="Crop Viewer" 
                                className="w-full h-full object-cover opacity-80 hover:opacity-100 transition-opacity" 
                              />
                            ) : (
                              <span className="text-xs text-neutral-600 font-mono text-center px-2">No Crop Image</span>
                            )}
                          </div>
                          <div className="flex-1 text-sm bg-black/50 p-3 rounded border border-neutral-700 flex flex-col justify-center">
                            {det.quantitative_evidence ? (
                              <>
                                <div className="grid grid-cols-2 gap-2 text-xs font-mono text-neutral-300 mb-2 border-b border-neutral-800 pb-2">
                                  <div><strong className="text-neutral-500">Kích thước:</strong> {det.quantitative_evidence.width_ratio ? `${(det.quantitative_evidence.width_ratio*100).toFixed(1)}%` : 'N/A'} x {det.quantitative_evidence.height_ratio ? `${(det.quantitative_evidence.height_ratio*100).toFixed(1)}%` : 'N/A'}</div>
                                  <div><strong className="text-neutral-500">CTR (Tim):</strong> <span className="text-blue-300 font-bold">{det.quantitative_evidence.estimated_ctr || 'Không áp dụng'}</span></div>
                                  <div><strong className="text-neutral-500">Tỷ lệ diện tích:</strong> {det.quantitative_evidence.area_ratio ? `${(det.quantitative_evidence.area_ratio*100).toFixed(1)}%` : 'N/A'}</div>
                                  <div><strong className="text-neutral-500">Mức độ đo:</strong> <span className="text-orange-300">{det.quantitative_evidence.quantitative_severity || 'unknown'}</span></div>
                                </div>
                                <div className="text-blue-200/90 italic mt-1 leading-snug">
                                  {det.quantitative_evidence.rationale || 'Không có giải thích tự động chuyên sâu từ AI.'}
                                </div>
                              </>
                            ) : (
                              <div className="text-neutral-500 italic">Không cung cấp bằng chứng định lượng.</div>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Zone D: Findings Draft & Knowledge */}
                      <div className="flex-1 flex flex-col overflow-hidden">
                        <div className="flex border-b border-neutral-800 shrink-0 bg-neutral-900 px-4 pt-2">
                          <div className="px-4 py-2 text-xs font-bold uppercase tracking-wider text-blue-300 bg-neutral-800 border-t border-x border-neutral-700 rounded-t-lg">
                            Bản thảo Chẩn đoán (Draft)
                          </div>
                        </div>

                        <div className="flex-1 overflow-y-auto custom-scrollbar p-6 bg-neutral-800">
                          <div className="space-y-5 animate-in fade-in duration-200">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                              <div>
                                <label className="block text-xs font-bold text-neutral-400 mb-1.5 uppercase tracking-wide">Impression / Findings</label>
                                <textarea 
                                  className="w-full h-32 rounded bg-meta-black border border-neutral-600 p-3 text-sm text-green-400 font-mono focus:border-blue-500 focus:outline-none custom-scrollbar shadow-inner"
                                  style={{ backgroundColor: '#000' }}
                                  value={det.findings_draft?.impression || ''}
                                  onChange={e => {
                                    const newList = [...editableDetections];
                                    if (!newList[idx].findings_draft) newList[idx].findings_draft = {};
                                    newList[idx].findings_draft.impression = e.target.value;
                                    setEditableDetections(newList);
                                  }}
                                />
                              </div>
                              <div>
                                <label className="block text-xs font-bold text-neutral-400 mb-1.5 uppercase tracking-wide">Recommended Next Steps</label>
                                <textarea 
                                  className="w-full h-32 rounded bg-meta-black border border-neutral-600 p-3 text-sm text-green-400 font-mono focus:border-blue-500 focus:outline-none custom-scrollbar shadow-inner"
                                  style={{ backgroundColor: '#000' }}
                                  value={det.findings_draft?.recommended_next_steps || ''}
                                  onChange={e => {
                                    const newList = [...editableDetections];
                                    if (!newList[idx].findings_draft) newList[idx].findings_draft = {};
                                    newList[idx].findings_draft.recommended_next_steps = e.target.value;
                                    setEditableDetections(newList);
                                  }}
                                />
                              </div>
                            </div>

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 pt-3 border-t border-neutral-700/50">
                              <div>
                                <label className="block text-xs font-bold text-neutral-400 mb-1.5 uppercase tracking-wide">Severity Assessment</label>
                                <input 
                                  type="text"
                                  className="w-full rounded bg-meta-black border border-neutral-600 p-2 text-sm text-green-400 font-mono focus:border-blue-500 focus:outline-none shadow-inner"
                                  style={{ backgroundColor: '#000' }}
                                  value={det.findings_draft?.severity_assessment || ''}
                                  onChange={e => {
                                    const newList = [...editableDetections];
                                    if (!newList[idx].findings_draft) newList[idx].findings_draft = {};
                                    newList[idx].findings_draft.severity_assessment = e.target.value;
                                    setEditableDetections(newList);
                                  }}
                                />
                              </div>
                              <div className="flex items-center mt-6">
                                <label className="flex items-center gap-3 cursor-pointer bg-neutral-900 p-2 px-3 rounded border border-neutral-700 hover:border-neutral-500 transition-colors">
                                  <input 
                                    type="checkbox"
                                    className="h-4 w-4 rounded border-neutral-600 text-blue-600 bg-black cursor-pointer"
                                    checked={det.findings_draft?.critical_flag || false}
                                    onChange={e => {
                                      const newList = [...editableDetections];
                                      if (!newList[idx].findings_draft) newList[idx].findings_draft = {};
                                      newList[idx].findings_draft.critical_flag = e.target.checked;
                                      setEditableDetections(newList);
                                    }}
                                  />
                                  <span className="text-sm font-bold text-red-400 tracking-wide uppercase">Critical Flag</span>
                                </label>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                      
                      {/* Footer */}
                      <div className="shrink-0 flex justify-end items-center gap-3 p-4 border-t border-neutral-800 bg-neutral-900">
                        <span className="text-xs text-neutral-500 mr-auto flex items-center gap-2">
                           <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></div>
                           RAG1 MAPPING ACTIVE
                        </span>
                        <button 
                          type="button" 
                          className="rounded-lg border border-neutral-600 bg-neutral-800 px-6 py-2 text-sm font-medium text-white hover:bg-neutral-700 transition-colors" 
                          onClick={() => setExpandedJsonDetId(null)}
                        >
                          Cancel
                        </button>
                        <button 
                          type="button" 
                          className="rounded-lg px-6 py-2 text-sm font-bold tracking-wide text-white shadow-lg transition-colors flex items-center justify-center bg-blue-600 hover:bg-blue-500 hover:shadow-blue-500/30"
                          onClick={() => {
                            try {
                              const parsed = editableDetections;
                              const result = AIAnnotationStore.getRAGResult();
                              const apiResponse = AIAnnotationStore.getRAGAPIResponse();
                              
                              if (result && apiResponse && Array.isArray(parsed)) {
                                parsed.forEach((parsedDet) => {
                                  const index = result.results_per_detection.findIndex(d => d.det_id === parsedDet.det_id);
                                  if (index !== -1) {
                                    result.results_per_detection[index] = parsedDet;
                                  }
                                });
                                AIAnnotationStore.setRAGResult(apiResponse);
                                alert('Information saved successfully!');
                                setExpandedJsonDetId(null);
                              }
                            } catch (e) {
                              alert('Error saving data: ' + (e as Error).message);
                            }
                          }}
                        >
                          Save Changes
                        </button>
                      </div>
                    </>
                  );
                })() : (
                  <div className="flex-1 flex flex-col items-center justify-center text-neutral-500 bg-neutral-800/20">
                    <svg className="w-16 h-16 mb-4 text-neutral-700" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd"></path></svg>
                    <p>Select an AI Finding from the list to view details</p>
                  </div>
                )}
              </div>
            </div>

          </div>
        </div>,
        document.body
      )}

    </div>
  );
}
