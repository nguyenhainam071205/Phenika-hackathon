import React, { useCallback, useState } from 'react';
import { ReactElement } from 'react';
import Dropzone from 'react-dropzone';
import PropTypes from 'prop-types';
import classNames from 'classnames';
import DicomFileUploader from '../../utils/DicomFileUploader';
import DicomUploadProgress from './DicomUploadProgress';
import { Button } from '@ohif/ui-next';
// Removed dashed border CSS; using simple 1px solid border with muted foreground color

type DicomUploadProps = {
  dataSource;
  onComplete: () => void;
  onStarted: () => void;
};

type UploadClinicalMetadata = {
  patientId?: string;
  patientName?: string;
  patientBirthDate?: string;
  patientSex?: string;
  studyDescription?: string;
};

function DicomUpload({ dataSource, onComplete, onStarted }: DicomUploadProps): ReactElement {
  const baseClassNames =
    'min-h-[375px] flex flex-col bg-background select-none rounded-lg overflow-hidden';
  const [dicomFileUploaderArr, setDicomFileUploaderArr] = useState([]);
  const [metadata, setMetadata] = useState<UploadClinicalMetadata>({
    patientId: '',
    patientName: '',
    patientBirthDate: '',
    patientSex: '',
    studyDescription: '',
  });
  const [showUploadZone, setShowUploadZone] = useState(false);

  const updateMetadata = (key: keyof UploadClinicalMetadata, value: string) => {
    setMetadata(prev => ({
      ...prev,
      [key]: value,
    }));
  };

  const getNormalizedMetadata = (): UploadClinicalMetadata => {
    const normalize = value => (value || '').trim();

    return {
      patientId: normalize(metadata.patientId),
      patientName: normalize(metadata.patientName),
      patientBirthDate: normalize(metadata.patientBirthDate),
      patientSex: normalize(metadata.patientSex),
      studyDescription: normalize(metadata.studyDescription),
    };
  };

  const onDrop = useCallback(async acceptedFiles => {
    onStarted();
    const clinicalMetadata = getNormalizedMetadata();
    setDicomFileUploaderArr(
      acceptedFiles.map(file => new DicomFileUploader(file, dataSource, clinicalMetadata))
    );
  }, [dataSource, metadata]);

  const getDropZoneComponent = (): ReactElement => {
    return (
      <Dropzone
        onDrop={acceptedFiles => {
          onDrop(acceptedFiles);
        }}
        noClick
      >
        {({ getRootProps }) => (
          <div
            {...getRootProps()}
            className="m-5 flex h-full flex-col items-center justify-center rounded-2xl border"
            style={{ borderColor: 'hsl(var(--muted-foreground) / 0.25)' }}
          >
            <div className="flex gap-2">
              <Dropzone
                onDrop={onDrop}
                noDrag
              >
                {({ getRootProps, getInputProps }) => (
                  <div {...getRootProps()}>
                    <Button
                      variant="default"
                      size="lg"
                      disabled={false}
                      onClick={() => {}}
                    >
                      {'Add files'}
                      <input
                        {...getInputProps()}
                        style={{ display: 'none' }}
                      />
                    </Button>
                  </div>
                )}
              </Dropzone>
              <Dropzone
                onDrop={onDrop}
                noDrag
              >
                {({ getRootProps, getInputProps }) => (
                  <div {...getRootProps()}>
                    <Button
                      variant="secondary"
                      size="lg"
                      disabled={false}
                      onClick={() => {}}
                    >
                      {'Add folder'}
                      <input
                        {...getInputProps()}
                        webkitdirectory="true"
                        mozdirectory="true"
                        style={{ display: 'none' }}
                      />
                    </Button>
                  </div>
                )}
              </Dropzone>
            </div>
            <div className="text-foreground pt-6 text-base">or drag images or folders here</div>
            <div className="text-muted-foreground pt-1 text-base">(DICOM files supported)</div>
          </div>
        )}
      </Dropzone>
    );
  };

  const getClinicalMetadataForm = (): ReactElement => {
    return (
      <div className="border-input m-5 rounded-2xl border p-4">
        <div className="text-foreground mb-3 text-lg font-semibold">Tiếp nhận bệnh nhân</div>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <label className="flex flex-col gap-1">
            <span className="text-foreground text-sm">Mã bệnh nhân</span>
            <input
              className="border-input bg-background text-foreground rounded border px-3 py-2"
              value={metadata.patientId}
              onChange={event => updateMetadata('patientId', event.target.value)}
              placeholder="VD: BN001"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-foreground text-sm">Tên bệnh nhân</span>
            <input
              className="border-input bg-background text-foreground rounded border px-3 py-2"
              value={metadata.patientName}
              onChange={event => updateMetadata('patientName', event.target.value)}
              placeholder="VD: Nguyen Van A"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-foreground text-sm">Ngày sinh</span>
            <input
              type="date"
              className="border-input bg-background text-foreground rounded border px-3 py-2"
              value={metadata.patientBirthDate}
              onChange={event => updateMetadata('patientBirthDate', event.target.value)}
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-foreground text-sm">Giới tính</span>
            <select
              className="border-input bg-background text-foreground rounded border px-3 py-2"
              value={metadata.patientSex}
              onChange={event => updateMetadata('patientSex', event.target.value)}
            >
              <option value="">Chọn giới tính</option>
              <option value="M">Nam</option>
              <option value="F">Nữ</option>
              <option value="O">Khác</option>
            </select>
          </label>
        </div>

        <label className="mt-3 flex flex-col gap-1">
          <span className="text-foreground text-sm">Mô tả phiên chụp</span>
          <textarea
            className="border-input bg-background text-foreground min-h-24 rounded border px-3 py-2"
            value={metadata.studyDescription}
            onChange={event => updateMetadata('studyDescription', event.target.value)}
            placeholder="Nhập mô tả lâm sàng hoặc phiên chụp"
          />
        </label>

        <div className="mt-4 flex justify-end">
          <Button
            variant="default"
            size="lg"
            disabled={false}
            onClick={() => setShowUploadZone(true)}
          >
            Tiếp tục upload phim
          </Button>
        </div>
      </div>
    );
  };

  return (
    <>
      {dicomFileUploaderArr.length ? (
        <div className={classNames('h-[calc(100vh-300px)]', baseClassNames)}>
          <DicomUploadProgress
            dicomFileUploaderArr={Array.from(dicomFileUploaderArr)}
            onComplete={onComplete}
          />
        </div>
      ) : (
        <div className={classNames('h-[480px]', baseClassNames)}>
          {!showUploadZone ? getClinicalMetadataForm() : getDropZoneComponent()}
        </div>
      )}
    </>
  );
}

DicomUpload.propTypes = {
  dataSource: PropTypes.object.isRequired,
  onComplete: PropTypes.func.isRequired,
  onStarted: PropTypes.func.isRequired,
};

export default DicomUpload;
