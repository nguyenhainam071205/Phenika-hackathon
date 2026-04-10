$ErrorActionPreference = "Stop"
Set-Location -Path (Split-Path -Parent $PSScriptRoot)
uvicorn backend_api:app --host 127.0.0.1 --port 8000 --reload
