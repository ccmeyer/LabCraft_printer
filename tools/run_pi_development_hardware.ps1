[CmdletBinding()]
param(
  [ValidateSet("Preflight", "Cancel", "Launch")]
  [string]$Action = "Preflight",
  [ValidateSet("Hardware", "No-Hardware")]
  [string]$RuntimeMode = "Hardware",
  [ValidateSet("Normal", "Stale-Commit", "Mismatched-Artifact")]
  [string]$QualificationScenario = "Normal",
  [Parameter(Mandatory = $true)]
  [string]$PiHost,
  [string]$PiUser = "labcraft",
  [string]$SshIdentityFile = "",
  [string]$ProductionRepo = "/home/labcraft/LabCraft_printer",
  [string]$DevelopmentRepo = "/home/labcraft/LabCraft_printer-dev",
  [string]$SharedPython = "/home/labcraft/LabCraft_printer/env/bin/python",
  [string]$WorkflowConfig = "/home/labcraft/.config/LabCraft/development_workflow.json",
  [string]$FirmwareStatePath = "/home/labcraft/.local/share/LabCraft/LabCraft Printer/development-workflow/firmware-state.json",
  [string]$ReleasedTag = "v1.3.0-rc.7",
  [string]$RemoteSessionRoot = "/home/labcraft/.local/share/LabCraft/LabCraft Printer/development-workflow/hardware-sessions",
  [string]$OutputRoot = "verification_reports/development-workflow/hardware",
  [string]$Operator = $env:USERNAME,
  [string]$AttendedConfirmation = "",
  [ValidateRange(30, 86400)]
  [int]$LaunchTimeoutSeconds = 1800,
  [switch]$Execute,
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
  "tools/pi_development_hardware.py",
  "--action", $Action.ToLowerInvariant(),
  "--runtime-mode", $RuntimeMode.ToLowerInvariant(),
  "--qualification-scenario", $QualificationScenario.ToLowerInvariant(),
  "--pi-host", $PiHost,
  "--pi-user", $PiUser,
  "--production-repo", $ProductionRepo,
  "--development-repo", $DevelopmentRepo,
  "--shared-python", $SharedPython,
  "--workflow-config", $WorkflowConfig,
  "--firmware-state-path", $FirmwareStatePath,
  "--released-tag", $ReleasedTag,
  "--remote-session-root", $RemoteSessionRoot,
  "--output-root", $OutputRoot,
  "--operator", $Operator,
  "--launch-timeout-seconds", $LaunchTimeoutSeconds
)
if (-not [string]::IsNullOrWhiteSpace($SshIdentityFile)) {
  $arguments += @("--ssh-identity-file", $SshIdentityFile)
}
if (-not [string]::IsNullOrWhiteSpace($AttendedConfirmation)) {
  $arguments += @("--attended-confirmation", $AttendedConfirmation)
}
if ($Execute.IsPresent) { $arguments += "--execute" }
if ($DryRun.IsPresent) { $arguments += "--dry-run" }

Push-Location $repoRoot
try {
  & $python @arguments
  exit $LASTEXITCODE
} finally {
  Pop-Location
}
