# Few-Shot Pair 001 — Viêm phổi + Tràn dịch + Tim to nhẹ

## Metadata
- pair_id: FS_GRP2_MOD_001
- pathology_group: pneumonia_effusion
- severity: moderate
- patient_profile: elderly_male
- language: vi+en

## Input Summary (Doctor-Revised JSON)

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

## Output — Báo Cáo Hoàn Chỉnh

### Tiếng Việt (PRIMARY)

KỸ THUẬT: Chụp X-quang ngực thẳng (PA) tư thế đứng. Hít thở đầy đủ. Chất lượng phim đạt yêu cầu.

NHẬN XÉT:
  Tim & Trung thất: Bóng tim to nhẹ, chỉ số tim/lồng ngực (CTR) khoảng 0,52. Các đường viền trung thất không có bất thường rõ. Khí quản ở đường giữa.
  Phổi: Đám mờ đồng nhất thùy dưới phổi phải kèm dấu hiệu khí phế quản đồ (kích thước khoảng 80mm), phù hợp với đông đặc phổi thùy dưới. Phổi trái thông thoáng. Không thấy nốt mờ hay khối mờ.
  Màng phổi: Tràn dịch màng phổi phải mức độ vừa (chiều sâu ~45mm), góc sườn hoành phải tù rõ. Không có tràn dịch màng phổi bên trái. Không có tràn khí màng phổi.
  Xương & Mô mềm: Các thành phần xương nhìn thấy còn nguyên vẹn. Không có bất thường mô mềm cấp tính.

KẾT LUẬN:
  1. Đông đặc phổi thùy dưới phổi phải — phù hợp với viêm phổi trong bối cảnh lâm sàng tương ứng.
  2. Tràn dịch màng phổi phải kèm theo (parapneumonic) mức độ vừa.
  3. Tim to nhẹ (CTR ~0,52).

ĐỀ NGHỊ: Đối chiếu lâm sàng với sốt, CRP, cấy đờm. Chụp X-quang ngực kiểm tra sau 4–6 tuần điều trị kháng sinh.

ICD-10: J18.9 (Viêm phổi, không đặc hiệu), J90 (Tràn dịch màng phổi), I51.7 (Tim to)

### Tiếng Anh (SECONDARY)

TECHNIQUE: PA chest radiograph, erect position. Adequate inspiratory effort. No motion artifact.

FINDINGS:
  Cardiac & Mediastinum: Mildly enlarged cardiac silhouette (CTR approximately 0.52). Mediastinal contours are otherwise unremarkable. Trachea is midline.
  Lungs: Homogeneous airspace opacity in the right lower lobe (~80mm) with visible air bronchograms, consistent with lobar consolidation. Left lung is clear. No nodule or mass identified.
  Pleura: Right pleural effusion with blunting of the right costophrenic angle, moderate in size (estimated depth ~45mm). No left-sided effusion. No pneumothorax.
  Bones & Soft Tissue: Visible osseous structures are intact. No acute soft tissue abnormality.

IMPRESSION:
  1. Right lower lobe consolidation — consistent with pneumonia in appropriate clinical context.
  2. Associated right parapneumonic pleural effusion, moderate.
  3. Mild cardiomegaly (CTR ~0.52).

RECOMMENDATION: Clinical correlation with fever/CRP/sputum culture. Follow-up chest radiograph recommended 4–6 weeks after antibiotic therapy.

ICD-10: J18.9 (Pneumonia, unspecified), J90 (Pleural effusion), I51.7 (Cardiomegaly)
