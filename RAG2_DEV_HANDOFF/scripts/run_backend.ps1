$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..
$python = Join-Path (Split-Path -Parent $PSScriptRoot) ".venv\Scripts\python.exe"
& $python -m uvicorn backend_api:app --host 127.0.0.1 --port 8001 --reload
