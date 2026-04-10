const { chromium } = require('playwright');
const { ensureDicomValid } = require('./dicom-processor');

async function getInstanceCount() {
  const response = await fetch('http://localhost:8042/instances');
  if (!response.ok) {
    throw new Error(`Failed to query Orthanc instances: ${response.status}`);
  }
  const data = await response.json();
  return Array.isArray(data) ? data.length : 0;
}

(async () => {
  let dicomPath =
    process.argv[2] ||
    'C:/Users/Dell/OneDrive/Documents/Hackathon/Viewers/node_modules/dicomweb-client/testData/sample2.dcm';

  // Auto-validate and fix DICOM if needed
  const processingResult = ensureDicomValid(dicomPath);
  if (processingResult.error) {
    throw new Error(`DICOM validation failed: ${processingResult.error}`);
  }
  dicomPath = processingResult.path;

  const beforeCount = await getInstanceCount();
  console.log(`Before upload instances: ${beforeCount}`);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  try {
    await page.goto('http://localhost:3000', { waitUntil: 'domcontentloaded', timeout: 60000 });

    const confirmBannerButton = page.getByText(/confirm and hide/i).first();
    if (await confirmBannerButton.isVisible().catch(() => false)) {
      await confirmBannerButton.click();
    }

    const uploadButtonByRole = page.getByRole('button', { name: /^upload$/i }).first();
    const uploadTriggerByText = page.getByText(/^upload$/i).first();

    if (await uploadButtonByRole.isVisible().catch(() => false)) {
      await uploadButtonByRole.click();
    } else {
      await uploadTriggerByText.waitFor({ timeout: 30000 });
      await uploadTriggerByText.click();
    }

    const addFilesButton = page.getByRole('button', { name: /add files/i }).first();
    await addFilesButton.waitFor({ timeout: 30000 });

    const fileInput = page.locator('input[type="file"]').first();
    await fileInput.setInputFiles(dicomPath);

    await page.waitForTimeout(10000);

    const errorMessages = [
      /request failed/i,
      /timed out/i,
      /not a valid dicom/i,
      /cancelled/i,
    ];

    for (const pattern of errorMessages) {
      const err = page.getByText(pattern).first();
      if (await err.isVisible().catch(() => false)) {
        throw new Error(`OHIF upload UI shows error: ${pattern}`);
      }
    }
  } finally {
    await browser.close();
  }

  const afterCount = await getInstanceCount();
  console.log(`After upload instances: ${afterCount}`);

  if (afterCount <= beforeCount) {
    throw new Error('Upload test did not increase Orthanc instance count.');
  }

  console.log('Upload UI smoke test passed.');
})().catch(error => {
  console.error(error.message);
  process.exit(1);
});
