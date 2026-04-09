import struct
import sys
import os

def analyze_dicom(filepath):
    """Analyze DICOM file structure"""
    
    if not os.path.exists(filepath):
        print(f"❌ File không tồn tại: {filepath}")
        sys.exit(1)
    
    try:
        with open(filepath, 'rb') as f:
            # Get file size
            f.seek(0, 2)
            file_size = f.tell()
            f.seek(0)
            
            size_mb = file_size / 1024 / 1024
            print(f"📄 File size: {size_mb:.2f} MB ({file_size} bytes)")
            print(f"📍 File path: {filepath}\n")
            
            # Check preamble (128 zeros)
            preamble = f.read(128)
            has_preamble = all(b == 0 for b in preamble)
            print(f"DICOM Preamble (128 zero bytes): {'✅ Valid' if has_preamble else '⚠️  Not standard'}")
            
            # Check DICM prefix
            dicm_marker = f.read(4)
            has_dicm = dicm_marker == b'DICM'
            print(f"DICOM Prefix check (offset 128): {'✅ DICM found' if has_dicm else '❌ No DICM prefix'}")
            
            if not has_dicm:
                print("\n⚠️  File không hợp lệ - thiếu DICM marker\n")
            
            print("\n📋 Parsing File Meta Information Group...\n")
            
            # Parse File Meta Information Group (Group 0002)
            required_tags = {
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
            }
            
            tags_found = {}
            tag_count = 0
            
            # Parse DICOM tags
            while f.tell() < file_size:
                try:
                    # Read tag (group, element)
                    tag_bytes = f.read(4)
                    if len(tag_bytes) < 4:
                        break
                    
                    group, element = struct.unpack('<HH', tag_bytes)
                    
                    # Skip if group is 0x0000 or 0xFFFE
                    if group in [0x0000, 0xFFFE]:
                        continue
                    
                    # Read VR (2 bytes)
                    vr_bytes = f.read(2)
                    if len(vr_bytes) < 2:
                        break
                    
                    # Determine if valid VR
                    vr_list = ['AE', 'AS', 'AT', 'CS', 'DA', 'DS', 'DT', 'FD', 'FL', 'IS', 'LO',
                              'LT', 'OB', 'OD', 'OF', 'OL', 'OW', 'PN', 'SH', 'SL', 'SQ', 'SS',
                              'ST', 'TM', 'UC', 'UI', 'UL', 'UN', 'UR', 'US', 'UT']
                    
                    vr = vr_bytes.decode('ascii', errors='ignore')
                    
                    if not vr.isalpha() or vr not in vr_list:
                        # Treat as implicit VR - go back 2 bytes
                        f.seek(-2, 1)
                        vr = 'UN'
                        # Read 4-byte length for implicit VR
                        if len(f.read(4)) < 4:
                            break
                        f.seek(-4, 1)
                        length_bytes = f.read(4)
                        value_length = struct.unpack('<I', length_bytes)[0]
                    else:
                        # Explicit VR
                        if vr in ['OB', 'OD', 'OF', 'OL', 'OW', 'SQ', 'UN', 'UR', 'UT']:
                            # 2 reserved bytes + 4-byte length
                            f.read(2)  # reserved
                            length_bytes = f.read(4)
                            if len(length_bytes) < 4:
                                break
                            value_length = struct.unpack('<I', length_bytes)[0]
                        else:
                            # 2-byte length
                            length_bytes = f.read(2)
                            if len(length_bytes) < 2:
                                break
                            value_length = struct.unpack('<H', length_bytes)[0]
                    
                    tag_hex = f'{group:04X},{element:04X}'
                    tags_found[tag_hex] = {'vr': vr, 'length': value_length}
                    tag_count += 1
                    
                    # Skip the value
                    current_pos = f.tell()
                    if current_pos + value_length <= file_size:
                        f.seek(value_length, 1)
                    else:
                        break
                    
                    if tag_count > 5000:  # Safety limit
                        break
                        
                except Exception as e:
                    break
            
            print(f"✅ Found {tag_count} DICOM tags\n")
            
            # Check for required tags
            print("📌 Required tags status:\n")
            found_count = 0
            missing_count = 0
            
            for tag, name in required_tags.items():
                if tag in tags_found:
                    print(f"✅ {tag} ({name})")
                    found_count += 1
                else:
                    print(f"❌ {tag} ({name}) - MISSING")
                    missing_count += 1
            
            # Summary
            print("\n📊 SUMMARY:\n")
            
            if tag_count == 0:
                print("❌ NO DICOM tags detected")
                print("   → This file is NOT a valid DICOM format")
            elif missing_count > 0:
                print(f"⚠️  WARNING: Missing {missing_count}/{len(required_tags)} required tags")
                print(f"✅ Found {found_count}/{len(required_tags)} required tags")
                print("\nLikely issues:")
                print("• File may be incomplete or corrupted")
                print("• File has non-standard DICOM structure")
                print("• Critical metadata tags are missing")
            else:
                print(f"✅ VALID DICOM file with all required tags ({tag_count} tags total)")
            
            # Sample tags
            if tag_count > 0:
                print("\n📋 Sample of found tags:")
                sample_tags = sorted(list(tags_found.items()))[:20]
                for tag, info in sample_tags:
                    print(f"   {tag} ({info['vr']}): {info['length']} bytes")
                if len(tags_found) > 20:
                    print(f"   ... and {len(tags_found) - 20} more tags")
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    dicom_path = sys.argv[1] if len(sys.argv) > 1 else 'C:/Users/Dell/OneDrive/Documents/Hackathon/0171021638f9272a34a41feb84ed47a0.dicom'
    analyze_dicom(dicom_path)
