import React, { ReactElement, memo, useCallback, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import DicomFileUploader, {
  DicomFileUploaderProgressEvent,
  EVENTS,
  UploadRejection,
  UploadStatus,
} from '../../utils/DicomFileUploader';
import { Icons } from '@ohif/ui-next';

type DicomUploadProgressItemProps = {
  dicomFileUploader: DicomFileUploader;
};

// eslint-disable-next-line react/display-name
const DicomUploadProgressItem = memo(
  ({ dicomFileUploader }: DicomUploadProgressItemProps): ReactElement => {
    const [percentComplete, setPercentComplete] = useState(dicomFileUploader.getPercentComplete());
    const [failedReason, setFailedReason] = useState('');
    const [status, setStatus] = useState(dicomFileUploader.getStatus());
    const [diagnosticMessage, setDiagnosticMessage] = useState(
      dicomFileUploader.getDiagnosticMessage()
    );
    const [missingTags, setMissingTags] = useState(dicomFileUploader.getMissingTags());

    const isComplete = useCallback(() => {
      return (
        status === UploadStatus.Failed ||
        status === UploadStatus.Cancelled ||
        status === UploadStatus.Success
      );
    }, [status]);

    useEffect(() => {
      const progressSubscription = dicomFileUploader.subscribe(
        EVENTS.PROGRESS,
        (dicomFileUploaderProgressEvent: DicomFileUploaderProgressEvent) => {
          setPercentComplete(dicomFileUploaderProgressEvent.percentComplete);
        }
      );

      dicomFileUploader
        .load()
        .catch((reason: UploadRejection) => {
          setStatus(reason.status);
          setFailedReason(reason.message ?? '');
          setDiagnosticMessage(dicomFileUploader.getDiagnosticMessage());
          setMissingTags(dicomFileUploader.getMissingTags());
        })
        .finally(() => {
          setStatus(dicomFileUploader.getStatus());
          setDiagnosticMessage(dicomFileUploader.getDiagnosticMessage());
          setMissingTags(dicomFileUploader.getMissingTags());
        });

      return () => progressSubscription.unsubscribe();
    }, []);

    const cancelUpload = useCallback(() => {
      dicomFileUploader.cancel();
    }, []);

    const getStatusIcon = (): ReactElement => {
      switch (dicomFileUploader.getStatus()) {
        case UploadStatus.Success:
          return (
            <Icons.ByName
              name="status-tracked"
              className="text-highlight"
            />
          );
        case UploadStatus.InProgress:
          return <Icons.ByName name="icon-transferring" />;
        case UploadStatus.Failed:
          return <Icons.ByName name="icon-alert-small" />;
        case UploadStatus.Cancelled:
          return <Icons.ByName name="icon-alert-outline" />;
        default:
          return <></>;
      }
    };

    return (
      <div className="min-h-14 border-input flex w-full items-center overflow-hidden border-b p-2.5 text-lg">
        <div className="self-top flex w-0 shrink grow flex-col gap-1">
          <div className="flex gap-4">
            <div className="flex w-6 shrink-0 items-center justify-center">{getStatusIcon()}</div>
            <div className="text-foreground overflow-hidden text-ellipsis whitespace-nowrap">
              {dicomFileUploader.getFileName()}
            </div>
          </div>
          {diagnosticMessage && (
            <div className="text-muted-foreground pl-10 text-sm">{diagnosticMessage}</div>
          )}
          {missingTags.length > 0 && (
            <div className="pl-10 text-sm">
              <div className="text-foreground/90">Missing tags:</div>
              <div className="text-muted-foreground mt-1 flex flex-col gap-1">
                {missingTags.map(tag => (
                  <div key={tag.tag}>{`${tag.label} (${tag.tag})`}</div>
                ))}
              </div>
            </div>
          )}
          {failedReason && (
            <div className="mt-2 rounded border border-red-600 bg-red-900/20 p-2 text-sm text-red-400">
              <div className="font-semibold">Error:</div>
              <div className="mt-1 break-words font-mono text-xs">{failedReason}</div>
            </div>
          )}
        </div>
        <div className="flex w-24 items-center">
          {!isComplete() && (
            <>
              {dicomFileUploader.getStatus() === UploadStatus.InProgress && (
                <div className="w-10 text-right">{percentComplete}%</div>
              )}
              <div className="ml-auto flex cursor-pointer">
                <Icons.Close
                  className="text-primary self-center"
                  onClick={cancelUpload}
                />
              </div>
            </>
          )}
        </div>
      </div>
    );
  }
);

DicomUploadProgressItem.propTypes = {
  dicomFileUploader: PropTypes.instanceOf(DicomFileUploader).isRequired,
};

export default DicomUploadProgressItem;
