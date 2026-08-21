[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$PiHost,
  [string]$PiUser = "labcraft",
  [string]$SshIdentityFile = "",
  [string]$ProductionRepo = "/home/labcraft/LabCraft_printer",
  [string]$DevelopmentRepo = "/home/labcraft/LabCraft_printer-dev",
  [string]$SharedPython = "/home/labcraft/LabCraft_printer/env/bin/python",
  [string]$WorkflowConfig = "/home/labcraft/.config/LabCraft/development_workflow.json",
  [string]$ReleasedTag = "v1.3.0-rc.5",
  [string]$Port = "/dev/ttyAMA0",
  [string]$Operator = $env:USERNAME,
  [string]$RemoteSessionRoot = "/home/labcraft/.local/share/LabCraft/LabCraft Printer/development-workflow/firmware-sessions",
  [string]$OutputRoot = "verification_reports/development-workflow/firmware",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonCandidates = @(
  (Join-Path $repoRoot "env\Scripts\python.exe"),
  (Join-Path $repoRoot ".venv\Scripts\python.exe"),
  (Join-Path $repoRoot "venv\Scripts\python.exe")
)
$python = $pythonCandidates | Where-Object {
  Test-Path -LiteralPath $_ -PathType Leaf
} | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($python)) {
  throw "No repository-local Windows Python interpreter was found."
}

$arguments = @(
  "tools/pi_development_firmware.py",
  "--pi-host", $PiHost,
  "--pi-user", $PiUser,
  "--production-repo", $ProductionRepo,
  "--development-repo", $DevelopmentRepo,
  "--shared-python", $SharedPython,
  "--workflow-config", $WorkflowConfig,
  "--released-tag", $ReleasedTag,
  "--port", $Port,
  "--operator", $Operator,
  "--remote-session-root", $RemoteSessionRoot,
  "--output-root", $OutputRoot
)
if (-not [string]::IsNullOrWhiteSpace($SshIdentityFile)) {
  $arguments += @("--ssh-identity-file", $SshIdentityFile)
}
if ($DryRun.IsPresent) {
  $arguments += "--dry-run"
}

Push-Location $repoRoot
try {
  & $python @arguments
  exit $LASTEXITCODE
} finally {
  Pop-Location
}
