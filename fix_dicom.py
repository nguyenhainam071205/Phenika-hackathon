import struct
import sys
import os
from datetime import datetime
import uuid

def add_required_tags_to_dicom(input_path, output_path):
    """Add missing required tags to DICOM file"""
    
    if not os.path.exists(input_path):
        print(f"❌ Input file không tồn tại: {input_path}")
        sys.exit(1)
    
    print(f"📖 Reading DICOM file: {input_path}")
    
    with open(input_path, 'rb') as f:
        data = f.read()
    
    # Parse existing file to find data element position
    # File structure: [128 byte preamble][DICM][File Meta Info Group][Dataset]
    # We need to insert tags at the beginning of the dataset (after File Meta Info Group)
    
    # Find where File Meta Info Group ends (after Group 0002)
    offset = 132  # After preamble + DICM
    
    dataset_start = offset
    
    # Skip File Meta Information Group (all tags with group 0x0002)
    while offset < len(data) - 4:
        group_bytes = data[offset:offset+2]
        if len(group_bytes) < 2:
            break
        group = struct.unpack('<H', group_bytes)[0]
        
        if group != 0x0002:
            dataset_start = offset
            break
        
        # Skip this tag
        offset += 4  # group + element
        vr = data[offset:offset+2].decode('ascii', errors='ignore')
        offset += 2
        
        if vr in ['OB', 'OD', 'OF', 'OL', 'OW', 'SQ', 'UN', 'UR', 'UT']:
            offset += 2
            length = struct.unpack('<I', data[offset:offset+4])[0]
            offset += 4
        else:
            length = struct.unpack('<H', data[offset:offset+2])[0]
            offset += 2
        
        offset += length
    
    print(f"📍 Dataset starts at offset: {dataset_start}")
    
    # Helper function to create DICOM tag
    def create_tag(group, element, vr, value):
        """Create a DICOM data element"""
        tag = struct.pack('<HH', group, element)
        vr_bytes = vr.encode('ascii')
        
        if isinstance(value, str):
            value_bytes = value.encode('ascii')
        elif isinstance(value, int):
            if vr == 'US':
                value_bytes = struct.pack('<H', value)
            elif vr == 'UL':
                value_bytes = struct.pack('<I', value)
            elif vr == 'SS':
                value_bytes = struct.pack('<h', value)
            elif vr == 'SL':
                value_bytes = struct.pack('<i', value)
            else:
                value_bytes = value.encode('ascii')
        else:
            value_bytes = value
        
        length = len(value_bytes)
        
        # Explicit VR
        if vr in ['OB', 'OD', 'OF', 'OL', 'OW', 'SQ', 'UN', 'UR', 'UT']:
            length_bytes = struct.pack('<HI', 0, length)
        else:
            length_bytes = struct.pack('<H', length)
        
        return tag + vr_bytes + length_bytes + value_bytes
    
    # Create required tags
    now = datetime.now()
    study_date = now.strftime('%Y%m%d')
    study_time = now.strftime('%H%M%S.%f')
    
    # Generate UIDs
    study_uid = '1.2.826.0.1.3680043.8.498.' + ''.join(str(ord(c)) for c in str(uuid.uuid4()))[:20]
    series_uid = '1.2.826.0.1.3680043.8.498.' + ''.join(str(ord(c)) for c in str(uuid.uuid4()))[:20]
    sop_instance_uid = '1.2.826.0.1.3680043.8.498.' + ''.join(str(ord(c)) for c in str(uuid.uuid4()))[:20]
    
    print(f"\n➕ Adding required tags:\n")
    
    new_tags = b''
    
    # 0008,0020 - StudyDate
    new_tags += create_tag(0x0008, 0x0020, 'DA', study_date)
    print(f"✅ StudyDate (0008,0020): {study_date}")
    
    # 0008,0030 - StudyTime
    new_tags += create_tag(0x0008, 0x0030, 'TM', study_time)
    print(f"✅ StudyTime (0008,0030): {study_time}")
    
    # 0008,0016 - SOPClassUID (Secondary Capture Image Storage)
    sop_class = '1.2.840.10008.5.1.4.1.1.7'  # Secondary Capture Image Storage
    new_tags += create_tag(0x0008, 0x0016, 'UI', sop_class)
    print(f"✅ SOPClassUID (0008,0016): {sop_class}")
    
    # 0008,0018 - SOPInstanceUID
    new_tags += create_tag(0x0008, 0x0018, 'UI', sop_instance_uid)
    print(f"✅ SOPInstanceUID (0008,0018): {sop_instance_uid[:50]}...")
    
    # 0010,0010 - PatientName
    patient_name = 'ANONYMOUS^PATIENT'
    new_tags += create_tag(0x0010, 0x0010, 'PN', patient_name)
    print(f"✅ PatientName (0010,0010): {patient_name}")
    
    # 0010,0020 - PatientID
    patient_id = 'PAT' + now.strftime('%Y%m%d%H%M%S')
    new_tags += create_tag(0x0010, 0x0020, 'LO', patient_id)
    print(f"✅ PatientID (0010,0020): {patient_id}")
    
    # 0020,000D - StudyInstanceUID
    new_tags += create_tag(0x0020, 0x000D, 'UI', study_uid)
    print(f"✅ StudyInstanceUID (0020,000D): {study_uid[:50]}...")
    
    # 0020,000E - SeriesInstanceUID
    new_tags += create_tag(0x0020, 0x000E, 'UI', series_uid)
    print(f"✅ SeriesInstanceUID (0020,000E): {series_uid[:50]}...")
    
    # Combine: preamble + DICM + File Meta + New Tags + Rest of dataset
    new_data = data[:dataset_start] + new_tags + data[dataset_start:]
    
    # Write output file
    with open(output_path, 'wb') as f:
        f.write(new_data)
    
    print(f"\n✅ Output file created: {output_path}")
    print(f"📊 Original size: {len(data)} bytes")
    print(f"📊 New size: {len(new_data)} bytes")
    print(f"📊 Added: {len(new_data) - len(data)} bytes")

if __name__ == '__main__':
    input_path = sys.argv[1] if len(sys.argv) > 1 else 'C:/Users/Dell/OneDrive/Documents/Hackathon/0171021638f9272a34a41feb84ed47a0.dicom'
    output_path = sys.argv[2] if len(sys.argv) > 2 else 'C:/Users/Dell/OneDrive/Documents/Hackathon/0171021638f9272a34a41feb84ed47a0_fixed.dicom'
    
    add_required_tags_to_dicom(input_path, output_path)
