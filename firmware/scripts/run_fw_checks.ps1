$ErrorActionPreference = "Stop"

powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_unit_tests.ps1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

powershell -ExecutionPolicy Bypass -File firmware/scripts/build_firmware_headless.ps1
exit $LASTEXITCODE