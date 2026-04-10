const { ensureDicomValid } = require('./dicom-processor');
const path = require('path');

// Test with the original problematic DICOM file
const testFile = 'C:/Users/Dell/OneDrive/Documents/Hackathon/0171021638f9272a34a41feb84ed47a0.dicom';
console.log(`Testing with: ${testFile}\n`);

const result = ensureDicomValid(testFile);
console.log('\nResult:', result);
