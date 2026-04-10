# RAG2 Dev Handoff

Goi nay dong goi rieng phan `RAG2` de mot dev web co the clone ve, chay backend, va goi HTTP ngay ma khong can repo goc.

## Ben trong co gi

- `backend_api.py`: FastAPI wrapper cho web/frontend goi HTTP.
- `rag2_pipeline.py`: CLI chay index, generate, demo, demo-from-rag1.
- `rag2/`: code report generation, adapter, retriever, prompts, schema.
- `rag2/kb_data/`: knowledge base markdown cho RAG2.
- `rag2/chroma_store/`: Chroma index da dong goi san.
- `rag1/kb_schema.py`: schema toi thieu de adapter `RAG1 output -> Doctor-Revised JSON` chay standalone.
- `demo_rag1_output.doctor_revised.json`: payload mau cho `POST /rag2/generate-report`.
- `demo_rag1_output.json`: payload mau cho `POST /rag2/demo-from-rag1`.
- `demo_rag1_output.doctor_revised.rag2_output.json`: sample output khi chay `generate`.
- `demo_rag1_output.rag2_output.json`: sample output khi chay `demo-from-rag1`.
- `outputs/`: noi luu artifacts moi lan chay.

## Package nay dung cho ai

Bundle nay phu hop khi dev web can:

- nhan `Doctor-Revised JSON` tu frontend viewer va goi RAG2 de sinh bao cao,
- hoac test nhanh voi sample co san,
- hoac tam thoi nhan `RAG1 output JSON` va dung adapter auto de sinh report.

Bundle nay KHONG can model YOLO, DICOM parser, hay full RAG1 runtime.

## Trang thai hien tai

Bundle da co du:

- code runtime RAG2,
- knowledge base va index san,
- sample JSON de test nhanh,
- API HTTP de frontend tich hop.

Luu y:

- Phai dien `GITHUB_TOKEN` vao `.env` truoc khi chay, vi phan embedding/generation dang goi GitHub Models.
- `rag2/chroma_store/` da duoc dong goi san, nen web dev thuong khong can chay `index` lai.
- Endpoint chinh cho frontend la `POST /rag2/generate-report`.

## Cach chay nhanh

1. Tao virtual env va cai dependency:

```powershell
cd RAG2_DEV_HANDOFF
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Dien token vao `.env`:

```env
GITHUB_TOKEN=ghp_xxx
```

3. Chay backend:

```powershell
uvicorn backend_api:app --host 127.0.0.1 --port 8000 --reload
```

4. Mo Swagger:

```text
http://127.0.0.1:8000/docs
```

## Endpoint backend cho frontend

### 1. Kiem tra server

`GET /health`

### 2. Lay sample co san

`GET /samples`

### 3. Chay sample nhanh

`POST /rag2/run-sample?sample_id=doctor_revised_demo`

Hoac:

`POST /rag2/run-sample?sample_id=rag1_output_demo&language=vi+en`

### 4. Endpoint chinh cho frontend

`POST /rag2/generate-report`

Request body: `Doctor-Revised JSON` theo schema trong `rag2/schema.py`.

### 5. Endpoint test tu RAG1 output

`POST /rag2/demo-from-rag1`

Request body: `RAG1 output JSON`

Co the them field tuy chon:

```json
{
  "_language": "vi+en"
}
```

## Vi du fetch cho frontend

### Goi sample Doctor-Revised

```js
const resp = await fetch(
  "http://127.0.0.1:8000/rag2/run-sample?sample_id=doctor_revised_demo",
  { method: "POST" }
);
const data = await resp.json();
console.log(data.result);
```

### Goi endpoint chinh voi payload tu frontend

```js
const resp = await fetch("http://127.0.0.1:8000/rag2/generate-report", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(doctorRevisedJson),
});
const data = await resp.json();
console.log(data.result);
```

### Goi auto adapter tu RAG1 output

```js
const rag1Payload = {
  ...rag1OutputJson,
  _language: "vi+en",
};

const resp = await fetch("http://127.0.0.1:8000/rag2/demo-from-rag1", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(rag1Payload),
});
const data = await resp.json();
console.log(data.result);
```

## Output sau moi lan chay

Moi request duoc luu trong `outputs/<job_id>/` voi cac file phu hop:

- `doctor_revised_input.json`
- `rag1_input.json` neu di qua adapter
- `doctor_revised_adapter.json` neu di qua adapter
- `rag2_report.json`

API cung tra ve:

- `job_id`
- `artifacts`
- `result`

## Chay bang CLI neu can

### Chay demo tu Doctor-Revised synthetic

```powershell
python rag2_pipeline.py demo --language vi+en
```

### Chay voi sample Doctor-Revised co san

```powershell
python rag2_pipeline.py generate --input demo_rag1_output.doctor_revised.json
```

### Chay tu sample RAG1 output

```powershell
python rag2_pipeline.py demo-from-rag1 --rag1-output demo_rag1_output.json
```

### Rebuild index neu muon

Co the bo qua vi package da kem `rag2/chroma_store/` san.

```powershell
python rag2_pipeline.py index
```

## Ban giao cho dev

Neu dev web chi can tich hop frontend:

- chay backend theo huong dan o tren,
- goi `POST /rag2/generate-report` voi payload tu viewer,
- hoac dung `POST /rag2/run-sample` de test nhanh,
- doc `data.result` de hien thi bao cao song ngu.

Neu dev can doi KB:

- cap nhat file trong `rag2/kb_data/`,
- chay lai `python rag2_pipeline.py index`.
