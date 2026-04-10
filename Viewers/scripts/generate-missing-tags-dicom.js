const fs = require('fs');
const path = require('path');
const dcmjs = require('dcmjs');

const sourcePath =
  process.argv[2] ||
  'C:/Users/Dell/OneDrive/Documents/Hackathon/Viewers/node_modules/dicomweb-client/testData/sample2.dcm';
const targetPath =
  process.argv[3] ||
  'C:/Users/Dell/OneDrive/Documents/Hackathon/Viewers/testdata/generated-missing-tags.dcm';

const { DicomMessage, DicomDict, DicomMetaDictionary } = dcmjs.data;

const srcBuffer = fs.readFileSync(sourcePath);
const dicomData = DicomMessage.readFile(srcBuffer.buffer.slice(srcBuffer.byteOffset, srcBuffer.byteOffset + srcBuffer.byteLength));

const naturalized = DicomMetaDictionary.naturalizeDataset(dicomData.dict);
delete naturalized.PatientID;
delete naturalized.StudyInstanceUID;
delete naturalized.SeriesInstanceUID;
delete naturalized.SOPInstanceUID;

const patched = new DicomDict(dicomData.meta);
patched.dict = DicomMetaDictionary.denaturalizeDataset(naturalized);
const outBuffer = Buffer.from(patched.write());

fs.mkdirSync(path.dirname(targetPath), { recursive: true });
fs.writeFileSync(targetPath, outBuffer);

console.log(`Generated DICOM without mandatory tags: ${targetPath}`);
