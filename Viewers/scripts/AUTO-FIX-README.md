# DICOM Auto-Fix Upload System

Tự động kiểm tra và thêm các tags DICOM bắt buộc khi upload file.

## ✨ Tính năng

- ✅ Kiểm tra DICOM file có tất cả tags bắt buộc không
- ✅ Tự động phát hiện và sửa file không hợp lệ
- ✅ Tạo các tags bắt buộc với dữ liệu hợp lý
- ✅ Không ảnh hưởng đến dữ liệu hình ảnh gốc
- ✅ Tương thích với file `.dcm` và `.dicom`

## 📋 Tags được tự động sinh ra

| Tag | Field | Giá trị |
|------|-------|--------|
| 0008,0020 | StudyDate | Ngày hiện tại (YYYYMMDD) |
| 0008,0030 | StudyTime | Giờ hiện tại (HHMMSS.mmm) |
| 0008,0016 | SOPClassUID | Secondary Capture (1.2.840.10008.5.1.4.1.1.7) |
| 0008,0018 | SOPInstanceUID | UID ngẫu nhiên |
| 0010,0010 | PatientName | ANONYMOUS^PATIENT |
| 0010,0020 | PatientID | PAT + timestamp |
| 0020,000D | StudyInstanceUID | UID ngẫu nhiên |
| 0020,000E | SeriesInstanceUID | UID ngẫu nhiên |

## 🚀 Cách sử dụng

### Option 1: Direct Auto-Upload (Khuyến nghị)

```bash
# Tự động kiểm tra -> sửa (nếu cần) -> upload
cd Viewers
node ./scripts/ui-upload-smoke.js "path/to/your/file.dicom"
```

Script sẽ:
1. Kiểm tra file DICOM
2. Nếu thiếu tags → tự động thêm
3. Upload file (gốc hoặc version đã sửa)
4. Hiển thị kết quả upload

### Option 2: Verify Only (Chỉ kiểm tra)

```bash
cd Viewers
node ./scripts/auto-upload-dicom.js "path/to/your/file.dicom" --dry-run
```

### Option 3: Auto-Fix Then Check

```bash
cd Viewers
node ./scripts/auto-upload-dicom.js "path/to/your/file.dicom"
```

Sẽ tạo file mới với suffix `_auto_fixed`:
```
original_file.dicom
  ↓
original_file_auto_fixed.dicom ← Ready to upload
```

## 📝 Ví dụ

### Ví dụ 1: Upload file không hợp lệ

```bash
node ./scripts/ui-upload-smoke.js "C:/data/scan.dicom"
```

Output:
```
🔍 Checking DICOM file: scan.dicom
⚠️  Missing 8 required tags:
   - 0008,0020
   - 0008,0030
   ...

➕ Auto-generating tags...

✅ Fixed DICOM saved to: scan_auto_fixed.dicom
   Original size: 18874882 bytes
   Fixed size: 18875164 bytes
✅ Verification: All required tags present

Before upload instances: 5
[Uploading scan_auto_fixed.dicom...]
After upload instances: 6
✅ Upload UI smoke test passed.
```

### Ví dụ 2: Upload file hợp lệ

```bash
node ./scripts/ui-upload-smoke.js "C:/data/valid_scan.dcm"
```

Output:
```
🔍 Checking DICOM file: valid_scan.dcm
✅ DICOM file is valid (47 tags found)

Before upload instances: 5
[Uploading valid_scan.dcm...]
After upload instances: 6
✅ Upload UI smoke test passed.
```

## 🔍 Chỉ kiểm tra mà không upload

Nếu bạn chỉ muốn kiểm tra file mà không upload:

```bash
cd ..  # Go to Hackathon folder
python3.13 check_dicom.py "your_file.dicom"
```

Output:
```
📄 File size: 18.00 MB (18875152 bytes)
DICOM Prefix check (offset 128): ✅ DICM found
DICOM Preamble (128 zero bytes): ✅ Valid

✅ Found 35 DICOM tags

📌 Required tags status:
✅ 0008,0020 (StudyDate)
✅ 0008,0030 (StudyTime)
... (all check marks)

📊 SUMMARY:
✅ VALID DICOM file with all required tags
```

## 🛠️ Lỏng ghép

Các script tạo ra:

1. **dicom-processor.js** - Thư viện xử lý DICOM
   - `checkDicomTags()` - Kiểm tra tags
   - `fixDicomFile()` - Sửa file
   - `ensureDicomValid()` - Wrapper tự động

2. **ui-upload-smoke.js** (Đã update)
   - Tích hợp auto-check & auto-fix trước upload
   - Sử dụng `ensureDicomValid()` tự động

3. **auto-upload-dicom.js** - Standalone utility
   - Script độc lập để kiểm tra/sửa file

4. **test-processor.js** - Testing utility
   - Kiểm tra processor có hoạt động đúng không

## ⚙️ Cấu hình

Để tùy chỉnh giá trị tags, sửa trong `dicom-processor.js`:

```javascript
// Để đổi SOP Class UID (hiện tại là Secondary Capture)
const sopClassUID = '1.2.840.10008.5.1.4.1.1.7'; // Đổi thành UID khác

// Để đổi PatientName
newTagsBuffer = Buffer.concat([
  newTagsBuffer,
  createTag(0x0010, 0x0010, 'PN', 'CUSTOM^NAME') // Đổi tên
]);
```

## 🐛 Troubleshooting

### File vẫn không upload được

1. Kiểm tra file bằng Python:
```bash
python3.13 check_dicom.py "your_file.dicom"
```

2. Nếu vẫn báo lỗi, file có thể bị hư:
```bash
# Fix bằng Python script
python3.13 fix_dicom.py "original.dcm" "fixed.dcm"
```

### Tags không được thêm đúng

- Xóa file `*_auto_fixed.*` nếu có
- Thử lại: `node scripts/auto-upload-dicom.js`
- Hoặc sử dụng Python script trực tiếp

### Orthanc vẫn báo lỗi

- Kiểm tra Orthanc có đang chạy: `http://localhost:8042`
- Kiểm tra OHIF Viewer có chạy: `http://localhost:3000`
- Xem log: `yarn dev:orthanc` trong terminal

## 📚 Tham khảo

- DICOM Standard: https://www.dicomstandard.org/
- Cornerstone.js: https://cornerstonejs.org/
- OHIF Viewers: https://github.com/OHIF/Viewers
