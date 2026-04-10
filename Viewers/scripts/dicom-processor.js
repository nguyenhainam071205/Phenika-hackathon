const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const dcmjs = require('dcmjs');

const { DicomDict, DicomMessage, DicomMetaDictionary } = dcmjs.data;

const REQUIRED_TAGS = [
  {
    tag: '0008,0020',
    keyword: 'StudyDate',
    label: 'StudyDate',
    generate: ({ now }) => formatStudyDate(now),
  },
  {
    tag: '0008,0030',
    keyword: 'StudyTime',
    label: 'StudyTime',
    generate: ({ now }) => formatStudyTime(now),
  },
  {
    tag: '0008,0016',
    keyword: 'SOPClassUID',
    label: 'SOPClassUID',
    generate: ({ dataset, meta }) =>
      dataset.SOPClassUID || meta.MediaStorageSOPClassUID || '1.2.840.10008.5.1.4.1.1.7',
  },
  {
    tag: '0008,0018',
    keyword: 'SOPInstanceUID',
    label: 'SOPInstanceUID',
    generate: ({ dataset, meta }) => dataset.SOPInstanceUID || meta.MediaStorageSOPInstanceUID || generateUid(),
  },
  {
    tag: '0010,0010',
    keyword: 'PatientName',
    label: 'PatientName',
    generate: () => 'ANONYMOUS^PATIENT',
  },
  {
    tag: '0010,0020',
    keyword: 'PatientID',
    label: 'PatientID',
    generate: ({ now }) => `PAT${formatTimestamp(now)}`,
  },
  {
    tag: '0020,000D',
    keyword: 'StudyInstanceUID',
    label: 'StudyInstanceUID',
    generate: () => generateUid(),
  },
  {
    tag: '0020,000E',
    keyword: 'SeriesInstanceUID',
    label: 'SeriesInstanceUID',
    generate: () => generateUid(),
  },
];

function bufferToArrayBuffer(buffer) {
  return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
}

function formatStudyDate(now) {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}${month}${day}`;
}

function formatStudyTime(now) {
  const hours = String(now.getHours()).padStart(2, '0');
  const minutes = String(now.getMinutes()).padStart(2, '0');
  const seconds = String(now.getSeconds()).padStart(2, '0');
  const milliseconds = String(now.getMilliseconds()).padStart(3, '0');
  return `${hours}${minutes}${seconds}.${milliseconds}`;
}

function formatTimestamp(now) {
  return `${formatStudyDate(now)}${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`;
}

function generateUid() {
  const uuidHex = crypto.randomUUID().replace(/-/g, '');
  return `2.25.${BigInt(`0x${uuidHex}`).toString(10)}`;
}

function isMissingValue(value) {
  if (value === undefined || value === null) {
    return true;
  }

  if (Array.isArray(value)) {
    return value.length === 0 || value.every(isMissingValue);
  }

  if (typeof value === 'string') {
    return value.trim() === '';
  }

  return false;
}

function readDicomFromFile(filePath) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`File not found: ${filePath}`);
  }

  const sourceBuffer = fs.readFileSync(filePath);
  const fileArrayBuffer = bufferToArrayBuffer(sourceBuffer);
  const dicomData = DicomMessage.readFile(fileArrayBuffer);
  const dataset = DicomMetaDictionary.naturalizeDataset(dicomData.dict);
  const meta = DicomMetaDictionary.naturalizeDataset(dicomData.meta);

  return {
    sourceBuffer,
    dicomData,
    dataset,
    meta,
  };
}

function checkDicomTags(filePath) {
  try {
    const { dataset } = readDicomFromFile(filePath);
    const missingTags = REQUIRED_TAGS.filter(definition => isMissingValue(dataset[definition.keyword]));

    return {
      isValid: missingTags.length === 0,
      needsFixing: missingTags.length > 0,
      foundTags: REQUIRED_TAGS.length - missingTags.length,
      missingTags: missingTags.map(definition => ({
        tag: definition.tag,
        keyword: definition.keyword,
        label: definition.label,
      })),
    };
  } catch (error) {
    return {
      isValid: false,
      needsFixing: false,
      error: error.message,
    };
  }
}

function buildPatchedDataset(dataset, meta) {
  const now = new Date();
  const patchedDataset = { ...dataset };
  const generatedTags = [];

  for (const definition of REQUIRED_TAGS) {
    if (!isMissingValue(patchedDataset[definition.keyword])) {
      continue;
    }

    const generatedValue = definition.generate({
      dataset: patchedDataset,
      meta,
      now,
    });

    patchedDataset[definition.keyword] = generatedValue;
    generatedTags.push({
      tag: definition.tag,
      keyword: definition.keyword,
      label: definition.label,
      value: generatedValue,
    });
  }

  return { patchedDataset, generatedTags };
}

function buildPatchedMeta(meta, dataset) {
  const patchedMeta = { ...meta };

  patchedMeta.MediaStorageSOPClassUID = dataset.SOPClassUID;
  patchedMeta.MediaStorageSOPInstanceUID = dataset.SOPInstanceUID;
  patchedMeta.TransferSyntaxUID = patchedMeta.TransferSyntaxUID || '1.2.840.10008.1.2.1';
  patchedMeta.ImplementationVersionName = patchedMeta.ImplementationVersionName || 'OHIFAUTOFIX';
  patchedMeta.ImplementationClassUID =
    patchedMeta.ImplementationClassUID || '2.25.80302813137786398554742050926734630921603366648225212145404';

  return patchedMeta;
}

function getFixedOutputPath(inputPath) {
  if (/\.(dcm|dicom)$/i.test(inputPath)) {
    return inputPath.replace(/\.(dcm|dicom)$/i, '_auto_fixed.$1');
  }

  return `${inputPath}_auto_fixed.dcm`;
}

function fixDicomFile(inputPath, outputPath = getFixedOutputPath(inputPath)) {
  try {
    const { dataset, meta } = readDicomFromFile(inputPath);
    const { patchedDataset, generatedTags } = buildPatchedDataset(dataset, meta);
    const patchedMeta = buildPatchedMeta(meta, patchedDataset);

    const dicomDict = new DicomDict(DicomMetaDictionary.denaturalizeDataset(patchedMeta));
    dicomDict.dict = DicomMetaDictionary.denaturalizeDataset(patchedDataset);

    const outBuffer = Buffer.from(dicomDict.write());
    fs.writeFileSync(outputPath, outBuffer);

    return {
      outputPath,
      generatedTags,
    };
  } catch (error) {
    throw new Error(`Failed to fix DICOM: ${error.message}`);
  }
}

function ensureDicomValid(inputPath) {
  console.log(`\nChecking DICOM file: ${path.basename(inputPath)}`);

  const checkResult = checkDicomTags(inputPath);

  if (checkResult.error) {
    return { path: inputPath, wasFixed: false, error: checkResult.error };
  }

  if (checkResult.isValid) {
    console.log(`All required tags are present (${checkResult.foundTags}/${REQUIRED_TAGS.length}).`);
    return {
      path: inputPath,
      wasFixed: false,
      missingTags: [],
      generatedTags: [],
    };
  }

  console.log(`Missing ${checkResult.missingTags.length} required tags:`);
  for (const missingTag of checkResult.missingTags) {
    console.log(`- ${missingTag.tag} ${missingTag.label}`);
  }

  try {
    const fixedPath = getFixedOutputPath(inputPath);
    const fixResult = fixDicomFile(inputPath, fixedPath);
    const verifyResult = checkDicomTags(fixedPath);

    if (!verifyResult.isValid) {
      throw new Error('Verification failed after generating missing tags');
    }

    console.log('Generated tags:');
    for (const generatedTag of fixResult.generatedTags) {
      console.log(`- ${generatedTag.tag} ${generatedTag.label}: ${generatedTag.value}`);
    }

    console.log(`Saved fixed DICOM: ${path.basename(fixedPath)}`);

    return {
      path: fixedPath,
      wasFixed: true,
      missingTags: checkResult.missingTags,
      generatedTags: fixResult.generatedTags,
    };
  } catch (error) {
    return { path: inputPath, wasFixed: false, error: error.message };
  }
}

module.exports = {
  REQUIRED_TAGS,
  checkDicomTags,
  fixDicomFile,
  ensureDicomValid,
};
