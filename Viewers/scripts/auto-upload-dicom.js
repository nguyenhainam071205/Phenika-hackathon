#!/usr/bin/env node
/**
 * DICOM Upload Auto-Fixer
 * 
 * Automatically checks and fixes DICOM files before upload
 * 
 * Usage:
 *   node auto-upload-dicom.js <dicom-file-path> [--dry-run]
 * 
 * Examples:
 *   node auto-upload-dicom.js "path/to/file.dcm"
 *   node auto-upload-dicom.js "path/to/file.dicom" --dry-run
 */

const { ensureDicomValid } = require('./dicom-processor');
const path = require('path');
const fs = require('fs');

async function main() {
  const args = process.argv.slice(2);
  
  if (args.length === 0) {
    console.error('❌ Usage: node auto-upload-dicom.js <dicom-file-path> [--dry-run]');
    process.exit(1);
  }

  const dicomPath = args[0];
  const isDryRun = args.includes('--dry-run');

  if (!fs.existsSync(dicomPath)) {
    console.error(`❌ File not found: ${dicomPath}`);
    process.exit(1);
  }

  console.log('═══════════════════════════════════════════════════');
  console.log('  DICOM Upload Auto-Fixer');
  console.log('═══════════════════════════════════════════════════\n');

  const result = ensureDicomValid(dicomPath);

  if (result.error) {
    console.error(`\n❌ Error: ${result.error}`);
    process.exit(1);
  }

  console.log('\n' + '═══════════════════════════════════════════════════');
  if (result.wasFixed) {
    console.log(`✅ File is ready for upload: ${result.path}`);
    if (isDryRun) {
      console.log('(Dry-run mode: file was not uploaded)');
    }
  } else {
    console.log(`✅ File is already valid: ${dicomPath}`);
  }
  console.log('═══════════════════════════════════════════════════\n');

  process.exit(0);
}

main().catch(error => {
  console.error(`\n❌ Unexpected error: ${error.message}`);
  process.exit(1);
});
