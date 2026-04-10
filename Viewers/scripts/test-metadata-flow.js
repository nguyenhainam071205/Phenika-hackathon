/**
 * Test script để debug upload và update metadata flow
 * Chạy: node scripts/test-metadata-flow.js
 */

const fs = require('fs');
const path = require('path');

// Cấu hình
const ORTHANC_URL = 'http://localhost:8042';
const WADO_ROOT = `${ORTHANC_URL}/dicom-web`;
const TEST_DICOM_FILE = path.join(__dirname, '../testdata/generated-missing-tags.dcm');

// ============================================================================
// Test 1: Upload DICOM với clinical metadata
// ============================================================================
async function testUploadWithMetadata() {
  console.log('\n========== TEST 1: Upload DICOM with Metadata ==========');

  if (!fs.existsSync(TEST_DICOM_FILE)) {
    console.error(`❌ Test DICOM file not found: ${TEST_DICOM_FILE}`);
    return;
  }

  try {
    const dicomBuffer = fs.readFileSync(TEST_DICOM_FILE);
    console.log(`✓ Loaded DICOM file: ${TEST_DICOM_FILE} (${dicomBuffer.length} bytes)`);

    // Simulate clinical metadata from upload dialog
    const clinicalMetadata = {
      patientId: 'BN-TEST-001',
      patientName: 'Nguyễn Văn Test',
      patientBirthDate: '19900515',
      patientSex: 'M',
      studyDescription: 'Test phim chụp tiếng Việt',
    };

    console.log('📝 Clinical Metadata:', clinicalMetadata);

    // Upload to STOW-RS endpoint (via proxy)
    const uploadUrl = `${WADO_ROOT}/studies`;
    console.log(`\n→ Upload URL: ${uploadUrl}`);
    console.log(`   Content-Type: multipart/related; type=application/dicom`);

    // Create multipart/related body
    const boundary = '----boundary' + Date.now();
    const multipartBody = Buffer.concat([
      Buffer.from(`--${boundary}\r\nContent-Type: application/dicom\r\n\r\n`),
      dicomBuffer,
      Buffer.from(`\r\n--${boundary}--\r\n`),
    ]);

    const uploadResponse = await fetch(uploadUrl, {
      method: 'POST',
      headers: {
        'Content-Type': `multipart/related; type=application/dicom; boundary=${boundary}`,
      },
      body: multipartBody,
    });

    console.log(`← Response Status: ${uploadResponse.status} ${uploadResponse.statusText}`);

    if (uploadResponse.ok) {
      console.log('✅ Upload SUCCESS');
      const responseText = await uploadResponse.text();
      console.log('   Response:', responseText.substring(0, 200));

      // Extract study UID from response if available
      try {
        const responseData = JSON.parse(responseText);
        if (responseData[0]) {
          const studyUid = Object.values(responseData[0])[0]?.Value?.[0];
          console.log(`   StudyInstanceUID: ${studyUid}`);
          return studyUid;
        }
      } catch (e) {
        console.log('   (Response is not JSON, skipping UID extraction)');
      }
    } else {
      console.error(`❌ Upload FAILED: ${uploadResponse.status}`);
      const responseText = await uploadResponse.text();
      console.error('   Error:', responseText);
    }
  } catch (error) {
    console.error('❌ Upload Error:', error.message);
  }
}

// ============================================================================
// Test 2: Update study metadata via Orthanc REST /modify
// ============================================================================
async function testUpdateStudyMetadata(studyInstanceUID) {
  console.log('\n========== TEST 2: Update Study Metadata ==========');

  if (!studyInstanceUID) {
    console.log('⚠️  Skipping update test (no StudyInstanceUID provided)');
    console.log('   (Usually from previous upload test or manual input)');
    return;
  }

  try {
    // Step 1: Find Orthanc Study ID from StudyInstanceUID
    console.log(`\n→ Finding Orthanc Study ID for StudyInstanceUID: ${studyInstanceUID}`);

    const findUrl = `${ORTHANC_URL}/tools/find`;
    console.log(`   Request URL: ${findUrl}`);
    console.log('   Request Body:', JSON.stringify({
      Level: 'Study',
      Query: { StudyInstanceUID },
    }, null, 2));

    const findResponse = await fetch(findUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        Level: 'Study',
        Query: { StudyInstanceUID },
      }),
    });

    console.log(`← Response Status: ${findResponse.status}`);

    if (!findResponse.ok) {
      console.error(`❌ Find failed: ${findResponse.status}`);
      const errorText = await findResponse.text();
      console.error('   Error:', errorText);
      return;
    }

    const orthancStudyIds = await findResponse.json();
    console.log(`✓ Found Orthanc Study IDs:`, orthancStudyIds);

    if (!Array.isArray(orthancStudyIds) || orthancStudyIds.length === 0) {
      console.error('❌ No Orthanc Study ID found');
      return;
    }

    const orthancStudyId = orthancStudyIds[0];
    console.log(`✓ Using first ID: ${orthancStudyId}`);

    // Step 2: Update metadata via /modify endpoint
    console.log(`\n→ Updating metadata for Orthanc Study: ${orthancStudyId}`);

    const modifyUrl = `${ORTHANC_URL}/studies/${encodeURIComponent(orthancStudyId)}/modify`;
    const updatePayload = {
      Replace: {
        PatientID: 'BN-TEST-UPDATED',
        PatientName: 'Nguyễn Văn Updated',
        StudyDescription: 'Test updated metadata tiếng Việt',
      },
    };

    console.log(`   Request URL: ${modifyUrl}`);
    console.log('   Request Body:', JSON.stringify(updatePayload, null, 2));

    const updateResponse = await fetch(modifyUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updatePayload),
    });

    console.log(`← Response Status: ${updateResponse.status} ${updateResponse.statusText}`);

    if (updateResponse.ok) {
      console.log('✅ Update SUCCESS');
      const responseText = await updateResponse.text();
      if (responseText) {
        console.log('   Response:', responseText.substring(0, 200));
      }
    } else {
      console.error(`❌ Update FAILED: ${updateResponse.status}`);
      const errorText = await updateResponse.text();
      console.error('   Error:', errorText);
    }
  } catch (error) {
    console.error('❌ Update Error:', error.message);
  }
}

// ============================================================================
// Test 3: Verify data via QIDO query
// ============================================================================
async function testVerifyWithQido(studyInstanceUID) {
  console.log('\n========== TEST 3: Verify Data via QIDO ==========');

  if (!studyInstanceUID) {
    console.log('⚠️  Skipping QIDO verify (no StudyInstanceUID provided)');
    return;
  }

  try {
    const qidoUrl = `${WADO_ROOT}/studies?StudyInstanceUID=${encodeURIComponent(studyInstanceUID)}`;
    console.log(`→ Query URL: ${qidoUrl}`);

    const queryResponse = await fetch(qidoUrl, {
      method: 'GET',
      headers: { 'Accept': 'application/dicom+json' },
    });

    console.log(`← Response Status: ${queryResponse.status}`);

    if (queryResponse.ok) {
      const results = await queryResponse.json();
      console.log('✅ QIDO Query SUCCESS\n');
      console.log('📊 Study Data from Server:');
      if (results.length > 0) {
        const study = results[0];
        console.log('  PatientID:', study['00100020']?.Value?.[0] || 'N/A');
        console.log('  PatientName:', study['00100010']?.Value?.[0] || 'N/A');
        console.log('  PatientSex:', study['00100040']?.Value?.[0] || 'N/A');
        console.log('  PatientBirthDate:', study['00100030']?.Value?.[0] || 'N/A');
        console.log('  StudyDescription:', study['00081030']?.Value?.[0] || 'N/A');
      }
    } else {
      console.error(`❌ QIDO Query failed: ${queryResponse.status}`);
      const errorText = await queryResponse.text();
      console.error('   Error:', errorText.substring(0, 200));
    }
  } catch (error) {
    console.error('❌ QIDO Error:', error.message);
  }
}

// ============================================================================
// Main
// ============================================================================
async function main() {
  console.log('🧪 METADATA FLOW TEST SUITE');
  console.log('============================');
  console.log(`Orthanc Server: ${ORTHANC_URL}`);
  console.log(`WADO Root: ${WADO_ROOT}`);

  // Check Orthanc connectivity
  try {
    const healthResponse = await fetch(`${ORTHANC_URL}/system`);
    if (healthResponse.ok) {
      console.log('✅ Orthanc server is reachable\n');
    } else {
      console.error('❌ Orthanc server returned non-200 status');
      return;
    }
  } catch (error) {
    console.error('❌ Cannot reach Orthanc server:', error.message);
    console.error('   Make sure Orthanc is running on', ORTHANC_URL);
    return;
  }

  // Run tests
  const studyUid = await testUploadWithMetadata();
  if (studyUid) {
    await testUpdateStudyMetadata(studyUid);
    await testVerifyWithQido(studyUid);
  }

  console.log('\n✅ Test suite completed\n');
}

main().catch(error => {
  console.error('Fatal error:', error);
  process.exit(1);
});
