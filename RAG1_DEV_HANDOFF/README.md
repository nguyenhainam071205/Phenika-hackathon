# RAG1 Dev Handoff

Goi nay dong goi rieng phan `RAG1` de dev co the nhan va chay doc lap voi repo goc.

## Ben trong co gi

- `backend_api.py`: FastAPI wrapper de frontend goi HTTP.
- `rag1_pipeline.py`: CLI chay end-to-end.
- `dicom_to_rag1_json.py`: doc DICOM, render PNG, chay YOLO, xuat input JSON.
- `rag1/`: code retrieval, generation, schema, config.
- `dataRAG1/RAG1_Knowledge_Base_CXR14_v2.pdf`: knowledge base PDF.
- `rag1/chroma_store/`: Chroma index da dong goi san.
- `Results/v3/weights/best.pt`: model YOLO dang dung.
- `image_dicom/`: DICOM mau de test nhanh.
- `.env`: file cau hinh an toan, KHONG chua token that.

## Trang thai hien tai

Bundle nay da du thanh phan de dev tich hop backend va frontend.

Luu y:
- Phai dien `GITHUB_TOKEN` vao `.env` truoc khi chay, vi phan generation va embedding dang goi GitHub Models.
- Neu may Windows chan DLL cua `torch` thi buoc YOLO se loi. Tren may kiem tra goc da gap `WinError 4551`.
- Bundle nay da va loi `uuid` trong `rag1_pipeline.py` ma repo goc dang gap.

## Cau truc quan trong

- `backend_api.py`
- `rag1_pipeline.py`
- `dicom_to_rag1_json.py`
- `rag1/`
- `image_dicom/`
- `Results/v3/weights/best.pt`
- `dataRAG1/RAG1_Knowledge_Base_CXR14_v2.pdf`
- `outputs/`

## Cach chay nhanh

1. Tao virtual env va cai dependency:

```powershell
cd RAG1_DEV_HANDOFF
py -3.11 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```

2. Dien token vao `.env`:

```env
GITHUB_TOKEN=ghp_xxx
```

3. Kiem tra API:

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

### 2. Lay danh sach DICOM mau

`GET /samples`

### 3. Chay voi sample da dong goi

`POST /rag1/run-sample?sample_id=004f33259ee4aef671c2b95d54e4be68`

Co the them:
- `language=vi|en`
- `rag_mode=findings_draft|ddx_only|severity_only`
- `top_k=5`
- `device=cpu`

### 4. Upload DICOM tu frontend

`POST /rag1/run-upload`

Form fields:
- `dicom_file`: file `.dicom`
- `language`
- `rag_mode`
- `top_k`
- `device`

## Vi du fetch cho frontend

### Goi sample

```js
const resp = await fetch(
  "http://127.0.0.1:8000/rag1/run-sample?sample_id=004f33259ee4aef671c2b95d54e4be68",
  { method: "POST" }
);
const data = await resp.json();
console.log(data.result);
```

### Goi upload

```js
const form = new FormData();
form.append("dicom_file", fileInput.files[0]);
form.append("language", "vi");
form.append("rag_mode", "findings_draft");
form.append("top_k", "5");
form.append("device", "cpu");

const resp = await fetch("http://127.0.0.1:8000/rag1/run-upload", {
  method: "POST",
  body: form,
});
const data = await resp.json();
console.log(data.result);
```

## Output sau moi lan chay

Moi request se duoc luu trong `outputs/<job_id>/` voi:

- `<name>.rag1_input.json`
- `<name>.png`
- `<name>.rag1_output.json`

API cung tra ve:
- `job_id`
- `artifacts`
- `detector`
- `result`

## Chay bang CLI neu can

### Chay demo

```powershell
python rag1_pipeline.py demo --language vi
```

### Chay 1 DICOM

```powershell
python rag1_pipeline.py run --dicom image_dicom/004f33259ee4aef671c2b95d54e4be68.dicom --device cpu --language vi
```

### Rebuild index neu muon

Co the bo qua vi package da kem `rag1/chroma_store/` san.

```powershell
python rag1_pipeline.py index
```

## Ban giao cho dev

Neu dev chi can tich hop frontend:
- chay backend theo huong dan o tren,
- goi `/rag1/run-sample` hoac `/rag1/run-upload`,
- doc `data.result` de hien thi ket qua.

Neu dev can doi model/KB:
- thay `Results/v3/weights/best.pt`,
- thay PDF trong `dataRAG1/`,
- chay lai `python rag1_pipeline.py index`.
