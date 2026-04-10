# RAG1 Web Handoff

Bo dong goi nay danh cho dev web/backend tich hop nhanh `RAG1` ma khong can mo toan bo repo goc.

## Package nay da bao gom gi

- `backend_api.py`: FastAPI wrapper de FE goi HTTP.
- `rag1_pipeline.py`: CLI chay RAG1 end-to-end.
- `dicom_to_rag1_json.py`: DICOM -> YOLO -> RAG1 input JSON + PNG + crops.
- `rag1/`: logic retrieval, draft generation, quantitative adjudication, final output cho FE.
- `dataRAG1/RAG1_Knowledge_Base_CXR14_v2.pdf`: knowledge base.
- `rag1/chroma_store/`: Chroma index da dong goi san.
- `Results/v3/weights/best.pt`: YOLO weights dang dung.
- `image_dicom/`: sample DICOM de test nhanh.
- `docs/eval_summary.md`: tong hop ket qua eval 10 case.

## Luong RAG1 hien tai

1. Upload DICOM hoac chon sample.
2. Render anh tu DICOM, chay YOLO, sinh `rag1_input.json`, `png`, `crops`.
3. Retrieval lay day du structured sections cua class phat hien.
4. LLM sinh `findings_draft` neu API cho phep, neu khong thi roi ve deterministic fallback.
5. Engine tinh quantitative evidence tu bbox.
6. Selective vision chi duoc can nhac cho case can review:
   `needs_review`, `confidence` thap, support-only class, conflict draft-vs-quantitative, hoac combo critical.
7. Adjudication chot `severity_final`, `critical_flag_final`, combo rules, va tao `final_for_fe`.

## Diem an toan da duoc dam bao

- `study_id` va `image_id` khong con de trong:
  - Neu DICOM co UID thi dung UID.
  - Neu DICOM khong co UID thi fallback `study_<stem>` va `image_<stem>`.
- FE khong nen doc raw draft:
  - FE phai dung `result.final_for_fe`.
  - `result.results_per_detection` chi de audit/debug.
- Mac dinh chay `SAFE_MODE`:
  - khong phu thuoc provider de demo,
  - van sinh duoc `final_for_fe`,
  - vision se duoc danh dau `skipped_safe_mode` thay vi goi ra ngoai.
- Retrieval khong con bi cat cung 5 section:
  - Luon giu full structured sections cua class.
  - `top_k` chi gioi han semantic extras.
- Co combo rules bat buoc:
  - `FLAG_CARDIO_AORTIC`
  - `FLAG_EFFUSION_CARDIO`
  - `FLAG_PNEUMO_EFFUSION`
- Neu model API bi loi/rate-limit:
  - co retry/backoff theo cap so nhan,
  - co cache tren dia cho LLM/semantic retrieval/vision verification,
  - semantic retrieval roi ve structured-only,
  - draft generation roi ve fallback an toan,
  - pipeline van sinh duoc `final_for_fe`, khong vo luong.
- Vision khong goi tran lan:
  - chi xep hang cac detection can review,
  - moi anh toi da 1 lan vision,
  - uu tien detection co combo critical hoac conflict ro rang.

## Gioi han hien tai

- Vision verification da duoc capability-gated nhung mac dinh dang tat.
- Khi provider bi rate-limit, output van on dinh cho FE nhung phan draft text co the don gian hon.
- Nhieu DICOM test khong co `PatientAge`, `PatientSex`, `StudyDescription`, UID; package fallback duoc ID nhung khong the tu tao patient context neu source khong co.

## Cai dat nhanh

```powershell
cd RAG1_WEB_HANDOFF
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Cap nhat `.env`:

```env
GITHUB_TOKEN=ghp_xxx
RAG1_LLM_MODEL=openai/gpt-4o-mini
RAG1_VISION_MODEL=openai/gpt-4o-mini
RAG1_SAFE_MODE=true
RAG1_ENABLE_RESPONSE_CACHE=true
RAG1_MAX_API_RETRIES=3
RAG1_INITIAL_BACKOFF_SECONDS=1.0
RAG1_ENABLE_VISION_VERIFICATION=false
RAG1_VISION_ONLY_ON_REVIEW_CASES=true
RAG1_VISION_CONFIDENCE_THRESHOLD=0.65
RAG1_VISION_MAX_ATTEMPTS_PER_IMAGE=1
```

Khuyen nghi demo truoc hoi dong:

- de `RAG1_SAFE_MODE=true`
- de `RAG1_ENABLE_VISION_VERIFICATION=false` neu khong can minh hoa multimodal
- FE chi doc `final_for_fe`
- neu can show selective vision, bat vision cho 1-2 case mau sau khi tat safe mode

## Chay backend

```powershell
.\scripts\run_backend.ps1
```

Hoac:

```powershell
uvicorn backend_api:app --host 127.0.0.1 --port 8000 --reload
```

Swagger:

```text
http://127.0.0.1:8000/docs
```

## API cho web

### 1. Health

`GET /health`

### 2. Danh sach sample

`GET /samples`

### 3. Chay sample

`POST /rag1/run-sample?sample_id=004f33259ee4aef671c2b95d54e4be68`

Query params:

- `language=vi|en`
- `rag_mode=findings_draft|ddx_only|severity_only`
- `top_k=5`
- `device=cpu`

### 4. Upload DICOM

`POST /rag1/run-upload`

Form fields:

- `dicom_file`
- `language`
- `rag_mode`
- `top_k`
- `device`

## FE nen doc field nao

Sau khi goi API, hay dung:

- `data.result.final_for_fe.study_id`
- `data.result.final_for_fe.image_id`
- `data.result.final_for_fe.findings`
- `data.result.final_for_fe.summary_final`
- `data.result.final_for_fe.overall_severity_final`
- `data.result.final_for_fe.requires_urgent_action_final`
- `data.result.final_for_fe.most_critical_det_id_final`
- `data.result.final_for_fe.flag_codes_final`

Khong nen hien thi truc tiep `results_per_detection[].findings_draft` cho nguoi dung cuoi.

## Cac field audit moi de giai thich

Trong `results_per_detection[].quantitative_evidence` da co them:

- `vision_candidate`
- `vision_candidate_reasons`
- `vision_verification_status`
- `vision_support`
- `vision_explanation`
- `vision_cache_hit`

Trong `metadata` da co them:

- `safe_mode`
- `response_cache_enabled`
- `api_retry_policy`
- `vision_verification_mode`

## Cac artifact sau moi request

Moi job duoc luu trong `outputs/<job_id>/`:

- `<name>.rag1_input.json`
- `<name>.png`
- `<name>_crops/`
- `<name>.rag1_output.json`

## Vi du fetch tu FE

```js
const form = new FormData();
form.append("dicom_file", file);
form.append("language", "vi");
form.append("rag_mode", "findings_draft");
form.append("top_k", "5");
form.append("device", "cpu");

const resp = await fetch("http://127.0.0.1:8000/rag1/run-upload", {
  method: "POST",
  body: form,
});

const data = await resp.json();
const finalResult = data.result.final_for_fe;
console.log(finalResult);
```

## File quan trong trong package

- `backend_api.py`
- `dicom_to_rag1_json.py`
- `rag1_pipeline.py`
- `rag1/engine.py`
- `rag1/retriever.py`
- `rag1/flags.py`
- `rag1/kb_schema.py`
- `docs/eval_summary.md`

## Khuyen nghi cho dev web

- Hien thi `final_for_fe` la mac dinh.
- Chi mo `results_per_detection` trong trang debug/admin.
- Neu `requires_urgent_action_final=true`, day canh bao noi bat len FE.
- Neu can audit, link toi artifact `input_json`, `input_png`, `output_json`.
