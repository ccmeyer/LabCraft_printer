[CmdletBinding()]
param(
  [ValidateSet("Prepare", "Status", "Update", "Cancel", "Activate", "Verify", "Summarize")]
  [string]$Action = "Status",
  [Parameter(Mandatory = $true)]
  [string]$PiHost,
  [string]$PiUser = "labcraft",
  [string]$SshIdentityFile = "",
  [string]$ProductionRepo = "/home/labcraft/LabCraft_printer",
  [string]$DevelopmentRepo = "/home/labcraft/LabCraft_printer-dev",
  [string]$SharedPython = "/home/labcraft/LabCraft_printer/env/bin/python",
  [string]$WorkflowConfig = "/home/labcraft/.config/LabCraft/development_workflow.json",
  [string]$FirmwareStatePath = "/home/labcraft/.local/share/LabCraft/LabCraft Printer/development-workflow/firmware-state.json",
  [string]$RemoteRoot = "/home/labcraft/.local/share/LabCraft/LabCraft Printer/development-workflow/upgrade-rehearsals",
  [string]$OutputRoot = "verification_reports/upgrade-rehearsal",
  [string[]]$RunId = @(),
  [string]$SourceRelease = "",
  [string]$TargetRelease = "",
  [string]$SourceWrapper = "",
  [string]$ExpectedMachineId = "",
  [string]$Operator = $env:USERNAME,
  [ValidateRange(30, 86400)]
  [int]$TimeoutSeconds = 1800,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = @(
  (Join-Path $repoRoot "env\Scripts\python.exe"),
  (Join-Path $repoRoot ".venv\Scripts\python.exe"),
  (Join-Path $repoRoot "venv\Scripts\python.exe")
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($python)) {
  throw "No repository-local Windows Python interpreter was found."
}

$arguments = @(
  "tools/pi_upgrade_rehearsal.py",
  "--action", $Action.ToLowerInvariant(),
  "--pi-host", $PiHost,
  "--pi-user", $PiUser,
  "--production-repo", $ProductionRepo,
  "--development-repo", $DevelopmentRepo,
  "--shared-python", $SharedPython,
  "--workflow-config", $WorkflowConfig,
  "--firmware-state-path", $FirmwareStatePath,
  "--remote-root", $RemoteRoot,
  "--output-root", $OutputRoot,
  "--operator", $Operator,
  "--timeout-seconds", $TimeoutSeconds
)
if (-not [string]::IsNullOrWhiteSpace($SshIdentityFile)) {
  $arguments += @("--ssh-identity-file", $SshIdentityFile)
}
foreach ($idEntry in $RunId) {
  foreach ($id in ($idEntry -split ",")) {
    if (-not [string]::IsNullOrWhiteSpace($id)) {
      $arguments += @("--run-id", $id.Trim())
    }
  }
}
if (-not [string]::IsNullOrWhiteSpace($SourceRelease)) {
  $arguments += @("--source-release", $SourceRelease)
}
if (-not [string]::IsNullOrWhiteSpace($TargetRelease)) {
  $arguments += @("--target-release", $TargetRelease)
}
if (-not [string]::IsNullOrWhiteSpace($SourceWrapper)) {
  $arguments += @("--source-wrapper", $SourceWrapper)
}
if (-not [string]::IsNullOrWhiteSpace($ExpectedMachineId)) {
  $arguments += @("--expected-machine-id", $ExpectedMachineId)
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
