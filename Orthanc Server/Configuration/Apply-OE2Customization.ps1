$ErrorActionPreference = 'Stop'

$workspaceConfigDir = 'C:\Users\Dell\OneDrive\Documents\Hackathon\Orthanc Server\Configuration'
$installConfigDir = 'C:\Program Files\Orthanc Server\Configuration'

$files = @(
  'orthanc-explorer-2.json',
  'oe2-custom.css'
)

foreach ($file in $files) {
  Copy-Item (Join-Path $workspaceConfigDir $file) (Join-Path $installConfigDir $file) -Force
}

Restart-Service -Name 'Orthanc'

Write-Host 'Orthanc Explorer 2 customization deployed.'
Write-Host 'Open http://localhost:8042/ui/app/'