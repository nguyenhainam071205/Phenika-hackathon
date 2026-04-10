import dicomImageLoader from '@cornerstonejs/dicom-image-loader';
import dicomParser from 'dicom-parser';

import { PubSubService } from '@ohif/core';

type MissingTagInfo = {
  tag: string;
  keyword: string;
  label: string;
};

type UploadClinicalMetadata = {
  patientId?: string;
  patientName?: string;
  patientBirthDate?: string;
  patientSex?: string;
  studyDescription?: string;
};

const REQUIRED_UPLOAD_TAGS: MissingTagInfo[] = [
  { tag: '0008,0020', keyword: 'x00080020', label: 'StudyDate' },
  { tag: '0008,0030', keyword: 'x00080030', label: 'StudyTime' },
  { tag: '0008,0016', keyword: 'x00080016', label: 'SOPClassUID' },
  { tag: '0008,0018', keyword: 'x00080018', label: 'SOPInstanceUID' },
  { tag: '0010,0010', keyword: 'x00100010', label: 'PatientName' },
  { tag: '0010,0020', keyword: 'x00100020', label: 'PatientID' },
  { tag: '0020,000D', keyword: 'x0020000d', label: 'StudyInstanceUID' },
  { tag: '0020,000E', keyword: 'x0020000e', label: 'SeriesInstanceUID' },
];

export const EVENTS = {
  PROGRESS: 'event:DicomFileUploader:progress',
};

export interface DicomFileUploaderEvent {
  fileId: number;
}

export interface DicomFileUploaderProgressEvent extends DicomFileUploaderEvent {
  percentComplete: number;
}

export enum UploadStatus {
  NotStarted,
  InProgress,
  Success,
  Failed,
  Cancelled,
}

type CancelOrFailed = UploadStatus.Cancelled | UploadStatus.Failed;

export class UploadRejection {
  message: string;
  status: CancelOrFailed;

  constructor(status: CancelOrFailed, message: string) {
    this.message = message;
    this.status = status;
  }
}

export default class DicomFileUploader extends PubSubService {
  private _file;
  private _fileId;
  private _dataSource;
  private _loadPromise;
  private _abortController = new AbortController();
  private _status: UploadStatus = UploadStatus.NotStarted;
  private _percentComplete = 0;
  private _diagnosticMessage = '';
  private _missingTags: MissingTagInfo[] = [];
  private _clinicalMetadata: UploadClinicalMetadata;

  constructor(file, dataSource, clinicalMetadata: UploadClinicalMetadata = {}) {
    super(EVENTS);
    this._file = file;
    this._fileId = dicomImageLoader.wadouri.fileManager.add(file);
    this._dataSource = dataSource;
    this._clinicalMetadata = clinicalMetadata;
  }

  getFileId(): string {
    return this._fileId;
  }

  getFileName(): string {
    return this._file.name;
  }

  getFileSize(): number {
    return this._file.size;
  }

  cancel(): void {
    this._abortController.abort();
  }

  getStatus(): UploadStatus {
    return this._status;
  }

  getPercentComplete(): number {
    return this._percentComplete;
  }

  getDiagnosticMessage(): string {
    return this._diagnosticMessage;
  }

  getMissingTags(): MissingTagInfo[] {
    return this._missingTags;
  }

  async load(): Promise<void> {
    if (this._loadPromise) {
      // Already started loading, return the load promise.
      return this._loadPromise;
    }

    this._loadPromise = new Promise<void>((resolve, reject) => {
      const upperName = (this._file?.name || '').toUpperCase();
      if (upperName === 'DICOMDIR') {
        this._reject(
          reject,
          new UploadRejection(
            UploadStatus.Cancelled,
            'Skipped DICOMDIR/index file. Please upload image instance files instead.'
          )
        );
        return;
      }

      // The upload listeners: fire progress events and/or settle the promise.
      const uploadCallbacks = {
        progress: evt => {
          if (!evt.lengthComputable) {
            // Progress computation is not possible.
            return;
          }

          this._status = UploadStatus.InProgress;

          this._percentComplete = Math.round((100 * evt.loaded) / evt.total);
          this._broadcastEvent(EVENTS.PROGRESS, {
            fileId: this._fileId,
            percentComplete: this._percentComplete,
          });
        },
        timeout: () => {
          this._reject(reject, new UploadRejection(UploadStatus.Failed, 'The request timed out.'));
        },
        abort: () => {
          this._reject(reject, new UploadRejection(UploadStatus.Cancelled, 'Cancelled'));
        },
        error: () => {
          this._reject(reject, new UploadRejection(UploadStatus.Failed, 'The request failed.'));
        },
      };

      // First try to load the file.
      dicomImageLoader.wadouri
        .loadFileRequest(this._fileId)
        .then(dicomFile => {
          if (this._abortController.signal.aborted) {
            this._reject(reject, new UploadRejection(UploadStatus.Cancelled, 'Cancelled'));
            return;
          }

          const validation = this._validateDicomFile(dicomFile);
          if (!validation.valid) {
            this._reject(
              reject,
              new UploadRejection(UploadStatus.Failed, validation.message)
            );
            return;
          }

          // Diagnostic-only: do not block upload, just surface likely root causes in console.
          this._logUploadDiagnostics(dicomFile);

          const request = new XMLHttpRequest();
          this._addRequestCallbacks(request, uploadCallbacks);

          // Do the actual upload by supplying the DICOM file and upload callbacks/listeners.
          return this._dataSource.store
            .dicom(dicomFile, request, undefined, this._clinicalMetadata)
            .then(() => {
              this._status = UploadStatus.Success;
              resolve();
            })
            .catch(reason => {
              this._reject(reject, reason);
            });
        })
        .catch(reason => {
          this._reject(reject, reason);
        });
    });

    return this._loadPromise;
  }

  private _isRejected(): boolean {
    return this._status === UploadStatus.Failed || this._status === UploadStatus.Cancelled;
  }

  private _reject(reject: (reason?: any) => void, reason: any) {
    if (this._isRejected()) {
      return;
    }

    if (reason instanceof UploadRejection) {
      this._status = reason.status;
      this._diagnosticMessage ||= reason.message ?? '';
      console.error('[DicomFileUploader] Upload rejection:', {
        fileName: this.getFileName(),
        status: reason.status,
        message: reason.message,
      });
      reject(reason);
      return;
    }

    this._status = UploadStatus.Failed;

    // Log full error for debugging
    console.error('[DicomFileUploader] Upload error:', {
      fileName: this.getFileName(),
      errorType: typeof reason,
      errorKeys: reason ? Object.keys(reason) : 'null',
      reason: reason,
    });

    if (reason?.status === 400 && reason?.response) {
      try {
        const response =
          typeof reason.response === 'string' ? JSON.parse(reason.response) : reason.response;

        console.warn('[OHIF Upload Diagnostic] STOW-RS 400 response for file:', {
          fileName: this.getFileName(),
          status: reason?.status,
          response,
        });

        // Orthanc STOW-RS failed instance response signature.
        if (response?.['00081199']) {
          const isDicomDirByName = (this.getFileName() || '').toUpperCase() === 'DICOMDIR';

          if (isDicomDirByName) {
            this._diagnosticMessage =
              'Detected DICOMDIR/index file. This type cannot be stored as a regular DICOM image instance.';
            console.warn(
              '[OHIF Upload Diagnostic] File appears to be DICOMDIR/index. Orthanc STOW-RS cannot store DICOMDIR as image instance.'
            );
          } else {
            this._diagnosticMessage =
              'File rejected as non-instance DICOM or missing mandatory tags.';
            console.warn(
              '[OHIF Upload Diagnostic] File was rejected by STOW-RS as non-instance DICOM or missing mandatory tags (PatientID/StudyUID/SeriesUID/SOPUID).'
            );
          }

          reject(
            new UploadRejection(
              UploadStatus.Cancelled,
              'Skipped non-instance DICOM file (likely DICOMDIR/index or missing mandatory tags).'
            )
          );
          return;
        }
      } catch {
        // Fall through to generic handling.
      }
    }

    // Build detailed error message
    let errorMessage = 'Upload failed.';
    if (reason?.message) {
      errorMessage = reason.message;
    } else if (reason?.response) {
      try {
        const parsedResponse = typeof reason.response === 'string' 
          ? JSON.parse(reason.response) 
          : reason.response;
        errorMessage = parsedResponse.Message || 
                      parsedResponse.HttpError || 
                      parsedResponse.OrthancError ||
                      JSON.stringify(parsedResponse).substring(0, 200);
      } catch {
        errorMessage = String(reason.response).substring(0, 200);
      }
    } else if (typeof reason === 'string') {
      errorMessage = reason;
    }

    console.error('[DicomFileUploader] Final error message:', errorMessage);
    reject(new UploadRejection(UploadStatus.Failed, errorMessage));
  }

  private _addRequestCallbacks(request: XMLHttpRequest, uploadCallbacks) {
    const abortCallback = () => request.abort();
    this._abortController.signal.addEventListener('abort', abortCallback);

    for (const [eventName, callback] of Object.entries(uploadCallbacks)) {
      request.upload.addEventListener(eventName, callback);
    }

    const cleanUpCallback = () => {
      this._abortController.signal.removeEventListener('abort', abortCallback);

      for (const [eventName, callback] of Object.entries(uploadCallbacks)) {
        request.upload.removeEventListener(eventName, callback);
      }

      request.removeEventListener('loadend', cleanUpCallback);
    };
    request.addEventListener('loadend', cleanUpCallback);
  }

  private _validateDicomFile(arrayBuffer: ArrayBuffer): { valid: boolean; message: string } {
    if (arrayBuffer.length <= 132) {
      return { valid: false, message: 'Not a valid DICOM file.' };
    }

    const arr = new Uint8Array(arrayBuffer.slice(128, 132));
    // bytes from 128 to 132 must be "DICM"
    const hasDicmPrefix = Array.from('DICM').every((char, i) => char.charCodeAt(0) === arr[i]);
    if (!hasDicmPrefix) {
      return { valid: false, message: 'Not a valid DICOM file.' };
    }

    return { valid: true, message: '' };
  }

  private _collectMissingTags(arrayBuffer: ArrayBuffer): MissingTagInfo[] {
    const dataSet = dicomParser.parseDicom(new Uint8Array(arrayBuffer));

    return REQUIRED_UPLOAD_TAGS.filter(tagDefinition => !dataSet.string(tagDefinition.keyword));
  }

  private _logUploadDiagnostics(arrayBuffer: ArrayBuffer): void {
    const fileName = this.getFileName();
    const upperName = (fileName || '').toUpperCase();
    this._missingTags = [];

    if (upperName === 'DICOMDIR') {
      this._diagnosticMessage =
        'Detected DICOMDIR/index file. This type is usually not storable via STOW-RS.';
      console.warn(
        '[OHIF Upload Diagnostic] Detected DICOMDIR by filename. This file is an index and usually cannot be stored via STOW-RS as an image instance.'
      );
    }

    try {
      const missingTags = this._collectMissingTags(arrayBuffer);
      this._missingTags = missingTags;

      if (missingTags.length > 0) {
        this._diagnosticMessage = `Missing ${missingTags.length} required DICOM tags. They will be auto-generated during upload.`;
        console.warn('[OHIF Upload Diagnostic] Mandatory tags missing before upload:', {
          fileName,
          missingTags: missingTags.map(tag => `${tag.label} (${tag.tag})`),
        });
      } else {
        this._diagnosticMessage = '';
        console.info('[OHIF Upload Diagnostic] Mandatory tags present before upload:', {
          fileName,
        });
      }
    } catch (error) {
      console.warn('[OHIF Upload Diagnostic] Unable to parse DICOM tags for diagnostics:', {
        fileName,
        error,
      });
    }
  }
}
