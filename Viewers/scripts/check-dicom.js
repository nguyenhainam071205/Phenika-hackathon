const fs = require('fs');

async function checkDicomFile(filePath) {
  try {
    if (!fs.existsSync(filePath)) {
      console.error(`❌ File không tồn tại: ${filePath}`);
      process.exit(1);
    }

    const stats = fs.statSync(filePath);
    console.log(`📄 File size: ${(stats.size / 1024 / 1024).toFixed(2)} MB (${stats.size} bytes)`);
    console.log(`📍 File path: ${filePath}\n`);

    const buffer = fs.readFileSync(filePath);

    // Kiểm tra DICOM prefix
    if (buffer.length < 132) {
      console.error('❌ File quá nhỏ để là file DICOM');
      process.exit(1);
    }

    const prefix = buffer.toString('ascii', 128, 132);
    const hasDicomPrefix = prefix === 'DICM';
    console.log(`DICOM Prefix check (offset 128): ${hasDicomPrefix ? '✅ DICM found' : '❌ No DICM prefix'}`);

    if (!hasDicomPrefix) {
      console.log('⚠️  Cảnh báo: File không có DICOM prefix tiêu chuẩn (DICM).\n');
    }

    // Check preamble
    let hasPreamble = true;
    for (let i = 0; i < 128; i++) {
      if (buffer[i] !== 0) {
        hasPreamble = false;
        break;
      }
    }
    console.log(`DICOM Preamble (128 zero bytes): ${hasPreamble ? '✅ Valid' : '⚠️  Not standard'}\n`);

    // Parse DICOM tags - thử cả Explicit VR Little Endian và Implicit VR
    console.log('📋 Parsing DICOM tags...\n');
    
    let offset = 132;
    const tags = [];
    const requiredTags = {
      '0008,0020': 'StudyDate',
      '0008,0030': 'StudyTime',
      '0008,0016': 'SOPClassUID',
      '0008,0018': 'SOPInstanceUID',
      '0010,0010': 'PatientName',
      '0010,0020': 'PatientID',
      '0020,000D': 'StudyInstanceUID',
      '0020,000E': 'SeriesInstanceUID',
      '0028,0010': 'Rows',
      '0028,0011': 'Columns',
    };

    const foundRequiredTags = {};
    for (const tag of Object.keys(requiredTags)) {
      foundRequiredTags[tag] = false;
    }

    // Try to parse - flexible approach
    let tagCount = 0;
    const maxTags = 2000;

    while (offset < buffer.length - 8 && tagCount < maxTags) {
      try {
        const group = buffer.readUInt16LE(offset);
        const element = buffer.readUInt16LE(offset + 2);
        
        // Skip invalid groups
        if (group === 0xFFFE || group === 0x0000) {
          offset += 4;
          continue;
        }

        const tagHex = `${group.toString(16).padStart(4, '0')},${element.toString(16).padStart(4, '0')}`.toUpperCase();

        // Try reading VR (Explicit VR)
        let vr = 'UN';
        let valueLength = 0;
        let nextOffset = offset + 4;

        if (nextOffset + 2 <= buffer.length) {
          const potentialVR = buffer.toString('ascii', nextOffset, nextOffset + 2);
          
          // Check if valid VR
          if (/^[A-Z]{2}$/.test(potentialVR) && ![
            'AE', 'AS', 'AT', 'CS', 'DA', 'DS', 'DT', 'FD', 'FL', 'IS', 'LO',
            'LT', 'OB', 'OD', 'OF', 'OL', 'OW', 'PN', 'SH', 'SL', 'SQ', 'SS',
            'ST', 'TM', 'UC', 'UI', 'UL', 'UN', 'UR', 'US', 'UT'
          ].includes(potentialVR)) {
            vr = 'UN';
          } else {
            vr = potentialVR;
            nextOffset += 2;

            if (['OB', 'OD', 'OF', 'OL', 'OW', 'SQ', 'UN', 'UR', 'UT'].includes(vr)) {
              if (nextOffset + 6 <= buffer.length) {
                nextOffset += 2; // Reserved
                valueLength = buffer.readUInt32LE(nextOffset);
                nextOffset += 4;
              }
            } else {
              if (nextOffset + 2 <= buffer.length) {
                valueLength = buffer.readUInt16LE(nextOffset);
                nextOffset += 2;
              }
            }
          }
        }

        tags.push({
          tag: tagHex,
          vr: vr,
          length: valueLength
        });

        if (requiredTags[tagHex]) {
          foundRequiredTags[tagHex] = true;
        }

        tagCount++;
        offset = nextOffset;

        // Skip to next tag
        if (valueLength > 0 && nextOffset + valueLength <= buffer.length) {
          offset = nextOffset + valueLength;
        }

      } catch (e) {
        offset += 4;
      }
    }

    console.log(`✅ Found ${tagCount} DICOM tags\n`);

    // Display found tags
    console.log('📌 Required tags status:\n');
    let missingCount = 0;
    let foundCount = 0;

    for (const [tag, name] of Object.entries(requiredTags)) {
      if (foundRequiredTags[tag]) {
        const tagData = tags.find(t => t.tag === tag);
        console.log(`✅ ${tag} (${name})`);
        foundCount++;
      } else {
        console.log(`❌ ${tag} (${name}) - MISSING`);
        missingCount++;
      }
    }

    // Summary
    console.log('\n📊 SUMMARY:\n');

    if (tagCount === 0) {
      console.log('❌ NO DICOM tags detected');
      console.log('   → This file might not be a valid DICOM format');
    } else if (missingCount > 0) {
      console.log(`⚠️  WARNING: Missing ${missingCount}/${Object.keys(requiredTags).length} required tags`);
      console.log(`✅ Found ${foundCount}/${Object.keys(requiredTags).length} required tags`);
      console.log('\nLikely issues:');
      console.log('• File is incomplete or corrupted');
      console.log('• File has non-standard DICOM structure');
      console.log('• Tags might be in a different encoding or byte order');
    } else {
      console.log(`✅ VALID DICOM file with all required tags (${tagCount} tags total)`);
    }

    // Show sample of found tags
    if (tagCount > 0) {
      console.log('\n📋 Sample of found tags:');
      tags.slice(0, 15).forEach(t => {
        console.log(`   ${t.tag} (${t.vr}): ${t.length} bytes`);
      });
      if (tagCount > 15) {
        console.log(`   ... and ${tagCount - 15} more tags`);
      }
    }

  } catch (error) {
    console.error('❌ Error:', error.message);
    process.exit(1);
  }
}

// Main
const dicomPath = process.argv[2] || 'C:/Users/Dell/OneDrive/Documents/Hackathon/0171021638f9272a34a41feb84ed47a0.dicom';
checkDicomFile(dicomPath);
