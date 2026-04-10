# RAG1 Hybrid Evaluation

- Cases: 10
- Output root: `E:\AI_Research\Phenika_Hackathon2026\RAG1_DEV_HANDOFF\evals\20260410_rag1_hybrid_v1`

| sample | study_id | image_id | det_count | overall_final | urgent | expected_combo_flags | final_flag_codes | needs_review | vision_candidates | severity_mismatch | retrieval_gaps | safe_mode | vision_mode |
| --- | --- | --- | ---: | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| dicom_1 | study_dicom_1 | image_dicom_1 | 2 | mild | True | FLAG_CARDIO_AORTIC | FLAG_CARDIO_AORTIC | 0 | 2 | 0 | 0 | True | safe_mode |
| dicom_10 | study_dicom_10 | image_dicom_10 | 5 | mild | False | - | FLAG_LOW_CONF|FLAG_MULTILESION|FLAG_RAPID_GROWTH | 0 | 5 | 0 | 0 | True | safe_mode |
| dicom_2 | study_dicom_2 | image_dicom_2 | 1 | mild | False | - | FLAG_LOW_CONF | 0 | 1 | 0 | 0 | True | safe_mode |
| dicom_3 | study_dicom_3 | image_dicom_3 | 5 | mild | False | - | FLAG_LOW_CONF|FLAG_MULTILESION|FLAG_RAPID_GROWTH | 0 | 4 | 0 | 0 | True | safe_mode |
| dicom_4 | study_dicom_4 | image_dicom_4 | 3 | mild | False | - | FLAG_RAPID_GROWTH | 0 | 3 | 0 | 0 | True | safe_mode |
| dicom_5 | study_dicom_5 | image_dicom_5 | 13 | mild | True | FLAG_CARDIO_AORTIC | FLAG_CARDIO_AORTIC|FLAG_LOW_CONF|FLAG_MULTILESION | 0 | 13 | 0 | 0 | True | safe_mode |
| dicom_6 | study_dicom_6 | image_dicom_6 | 1 | mild | False | - | FLAG_LOW_CONF | 0 | 1 | 0 | 0 | True | safe_mode |
| dicom_7 | study_dicom_7 | image_dicom_7 | 13 | severe | False | - | FLAG_LOW_CONF|FLAG_MULTILESION | 0 | 12 | 0 | 0 | True | safe_mode |
| dicom_8 | study_dicom_8 | image_dicom_8 | 12 | moderate | True | FLAG_CARDIO_AORTIC|FLAG_EFFUSION_CARDIO | FLAG_CARDIO_AORTIC|FLAG_EFFUSION_CARDIO|FLAG_LOW_CONF|FLAG_MULTILESION | 0 | 12 | 0 | 0 | True | safe_mode |
| dicom_9 | study_dicom_9 | image_dicom_9 | 2 | mild | False | - | FLAG_LOW_CONF | 0 | 2 | 0 | 0 | True | safe_mode |
