---
{
  "id": "file_h69k1ki4",
  "filetype": "document",
  "filename": "RAG2_Specification_v2.1",
  "created_at": "2026-04-07T15:12:02.968Z",
  "updated_at": "2026-04-07T15:12:02.968Z",
  "meta": {
    "location": "/",
    "tags": [],
    "categories": [],
    "description": "",
    "source": "markdown"
  }
}
---
# RAG2 — Kỹ Thuật Đặc Tả Chi Tiết
## CXR-Agent: Hệ Thống Sinh Báo Cáo X-Quang Ngực Tự Động

**Phiên bản:** 2.1  
**Chuẩn báo cáo PRIMARY:** Bộ Y tế Việt Nam (Thông tư 43/2013/TT-BYT + Hướng dẫn QTKT CĐHA 2014)  
**Chuẩn báo cáo REFERENCE:** ACR (American College of Radiology) — dùng cho thuật ngữ kỹ thuật  
**Ngôn ngữ output:** Song ngữ Việt (primary) + Anh (secondary)  
**Ngày:** 2026-04

---

## Mục Lục

1. Vị Trí RAG2 trong Pipeline Tổng Thể
2. Input: Doctor-Revised JSON (v2.0)
3. Knowledge Base RAG2 — Cấu Trúc & Nội Dung
4. Chiến Lược Retrieval
5. Prompt Engineering (Groq Llama 3.3 70B)
6. Output JSON Schema — RAG2 Response
7. Cấu Trúc Báo Cáo Chuẩn BYT (Song Ngữ)
8. Metrics Đánh Giá Chất Lượng
9. Ví Dụ End-to-End Hoàn Chỉnh
10. Tài Liệu Tham Khảo

---

## 1. Vị Trí RAG2 trong Pipeline Tổng Thể

```
YOLO JSON output
      ↓
RAG1  →  findings_draft (per detection, JSON có cấu trúc)
      ↓
Bác sĩ chỉnh sửa trên OHIF Viewer
      ↓  ← Doctor-Revised JSON (Section 2 — schema đầy đủ bên dưới)
RAG2  →  Báo cáo nháp song ngữ (Việt primary / Anh secondary)
      ↓
Bác sĩ duyệt lần cuối → ký → xuất PDF / Word / EMR
```

**Nhiệm vụ RAG2 — đúng phạm vi:**

| Làm | Không làm |
|---|---|
| Tổng hợp findings thành báo cáo nhất quán | Phát hiện thêm tổn thương mới |
| Áp dụng chuẩn ngôn ngữ BYT + RadLex | Đưa ra chẩn đoán cuối cùng |
| Sinh song ngữ cùng nội dung lâm sàng | Thay thế chữ ký bác sĩ |
| Đề xuất ICD-10 khi có icd10_confirmed | Thêm ICD-10 ngoài danh sách confirmed |
| Gán nhãn critical flag trong output | Ra quyết định điều trị |

---

## 2. Input: Doctor-Revised JSON (v2.0)

Schema chuẩn được truyền từ OHIF Viewer vào RAG2 sau khi bác sĩ hoàn tất chỉnh sửa.

```jsonc
{
  // ── Định danh ──────────────────────────────────────────────────────
  "query_id"    : "f47ac10b-58cc-4372-a567-0e02b2c3d479",   // UUID v4
  "study_id"    : "1.2.840.10008.5.1.4.1.1.2.20260407.001", // DICOM Study UID
  "image_id"    : "1.2.840.10008.5.1.4.1.1.2.20260407.002", // DICOM SOP UID
  "revision_id" : "a1b2c3d4-e5f6-7890-abcd-ef1234567890",   // UUID mới khi bác sĩ lưu
  "revised_at"  : "2026-04-07T10:30:00+07:00",              // ISO8601 + timezone VN
  "revised_by"  : "DR-NGUYEN-VAN-A",                        // mã định danh bác sĩ

  // ── Kỹ thuật chụp ─────────────────────────────────────────────────
  "technique": {
    "view"         : "PA",          // PA | AP | Lateral | Oblique
    "position"     : "erect",       // erect | supine | decubitus_right | decubitus_left
    "image_quality": "adequate",    // adequate | suboptimal | poor
    "quality_notes": null           // string mô tả nếu suboptimal/poor, null nếu adequate
    // Ví dụ quality_notes: "Xoay nhẹ sang phải. Hít thở chưa đủ sâu."
  },

  // ── Danh sách findings đã bác sĩ xác nhận ─────────────────────────
  // ĐÂY LÀ NGUỒN SỰ THẬT DUY NHẤT (single source of truth) cho RAG2
  // Chỉ chứa findings được giữ lại — findings bác sĩ xoá KHÔNG có ở đây
  "confirmed_findings": [
    {
      // -- Định danh detection --
      "det_id"   : 0,
      "class_id" : 10,
      "class_name": "Pleural Effusion",

      // -- Nguồn gốc (bắt buộc — RAG2 dùng để kiểm soát ngôn ngữ) --
      "source": "ai_confirmed",
      // Enum:
      //   ai_confirmed  = YOLO phát hiện, bác sĩ đồng ý không chỉnh sửa
      //   ai_modified   = YOLO phát hiện, bác sĩ chỉnh sửa bbox/severity/laterality
      //   doctor_added  = YOLO bỏ sót, bác sĩ vẽ thêm thủ công

      // -- Đặc điểm lâm sàng (bác sĩ xác nhận) --
      "laterality"    : "Right",     // Left | Right | Bilateral | Central | N/A
      "severity"      : "moderate",  // mild | moderate | severe
      "severity_source": "doctor",   // doctor | ai_agreed | ai_suggested

      // -- Bounding box sau chỉnh sửa (pixel tuyệt đối, 1024×1024) --
      "bbox_xyxy" : [600, 700, 950, 980],
      "bbox_norm" : [0.586, 0.684, 0.928, 0.957],

      // -- Ghi chú bác sĩ (KEY FIELD — RAG2 ưu tiên cao nhất) --
      // Viết tiếng Việt thuật ngữ y khoa chuẩn
      "doctor_note": "Tràn dịch màng phổi phải mức độ vừa, góc sườn hoành phải tù rõ.",

      // -- Kế thừa từ RAG1 --
      "rag1_impression_accepted" : true,
      "rag1_impression_override" : null,
      // Nếu accepted=false, override phải có nội dung
      // Nếu accepted=true, override=null → dùng rag1 impression gốc

      // -- Đo lường bác sĩ thực hiện trên OHIF (tất cả optional) --
      "measurements": {
        "max_depth_mm" : 45,    // Chiều sâu tràn dịch (Pleural Effusion)
        "ctr"          : null,  // Cardiothoracic Ratio (Cardiomegaly)
        "diameter_mm"  : null,  // Đường kính nốt/khối (Nodule/Mass)
        "length_mm"    : null,  // Chiều dài tổn thương
        "area_cm2"     : null   // Diện tích (ít dùng trên CXR)
      },

      // -- ICD-10 theo bảng mã BYT Việt Nam --
      "icd10_suggested": "J90",  // Từ RAG1
      "icd10_confirmed": "J90",  // Bác sĩ xác nhận; null nếu không xác nhận

      // -- Flag nguy cấp --
      "critical_flag": false
      // true khi: tension pneumothorax, massive effusion, ARDS pattern
    },
    {
      "det_id"         : 1,
      "class_id"       : 3,
      "class_name"     : "Cardiomegaly",
      "source"         : "ai_modified",
      "laterality"     : "Central",
      "severity"       : "mild",
      "severity_source": "doctor",
      "bbox_xyxy"      : [380, 290, 680, 650],
      "bbox_norm"      : [0.371, 0.283, 0.664, 0.635],
      "doctor_note"    : "Bóng tim to nhẹ, CTR đo được khoảng 0,52.",
      "rag1_impression_accepted": false,
      "rag1_impression_override": "Bóng tim to nhẹ, chỉ số tim/lồng ngực (CTR) khoảng 0,52.",
      "measurements": {
        "ctr"          : 0.52,
        "max_depth_mm" : null,
        "diameter_mm"  : null,
        "length_mm"    : null,
        "area_cm2"     : null
      },
      "icd10_suggested": "I51.7",
      "icd10_confirmed": "I51.7",
      "critical_flag"  : false
    },
    {
      "det_id"         : 2,
      "class_id"       : 4,
      "class_name"     : "Consolidation",
      "source"         : "doctor_added",  // YOLO bỏ sót, bác sĩ thêm
      "laterality"     : "Right",
      "severity"       : "moderate",
      "severity_source": "doctor",
      "bbox_xyxy"      : [600, 500, 950, 700],
      "bbox_norm"      : [0.586, 0.488, 0.928, 0.684],
      "doctor_note"    : "Đám mờ đồng nhất thùy dưới phổi phải kèm dấu hiệu khí phế quản đồ.",
      "rag1_impression_accepted": false,
      "rag1_impression_override": "Đám mờ đồng nhất thùy dưới phổi phải có dấu hiệu khí phế quản đồ.",
      "measurements": {
        "length_mm"    : 80,
        "ctr"          : null,
        "diameter_mm"  : null,
        "max_depth_mm" : null,
        "area_cm2"     : null
      },
      "icd10_suggested": "J18.9",
      "icd10_confirmed": "J18.9",
      "critical_flag"  : false
    }
  ],

  // ── Cấu trúc bình thường (bác sĩ xác nhận không có tổn thương) ────
  "normal_structures": ["Aorta", "Bones", "Soft tissue", "Trachea"],

  // ── Đánh giá tổng thể của bác sĩ ─────────────────────────────────
  "doctor_global_assessment": {
    "overall_severity"      : "moderate",
    "requires_urgent_action": false,
    "comparison_available"  : false,   // true nếu prior_study_id có giá trị
    "comparison_notes"      : null,    // string nếu comparison_available=true
    "free_text_summary"     : "Tràn dịch màng phổi phải vừa kết hợp đám mờ thùy dưới phải, nghi viêm phổi. Tim to nhẹ."
  },

  // ── Ngữ cảnh bệnh nhân ───────────────────────────────────────────
  "patient_context": {
    "age"           : 65,
    "sex"           : "M",          // M | F | unknown
    "clinical_notes": "Sốt 38,5°C, ho có đờm 5 ngày. Tiền sử tăng huyết áp.",
    "prior_study_id": null          // DICOM Study UID nếu có phim cũ để so sánh
  },

  // ── Cấu hình RAG2 ────────────────────────────────────────────────
  "rag2_config": {
    "mode"                  : "full_report",  // full_report | impression_only | structured_json
    "language"              : "vi+en",        // vi | en | vi+en
    "report_standard"       : "BYT",          // BYT | ACR | BYT_ACR
    "top_k"                 : 5,              // số chunk retrieval / query
    "include_icd10"         : true,
    "include_recommendation": true
  }
}
```

### 2.1 Priority Logic — RAG2 Dùng Text Nào?

RAG2 xác định nội dung mô tả cho mỗi finding theo thứ tự ưu tiên sau:

```
Ưu tiên 1 (cao nhất): doctor_note
  → Bác sĩ viết tay trực tiếp, luôn dùng nếu có

Ưu tiên 2: rag1_impression_override
  → Bác sĩ viết lại (khi rag1_impression_accepted = false)

Ưu tiên 3: rag1_impression gốc (từ RAG1 response)
  → Dùng khi rag1_impression_accepted = true

Ưu tiên 4 (thấp nhất): class_name + severity + laterality
  → Fallback khi không có text nào — RAG2 tự sinh từ metadata
```

### 2.2 Quy Tắc Xử Lý `source` Field

| source | Cách RAG2 xử lý |
|---|---|
| `ai_confirmed` | Viết bình thường, không ghi chú nguồn |
| `ai_modified` | Dùng giá trị bác sĩ đã chỉnh, không ghi chú |
| `doctor_added` | Viết bình thường — **KHÔNG** đề cập "AI không phát hiện" |

---

## 3. Knowledge Base RAG2 — Cấu Trúc & Nội Dung

RAG1 KB chứa tri thức về **từng tổn thương đơn lẻ** (định nghĩa, đặc điểm X-quang, phân loại mức độ).  
RAG2 KB chứa tri thức về **cách viết báo cáo tổng hợp** theo chuẩn BYT.

```
RAG2_KB/
├── L1_mau_bao_cao/          # Mẫu báo cáo hoàn chỉnh theo nhóm bệnh lý
├── L2_ngon_ngu_chuan/       # Chuẩn ngôn ngữ BYT + RadLex song ngữ
└── L3_fewshot_pairs/        # Cặp (Doctor-Revised JSON → báo cáo đã ký)
```

### 3.1 Layer 1 — Mẫu Báo Cáo Theo Nhóm Bệnh Lý

Mỗi nhóm có 3 mức: nhẹ (mild) / vừa (moderate) / nặng (severe).  
Định dạng: song ngữ Việt (primary) + Anh (secondary) trong cùng file.

---

**NHÓM 1: X-QUANG NGỰC BÌNH THƯỜNG**

```
[VI — PRIMARY]
KỸ THUẬT: Chụp X-quang ngực thẳng (PA) tư thế đứng. Hít thở đầy đủ. Không có nhiễu ảnh.
NHẬN XÉT:
  Tim & Trung thất: Bóng tim kích thước bình thường, chỉ số tim/lồng ngực < 0,5.
                    Trung thất không có bất thường. Khí quản ở đường giữa.
  Phổi:             Nhu mô phổi hai bên thông thoáng, không có đám mờ, nốt mờ hay khối mờ.
                    Mạch máu phổi phân bố bình thường.
  Màng phổi:        Không có tràn dịch màng phổi. Không có tràn khí màng phổi.
                    Hai góc sườn hoành tự do, thành tù sắc.
  Xương & Mô mềm:  Các thành phần xương nhìn thấy còn nguyên vẹn.
                    Không có bất thường mô mềm.
KẾT LUẬN: Không thấy tổn thương tim phổi cấp tính trên phim chụp này.
ĐỀ NGHỊ: Theo dõi định kỳ theo chỉ định lâm sàng.

[EN — SECONDARY]
TECHNIQUE: PA chest radiograph, erect position. Adequate inspiratory effort.
FINDINGS:
  Cardiac & Mediastinum: Heart size normal (CTR < 0.5). Mediastinum unremarkable. Trachea midline.
  Lungs: Lungs clear bilaterally. No focal consolidation, nodule, or mass.
  Pleura: No pleural effusion. No pneumothorax. Costophrenic angles sharp bilaterally.
  Bones & Soft Tissue: No acute osseous abnormality.
IMPRESSION: No acute cardiopulmonary abnormality.
```

---

**NHÓM 2: VIÊM PHỔI + TRÀN DỊCH MÀNG PHỔI (PARAPNEUMONIC)**

```
[VI — PRIMARY — Mức độ vừa]
KỸ THUẬT: Chụp X-quang ngực thẳng (PA) tư thế đứng. Chất lượng phim đạt yêu cầu.
NHẬN XÉT:
  Tim & Trung thất: Bóng tim [bình thường / to nhẹ, CTR ~X,XX].
                    Trung thất không có bất thường rõ.
  Phổi:             Đám mờ đồng nhất [thùy dưới / phân thùy] phổi [Phải/Trái/Hai bên]
                    kèm dấu hiệu khí phế quản đồ, phù hợp với đông đặc phổi.
                    [Phổi bên đối diện/Phổi còn lại thông thoáng.]
  Màng phổi:        Tràn dịch màng phổi [Phải/Trái] mức độ [nhẹ/vừa/nhiều],
                    góc sườn hoành [Phải/Trái] tù.
                    [Không có tràn dịch bên đối diện.]
                    Không có tràn khí màng phổi.
  Xương & Mô mềm:  Không có bất thường xương cấp tính.
KẾT LUẬN:
  1. Đông đặc phổi [thùy dưới Phải/Trái] — phù hợp với viêm phổi trong
     bối cảnh lâm sàng tương ứng.
  2. Tràn dịch màng phổi [Phải/Trái] kèm theo (parapneumonic) mức độ [nhẹ/vừa/nhiều].
  [3. Tim to nhẹ (CTR ~X,XX) — nếu có Cardiomegaly kèm.]
ĐỀ NGHỊ: Đối chiếu lâm sàng với sốt, CRP, cấy đờm.
          Chụp X-quang ngực kiểm tra sau 4–6 tuần điều trị kháng sinh.
ICD-10: J18.9 (Viêm phổi, không đặc hiệu), J90 (Tràn dịch màng phổi)

[EN — SECONDARY]
TECHNIQUE: PA chest radiograph, erect position.
FINDINGS:
  Cardiac & Mediastinum: [Normal cardiac silhouette / Mildly enlarged, CTR ~X.XX].
  Lungs: Homogeneous airspace consolidation in the [right/left] [lower lobe/segment]
         with visible air bronchograms.
  Pleura: [Right/Left] pleural effusion with blunting of the costophrenic angle, [mild/moderate/large].
IMPRESSION:
  1. [Right/Left] [lower lobe] consolidation — consistent with pneumonia.
  2. Associated [right/left] parapneumonic pleural effusion, [severity].
  [3. Mild cardiomegaly (CTR ~X.XX).]
RECOMMENDATION: Clinical correlation. Follow-up CXR 4–6 weeks post-treatment.
ICD-10: J18.9, J90
```

---

**NHÓM 3: SUY TIM (CARDIOMEGALY + TRÀN DỊCH HAI BÊN)**

```
[VI — PRIMARY]
NHẬN XÉT:
  Tim & Trung thất: Bóng tim to, chỉ số tim/lồng ngực (CTR) khoảng X,XX.
                    Cung động mạch phổi nổi. [Phân bố lại mạch máu phổi ra vùng đỉnh — nếu có.]
  Phổi:             Tăng mạch máu phổi [và/hoặc] mờ lan tỏa vùng quanh rốn phổi,
                    phù hợp với phù phổi do tim. [Đường Kerley B ở ngoại vi — nếu thấy.]
  Màng phổi:        Tràn dịch màng phổi hai bên [Phải > Trái / đối xứng].
                    [Không có tràn khí màng phổi.]
KẾT LUẬN:
  1. Tim to (CTR ~X,XX).
  2. Hình ảnh phù hợp với suy tim / tăng áp tĩnh mạch phổi.
  3. Tràn dịch màng phổi hai bên [Phải nhiều hơn / đối xứng].
ĐỀ NGHỊ: Siêu âm tim nếu chưa có kết quả gần đây.
          Đối chiếu BNP/NT-proBNP.
ICD-10: I50.9 (Suy tim, không đặc hiệu), J90 (Tràn dịch màng phổi)
```

---

**NHÓM 4: BỆNH PHỔI KẼ (ILD) + XƠ PHỔI**

```
[VI — PRIMARY — Mức độ vừa]
NHẬN XÉT:
  Phổi: Đám mờ dạng lưới hai bên [vùng dưới / toàn bộ], phù hợp với hình ảnh bệnh phổi kẽ.
        [Đám mờ kính mờ (GGO) lan tỏa kèm theo — nếu có.]
        [Thay đổi dạng lưới thô ở ngoại vi gợi ý thay đổi xơ hóa — nếu có Pulmonary fibrosis.]
        [Thể tích phổi thu nhỏ nhẹ.]
  Màng phổi: Không có tràn dịch màng phổi đáng kể.
  Tim: [Bóng tim bình thường / To nhẹ].
KẾT LUẬN:
  1. Hình ảnh bệnh phổi kẽ hai bên, [phân bố vùng dưới / lan tỏa] ưu thế.
  [2. Thay đổi phù hợp xơ phổi — nếu có Pulmonary fibrosis.]
ĐỀ NGHỊ: Chụp CT ngực phân giải cao (HRCT) để đánh giá chi tiết hình ảnh bệnh phổi kẽ.
ICD-10: J84.9 (Bệnh phổi kẽ, không đặc hiệu), J84.10 (Xơ phổi vô căn)
```

---

**NHÓM 5: TRÀN KHÍ MÀNG PHỔI**

```
[VI — PRIMARY]
NHẬN XÉT:
  Phổi: Đường màng phổi thành [Phải/Trái] ở vùng [trên/giữa], vắng mặt bóng mạch phổi
        phía ngoài đường này, phù hợp với tràn khí màng phổi.
        Ước tính kích thước: [nhỏ <2cm / vừa 2–4cm / lớn >4cm] theo tiêu chí BTS 2023.
        [NGHIÊM TRỌNG: Trung thất lệch sang bên đối diện, khí quản lệch —
        gợi ý tràn khí màng phổi áp lực (tension pneumothorax).]
  Phổi đối diện: Thông thoáng.
KẾT LUẬN:
  1. Tràn khí màng phổi [Phải/Trái], mức độ [nhỏ/vừa/lớn].
  [2. Hình ảnh gợi ý tràn khí áp lực — CẦN XỬ TRÍ NGAY.]
ĐỀ NGHỊ:
  [Nhỏ]: Theo dõi lâm sàng, chụp lại sau 4–6 giờ.
  [Vừa/Lớn]: Hội chẩn can thiệp dẫn lưu màng phổi.
  [Áp lực]: CẦN XỬ TRÍ NGAY — dẫn lưu khẩn cấp.
ICD-10: J93.9 (Tràn khí màng phổi), J93.0 (Tràn khí áp lực)
```

---

**NHÓM 6: NỐT / KHỐI MỜ PHỔI**

```
[VI — PRIMARY]
NHẬN XÉT:
  Phổi: Nốt mờ [đơn độc / nhiều nốt] [thùy trên/dưới phổi Phải/Trái],
        kích thước khoảng X mm. Bờ [đều, rõ / không đều / tua gai].
        [Có/Không] có vôi hóa. Không có tràn dịch màng phổi kèm theo.
KẾT LUẬN:
  1. Nốt mờ phổi [Phải/Trái] kích thước ~X mm — [bờ đều, tính chất lành tính /
     bờ tua gai, cần loại trừ ác tính / đặc điểm chưa xác định].
ĐỀ NGHỊ (theo tiêu chí Fleischner Society 2017 và hướng dẫn BYT):
  < 6mm, nguy cơ thấp: Không cần theo dõi thường quy.
  6–8mm: Chụp CT ngực sau 6–12 tháng.
  > 8mm hoặc bờ tua gai: Chụp CT ngực sau 3 tháng ± PET-CT.
ICD-10: R91.8 (Nốt mờ phổi)
```

---

### 3.2 Layer 2 — Chuẩn Ngôn Ngữ BYT + RadLex Song Ngữ

**Bảng thuật ngữ bắt buộc (BYT 2014 + RSNA RadLex):**

```
LOẠI ĐÁM MỜ / OPACITY TYPE
─────────────────────────────────────────────────────────────────────
Tiếng Việt (BYT)                    | English (RadLex)
────────────────────────────────────|────────────────────────────────
Đám mờ đồng nhất / Đông đặc phổi   | Consolidation / Airspace opacity
Đám mờ dạng kính mờ                | Ground-glass opacity (GGO)
Đám mờ dạng lưới                   | Reticular opacity
Đám mờ dạng nốt                    | Nodular opacity
Đám mờ kẽ                          | Interstitial opacity
Đám mờ vùng quanh rốn phổi         | Perihilar opacity / haziness
Thâm nhiễm phổi                    | Pulmonary infiltrate

PHÂN BỐ / DISTRIBUTION
─────────────────────────────────────────────────────────────────────
Một bên / Hai bên                   | Unilateral / Bilateral
Phổi Phải / Phổi Trái               | Right lung / Left lung
Vùng trên / giữa / dưới             | Upper / mid / lower zone
Thùy trên / giữa / dưới             | Upper / middle / lower lobe
Phân thùy / Dưới phân thùy          | Segmental / Subsegmental
Ngoại vi / Trung tâm                | Peripheral / Central
Dưới màng phổi                      | Subpleural
Quanh phế quản                      | Peribronchial

HÌNH THÁI / MORPHOLOGY
─────────────────────────────────────────────────────────────────────
Bờ đều, rõ                          | Well-defined, smooth margin
Bờ không đều                        | Irregular margin
Bờ tua gai                          | Spiculated margin
Đồng nhất                           | Homogeneous
Không đồng nhất                     | Heterogeneous
Có vôi hóa                          | Calcification present
Dấu hiệu khí phế quản đồ           | Air bronchogram sign
Dấu hiệu mức nước khí               | Air-fluid level / Meniscus sign

TIM-MẠCH / CARDIAC
─────────────────────────────────────────────────────────────────────
Bóng tim                            | Cardiac silhouette
Chỉ số tim/lồng ngực (CTR)          | Cardiothoracic ratio (CTR)
Tim to nhẹ / vừa / nhiều            | Mild / moderate / marked cardiomegaly
Trung thất dãn rộng                  | Mediastinal widening
Phân bố lại mạch máu phổi           | Vascular redistribution
Cung động mạch phổi nổi             | Prominent pulmonary artery
Đường Kerley B                      | Kerley B lines

GIẢI PHẪU LIÊN QUAN / ANATOMY
─────────────────────────────────────────────────────────────────────
Khí quản                            | Trachea
Rốn phổi                            | Hilum / Hila
Cơ hoành                            | Diaphragm
Góc sườn hoành                      | Costophrenic angle
Góc sườn hoành tù rõ               | Blunted costophrenic angle
Khoang liên sườn                    | Intercostal space
Xương sườn                          | Ribs / Costae
Xương đòn                           | Clavicle
Cột sống                            | Vertebral column / Spine

MÀNG PHỔI / PLEURA
─────────────────────────────────────────────────────────────────────
Tràn dịch màng phổi [mức độ]        | Pleural effusion [mild/mod/large]
Tràn khí màng phổi                  | Pneumothorax
Tràn khí áp lực                    | Tension pneumothorax
Dày màng phổi                       | Pleural thickening
Đường màng phổi tạng               | Visceral pleural line
```

**Quy tắc viết NHẬN XÉT (BYT chuẩn):**

```
1. Thứ tự mô tả bắt buộc: Tim & Trung thất → Phổi → Màng phổi → Xương & Mô mềm
2. Mỗi cấu trúc bình thường vẫn phải được đề cập ngắn gọn (không bỏ qua)
3. Mô tả tổn thương theo trình tự: vị trí → hình thái → kích thước → đặc điểm kèm theo
4. Dùng từ "phù hợp với" thay vì chẩn đoán trực tiếp
   ĐÚNG: "Đám mờ đồng nhất thùy dưới phổi phải phù hợp với đông đặc phổi."
   SAI: "Bệnh nhân bị viêm phổi."
5. Ghi measurement khi có: "CTR khoảng 0,52", "nốt mờ kích thước ~12mm"
6. Dùng dấu phẩy thập phân theo chuẩn Việt Nam: 0,52 (không phải 0.52)
```

**Quy tắc viết KẾT LUẬN (BYT chuẩn):**

```
1. Tối đa 5 dòng (BYT) — linh hoạt hơn ACR (3 dòng)
2. Thứ tự: tổn thương nguy hiểm nhất → ít nguy hiểm hơn
3. Mỗi dòng đánh số thứ tự: "1. ...", "2. ...", "3. ..."
4. Nếu bình thường: "Không thấy tổn thương tim phổi cấp tính trên phim chụp này."
5. KHÔNG lặp lại chi tiết đã có trong Nhận xét
6. KHÔNG dùng ngôn ngữ không chắc chắn nếu không có lý do
   CÓ LÝ DO: "Không thể loại trừ X trên phim thẳng, cần CT bổ sung."
   KHÔNG CÓ LÝ DO: "Có thể có X." → Không chấp nhận
```

**Quy tắc viết ĐỀ NGHỊ (BYT):**

```
Viết khi:
  ✓ Nốt/khối phổi → áp dụng Fleischner 2017 + hướng dẫn BYT
  ✓ Bệnh phổi kẽ → CT ngực phân giải cao (HRCT)
  ✓ Viêm phổi → X-quang kiểm tra sau 4–6 tuần
  ✓ Tim to → siêu âm tim nếu chưa có
  ✓ Critical finding → ghi rõ mức độ khẩn

Không viết khi:
  ✗ X-quang bình thường
  ✗ Tổn thương mạn tính đã biết, ổn định
  ✗ rag2_config.include_recommendation = false
  
Khung thời gian cụ thể: "4–6 tuần", "3 tháng", "6–12 tháng"
Không dùng: "sớm", "khi cần", "theo dõi tiếp"
```

### 3.3 Layer 3 — Few-Shot Pairs (Cặp Mẫu Đã Bác Sĩ Ký)

Tối thiểu **50 cặp/nhóm bệnh lý**, đa dạng severity, nguồn từ:
- MIMIC-CXR (de-identified) — Johnson et al., Scientific Data 2019
- VinDr-CXR reports được bác sĩ phê duyệt — Nguyen et al., Scientific Data 2022
- Báo cáo nội bộ bệnh viện đối tác (ẩn danh hóa theo Nghị định 13/2023/NĐ-CP)

**Metadata bắt buộc cho mỗi few-shot pair:**
```json
{
  "pair_id"         : "FS_GRP2_MOD_001",
  "pathology_group" : "pneumonia_effusion",
  "severity"        : "moderate",
  "patient_profile" : "elderly_male",
  "source"          : "MIMIC-CXR-deidentified",
  "reviewed_by"     : "DR-SPECIALIST-CXR",
  "review_date"     : "2025-01-15",
  "language"        : "vi+en"
}
```

---

## 4. Chiến Lược Retrieval

### 4.1 Multi-Query Parallel Strategy

RAG2 sinh **3 query song song** để tối đa hóa recall:

```python
def build_rag2_queries(revised_json: dict) -> list[str]:
    findings   = revised_json["confirmed_findings"]
    patient    = revised_json["patient_context"]
    
    class_names  = [f["class_name"] for f in findings]
    severities   = list(set(f["severity"] for f in findings))
    lateralities = list(set(f["laterality"] for f in findings if f["laterality"] != "N/A"))

    # Query 1: Pattern matching — tìm mẫu báo cáo theo tổ hợp bệnh lý
    q1 = f"mau bao cao xquang {' '.join(class_names)} {' '.join(lateralities)}"

    # Query 2: Severity + combination — tìm mẫu cùng mức độ
    q2 = f"bao cao chan doan hinh anh {' '.join(class_names)} {' '.join(severities)} BYT"

    # Query 3: Clinical context — tìm few-shot tương tự hồ sơ bệnh nhân
    age_group = "nguoi cao tuoi" if patient.get("age", 0) >= 60 else "nguoi lon"
    sex_str   = "nam" if patient.get("sex") == "M" else "nu"
    q3 = f"vi du bao cao {age_group} {sex_str} {class_names[0] if class_names else ''}"

    return [q1, q2, q3]
```

### 4.2 Chunking Strategy

| Layer | Đơn vị chunk | Overlap | Kích thước |
|---|---|---|---|
| L1 (Templates) | 1 template hoàn chỉnh | 0 | ~600–800 tokens |
| L2 (Language) | 1 bảng thuật ngữ hoặc 1 bộ quy tắc | 50 tokens | 200–400 tokens |
| L3 (Few-shot) | 1 cặp input_summary + báo cáo đầy đủ | 0 | ~800–1200 tokens |

### 4.3 Re-ranking sau Vector Search

```
Score_final = 0.5 × cosine_similarity
            + 0.3 × pathology_match_bonus    # +1.0 nếu class_name khớp chính xác
            + 0.2 × severity_match_bonus     # +0.5 nếu severity khớp
            
Giữ top 3 chunks sau re-ranking → đưa vào prompt
(Tránh context overflow — Llama 3.3 70B context 128k nhưng prompt dài làm giảm quality)
```

---

## 5. Prompt Engineering (Groq Llama 3.3 70B)

### 5.1 System Prompt

```
Bạn là trợ lý chuyên gia X-quang ngực, hỗ trợ bác sĩ soạn báo cáo chính thức.
Báo cáo tuân theo chuẩn Bộ Y tế Việt Nam (Thông tư 43/2013/TT-BYT) với phần tiếng Anh kèm theo.

QUY TẮC TUYỆT ĐỐI:
1. Chỉ mô tả các tổn thương có trong confirmed_findings. KHÔNG thêm tổn thương mới.
2. Kết luận phải tương ứng trực tiếp với Nhận xét — không có thông tin mới trong Kết luận.
3. KHÔNG đưa ra chẩn đoán cuối cùng — chỉ mô tả dấu hiệu X-quang quan sát được.
   SAI: "Bệnh nhân bị viêm phổi."
   ĐÚNG: "Đám mờ đồng nhất phù hợp với đông đặc phổi trong bối cảnh lâm sàng tương ứng."
4. ICD-10 chỉ dùng cho finding có icd10_confirmed != null.
5. doctor_added findings: viết bình thường, KHÔNG đề cập "AI không phát hiện".
6. Ưu tiên nội dung: doctor_note > rag1_impression_override > rag1_impression > metadata.
7. Phần tiếng Việt là PRIMARY — viết trước, đầy đủ nhất.
8. Phần tiếng Anh là SECONDARY — cùng nội dung lâm sàng, dùng thuật ngữ RadLex/ACR.
9. Trả về ĐÚNG định dạng JSON output schema. Không có văn xuôi ngoài JSON.
10. Dùng dấu phẩy thập phân trong tiếng Việt: 0,52 (không phải 0.52).
```

### 5.2 User Prompt Template

```python
def build_rag2_user_prompt(revised_json: dict, retrieved_chunks: list[dict]) -> str:
    findings = revised_json["confirmed_findings"]
    normal   = revised_json.get("normal_structures", [])
    global_a = revised_json["doctor_global_assessment"]
    patient  = revised_json["patient_context"]
    tech     = revised_json["technique"]

    # Serialize findings với priority logic
    findings_prompt = []
    for f in findings:
        # Priority: doctor_note > override > accepted
        description = (
            f.get("doctor_note")
            or f.get("rag1_impression_override")
            or f"{f['class_name']} {f['laterality']} {f['severity']}"
        )
        # Đưa measurements có giá trị vào
        meas = {k: v for k, v in (f.get("measurements") or {}).items() if v is not None}
        findings_prompt.append({
            "label"       : f["class_name"],
            "laterality"  : f["laterality"],
            "severity"    : f["severity"],
            "description" : description,
            "measurements": meas,
            "icd10"       : f.get("icd10_confirmed"),
            "critical"    : f.get("critical_flag", False),
        })

    # Format retrieved chunks
    chunks_text = "\n\n---\n\n".join([
        f"[{c.get('layer','?')} | {c.get('pathology_group','')} | score:{c.get('score',0):.2f}]\n{c['content']}"
        for c in retrieved_chunks
    ])

    return f"""## THÔNG TIN BỆNH NHÂN:
Tuổi: {patient.get('age','không rõ')} | Giới: {patient.get('sex','không rõ')}
Lâm sàng: {patient.get('clinical_notes','Không có thông tin')}
Phim cũ: {patient.get('prior_study_id','Không có')}

## KỸ THUẬT CHỤP:
Tư thế: {tech['view']} {tech['position']} | Chất lượng: {tech['image_quality']}
{f"Ghi chú: {tech['quality_notes']}" if tech.get('quality_notes') else ''}

## FINDINGS ĐÃ BÁC SĨ XÁC NHẬN (nguồn sự thật duy nhất):
{json.dumps(findings_prompt, ensure_ascii=False, indent=2)}

## CẤU TRÚC BÌNH THƯỜNG (bác sĩ xác nhận không có tổn thương):
{', '.join(normal) if normal else 'Không ghi nhận'}

## ĐÁNH GIÁ TỔNG THỂ BÁC SĨ:
Mức độ tổng thể: {global_a['overall_severity']}
Cần xử trí khẩn: {global_a['requires_urgent_action']}
Tóm tắt: {global_a.get('free_text_summary', '')}

## TRI THỨC TRUY XUẤT TỪ KNOWLEDGE BASE:
{chunks_text}

## NHIỆM VỤ:
Sinh báo cáo X-quang ngực hoàn chỉnh song ngữ Việt–Anh theo OUTPUT JSON SCHEMA.
Dùng mẫu báo cáo và bảng thuật ngữ từ tri thức truy xuất làm tham chiếu.
"""
```

---

## 6. Output JSON Schema — RAG2 Response

```jsonc
{
  // ── Echo định danh ──────────────────────────────────────────────────
  "query_id"     : "string — echo từ input",
  "study_id"     : "string — echo từ input",
  "image_id"     : "string — echo từ input",
  "revision_id"  : "string — echo từ input",
  "report_id"    : "uuid-v4 — sinh mới cho báo cáo này",
  "generated_at" : "ISO8601+07:00",

  // ── BÁO CÁO TIẾNG VIỆT (PRIMARY — BYT chuẩn) ──────────────────────
  "report_vi": {
    "ky_thuat"  : "string",
    "nhan_xet"  : {
      "tim_trung_that" : "string",   // Tim & Trung thất
      "phoi"           : "string",   // Phổi
      "mang_phoi"      : "string",   // Màng phổi
      "xuong_mo_mem"   : "string"    // Xương & Mô mềm
    },
    "ket_luan"  : [
      "string",   // 1. Finding nguy hiểm nhất
      "string",   // 2. ...
      "string"    // Tối đa 5 items (BYT cho phép)
    ],
    "de_nghi"   : "string | null",   // null nếu không cần
    "icd10"     : [
      {
        "ma"   : "J18.9",
        "mo_ta": "Viêm phổi, không đặc hiệu"
      }
    ]
  },

  // ── BÁO CÁO TIẾNG ANH (SECONDARY — ACR standard) ───────────────────
  "report_en": {
    "technique"  : "string",
    "findings"   : {
      "cardiac_mediastinum" : "string",
      "lungs"               : "string",
      "pleura"              : "string",
      "bones_soft_tissue"   : "string"
    },
    "impression"     : [
      "string"   // Tối đa 3 items (ACR standard)
    ],
    "recommendation" : "string | null",
    "icd10"          : [
      {
        "code"       : "J18.9",
        "description": "Pneumonia, unspecified"
      }
    ]
  },

  // ── METADATA CHẤT LƯỢNG & AN TOÀN ──────────────────────────────────
  "metadata": {
    "rag_version"           : "2.0",
    "kb_version"            : "RAG2_KB_v1.0",
    "llm_model"             : "llama-3.3-70b-versatile",
    "report_standard"       : "BYT",
    "language"              : "vi+en",
    "chunks_used"           : 3,
    "processing_time_ms"    : 380,

    // Safety fields
    "critical_flags"        : [],      // list det_id có critical_flag=true
    "requires_urgent_review": false,   // true nếu có critical finding
    "confidence_notes"      : [],      // list cảnh báo (low-conf AI detection còn lại)

    // Traceability
    "findings_count_input"  : 3,       // số confirmed_findings nhận vào
    "findings_count_output" : 3        // số findings đã mô tả trong báo cáo (phải = input)
  }
}
```

**Validation rule quan trọng:** `findings_count_output` phải bằng `findings_count_input`.  
Nếu không khớp → pipeline raise error, không xuất báo cáo → bác sĩ phải review thủ công.

---

## 7. Cấu Trúc Báo Cáo Chuẩn BYT (Song Ngữ)

### 7.1 Thứ Tự Section Bắt Buộc

```
TIẾNG VIỆT (PRIMARY)       TIẾNG ANH (SECONDARY)
─────────────────────────────────────────────────────
1. KỸ THUẬT            →   TECHNIQUE
2. NHẬN XÉT            →   FINDINGS
   2a. Tim & Trung thất →     Cardiac & Mediastinum
   2b. Phổi             →     Lungs
   2c. Màng phổi        →     Pleura
   2d. Xương & Mô mềm   →     Bones & Soft Tissue
3. KẾT LUẬN            →   IMPRESSION
4. ĐỀ NGHỊ             →   RECOMMENDATION
5. ICD-10              →   ICD-10
```

### 7.2 Phân Biệt BYT vs ACR (Điểm Khác Nhau Quan Trọng)

| Tiêu chí | BYT (Việt Nam) | ACR (Mỹ) |
|---|---|---|
| Tên section kết luận | KẾT LUẬN | IMPRESSION |
| Số dòng kết luận | ≤ 5 dòng | ≤ 3 dòng |
| Tên section đề nghị | ĐỀ NGHỊ | RECOMMENDATION |
| Measurement số | Dùng dấu phẩy: 0,52 | Dùng dấu chấm: 0.52 |
| ICD-10 version | ICD-10 BYT (có điều chỉnh VN) | ICD-10-CM |
| Bắt buộc ký duyệt | Có (bác sĩ có thẩm quyền) | Có |
| Ghi tên bác sĩ | Bắt buộc theo TT43/2013 | Tuỳ cơ sở |

---

## 8. Metrics Đánh Giá Chất Lượng

### 8.1 Automatic Metrics

| Metric | Mô tả | Ngưỡng mục tiêu |
|---|---|---|
| **BERTScore F1** (multilingual) | Tương đồng ngữ nghĩa với báo cáo reference | ≥ 0.82 |
| **RadGraph F1** | Trùng khớp clinical entities (anatomy + observation + relation) | ≥ 0.65 |
| **CheXBert Label Accuracy** | So sánh 14 labels AI vs ground truth | ≥ 0.80 |
| **Section Completeness** | Tất cả 4 section NHẬN XÉT có mặt và không rỗng | = 1.0 |
| **Findings Coverage** | findings_count_output = findings_count_input | = 1.0 |
| **ICD-10 Precision** | ICD-10 output ⊆ icd10_confirmed input | = 1.0 |
| **Impression Line Count** | Số dòng KẾT LUẬN trong [1, 5] (BYT) | = 1.0 |

### 8.2 Clinical Review — Đánh Giá Mù (100 ca test)

| Tiêu chí | Thang | Mô tả |
|---|---|---|
| **Độ chính xác** | 1–5 | Nội dung có chính xác về mặt lâm sàng không? |
| **Độ đầy đủ** | 1–5 | Có bỏ sót finding quan trọng nào không? |
| **Phù hợp lâm sàng** | 1–5 | Đề nghị có phù hợp không? |
| **Ngôn ngữ tiếng Việt** | 1–5 | Có chuẩn BYT, tự nhiên không? |
| **Ngôn ngữ tiếng Anh** | 1–5 | Có chuẩn RadLex/ACR không? |

**Ngưỡng chấp nhận lâm sàng:** Mean ≥ 4.0/5.0 trên tất cả 5 tiêu chí.

### 8.3 Safety Metrics (Bắt Buộc = 0%)

| Metric | Định nghĩa | Mục tiêu |
|---|---|---|
| **Hallucination Rate** | % báo cáo có finding ngoài confirmed_findings | = 0% |
| **Critical Miss Rate** | % ca critical_flag=true không ghi nhận đúng | = 0% |
| **ICD-10 False Add Rate** | % ICD-10 thêm ngoài icd10_confirmed | = 0% |
| **Findings Coverage Fail** | % ca findings_count_output ≠ findings_count_input | = 0% |

---

## 9. Ví Dụ End-to-End Hoàn Chỉnh

### Input tóm tắt (Doctor-Revised JSON)
```
confirmed_findings:
  [0] Pleural Effusion | Right | moderate | ai_confirmed
      doctor_note: "Tràn dịch màng phổi phải mức độ vừa, góc sườn hoành phải tù rõ."
      measurements: max_depth_mm=45 | icd10_confirmed: J90

  [1] Cardiomegaly | Central | mild | ai_modified
      override: "Bóng tim to nhẹ, CTR khoảng 0,52."
      measurements: ctr=0.52 | icd10_confirmed: I51.7

  [2] Consolidation | Right | moderate | doctor_added
      doctor_note: "Đám mờ đồng nhất thùy dưới phổi phải kèm dấu hiệu khí phế quản đồ."
      measurements: length_mm=80 | icd10_confirmed: J18.9

normal_structures: ["Aorta", "Bones", "Soft tissue", "Trachea"]
patient: 65M, sốt 38,5°C, ho đờm 5 ngày, tiền sử THA
technique: PA, erect, adequate
```

### Retrieved Chunks (top 3 sau re-ranking)
```
[L3 | pneumonia_effusion | score:0.94] Few-shot pair tương tự — báo cáo đã ký
[L1 | pneumonia_effusion_moderate | score:0.88] Mẫu báo cáo Nhóm 2 mức vừa
[L2 | terminology | score:0.71] Bảng thuật ngữ đám mờ + màng phổi
```

### RAG2 Output

```json
{
  "query_id"     : "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "study_id"     : "1.2.840.10008.5.1.4.1.1.2.20260407.001",
  "image_id"     : "1.2.840.10008.5.1.4.1.1.2.20260407.002",
  "revision_id"  : "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "report_id"    : "c9d8e7f6-a5b4-3210-fedc-ba9876543210",
  "generated_at" : "2026-04-07T10:31:22+07:00",

  "report_vi": {
    "ky_thuat": "Chụp X-quang ngực thẳng (PA) tư thế đứng. Hít thở đầy đủ. Chất lượng phim đạt yêu cầu.",
    "nhan_xet": {
      "tim_trung_that": "Bóng tim to nhẹ, chỉ số tim/lồng ngực (CTR) khoảng 0,52. Các đường viền trung thất không có bất thường rõ. Khí quản ở đường giữa.",
      "phoi": "Đám mờ đồng nhất thùy dưới phổi phải kèm dấu hiệu khí phế quản đồ (kích thước khoảng 80mm), phù hợp với đông đặc phổi thùy dưới. Phổi trái thông thoáng. Không thấy nốt mờ hay khối mờ.",
      "mang_phoi": "Tràn dịch màng phổi phải mức độ vừa (chiều sâu ~45mm), góc sườn hoành phải tù rõ. Không có tràn dịch màng phổi bên trái. Không có tràn khí màng phổi.",
      "xuong_mo_mem": "Các thành phần xương nhìn thấy còn nguyên vẹn. Không có bất thường mô mềm cấp tính."
    },
    "ket_luan": [
      "1. Đông đặc phổi thùy dưới phổi phải — phù hợp với viêm phổi trong bối cảnh lâm sàng tương ứng.",
      "2. Tràn dịch màng phổi phải kèm theo (parapneumonic) mức độ vừa.",
      "3. Tim to nhẹ (CTR ~0,52)."
    ],
    "de_nghi": "Đối chiếu lâm sàng với sốt, CRP, cấy đờm. Chụp X-quang ngực kiểm tra sau 4–6 tuần điều trị kháng sinh.",
    "icd10": [
      { "ma": "J18.9", "mo_ta": "Viêm phổi, không đặc hiệu" },
      { "ma": "J90",   "mo_ta": "Tràn dịch màng phổi" },
      { "ma": "I51.7", "mo_ta": "Tim to" }
    ]
  },

  "report_en": {
    "technique": "PA chest radiograph, erect position. Adequate inspiratory effort. No motion artifact.",
    "findings": {
      "cardiac_mediastinum": "Mildly enlarged cardiac silhouette (CTR approximately 0.52). Mediastinal contours are otherwise unremarkable. Trachea is midline.",
      "lungs": "Homogeneous airspace opacity in the right lower lobe (~80mm) with visible air bronchograms, consistent with lobar consolidation. Left lung is clear. No nodule or mass identified.",
      "pleura": "Right pleural effusion with blunting of the right costophrenic angle, moderate in size (estimated depth ~45mm). No left-sided effusion. No pneumothorax.",
      "bones_soft_tissue": "Visible osseous structures are intact. No acute soft tissue abnormality."
    },
    "impression": [
      "1. Right lower lobe consolidation — consistent with pneumonia in appropriate clinical context.",
      "2. Associated right parapneumonic pleural effusion, moderate.",
      "3. Mild cardiomegaly (CTR ~0.52)."
    ],
    "recommendation": "Clinical correlation with fever/CRP/sputum culture. Follow-up chest radiograph recommended 4–6 weeks after antibiotic therapy.",
    "icd10": [
      { "code": "J18.9", "description": "Pneumonia, unspecified" },
      { "code": "J90",   "description": "Pleural effusion, not elsewhere classified" },
      { "code": "I51.7", "description": "Cardiomegaly" }
    ]
  },

  "metadata": {
    "rag_version"           : "2.0",
    "kb_version"            : "RAG2_KB_v1.0",
    "llm_model"             : "llama-3.3-70b-versatile",
    "report_standard"       : "BYT",
    "language"              : "vi+en",
    "chunks_used"           : 3,
    "processing_time_ms"    : 342,
    "critical_flags"        : [],
    "requires_urgent_review": false,
    "confidence_notes"      : [],
    "findings_count_input"  : 3,
    "findings_count_output" : 3
  }
}
```

---

## 10. Tài Liệu Tham Khảo

1. Bộ Y tế Việt Nam, **Thông tư 43/2013/TT-BYT** — Quy định chi tiết phân loại phẫu thuật, thủ thuật và định mức nhân lực trong thực hiện kỹ thuật y tế.
2. Bộ Y tế Việt Nam, **Hướng dẫn Quy trình Kỹ thuật Chẩn đoán Hình ảnh** (2014) — Quyết định 3128/QĐ-BYT.
3. Bộ Y tế Việt Nam, **Nghị định 13/2023/NĐ-CP** — Bảo vệ dữ liệu cá nhân.
4. ACR, **Practice Parameter for Communication of Diagnostic Imaging Findings** (2020).
5. MacMahon et al., **Fleischner Society Guidelines for Pulmonary Nodules** — Radiology 284:228–243, 2017.
6. BTS, **Guidelines for Pleural Disease** — Thorax 78:S1–S42, 2023.
7. RSNA, **RadLex Playbook v2.0** — rsna.org/radlex (40,000+ thuật ngữ X-quang).
8. Jain et al., **RadGraph: Extracting Clinical Entities from Radiology Reports** — NeurIPS 2021.
9. Zhang et al., **BERTScore: Evaluating Text Generation with BERT** — ICLR 2020.
10. Smit et al., **CheXbert: Accurate Radiology Report Labeling using BERT** — EMNLP 2020, pp.1500–1519.
11. Nguyen et al., **VinDr-CXR: An Open Dataset of Chest X-rays with Radiologist Annotations** — Scientific Data 9:429, 2022.
12. Johnson et al., **MIMIC-CXR: A De-identified Database of Chest Radiographs** — Scientific Data 6:317, 2019.
