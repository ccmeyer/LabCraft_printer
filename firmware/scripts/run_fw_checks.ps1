param(
  [string]$Config = "Debug"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $repoRoot
try {
  powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_unit_tests.ps1 -Config $Config
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  powershell -ExecutionPolicy Bypass -File firmware/scripts/build_firmware_headless.ps1 -Config $Config
  exit $LASTEXITCODE
} finally {
  Pop-Location
}
