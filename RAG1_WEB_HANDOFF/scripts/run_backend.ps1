$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path -Parent $PSScriptRoot)
$python = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) ".venv\Scripts\python.exe"
& $python -m uvicorn backend_api:app --host 127.0.0.1 --port 8000 --reload
