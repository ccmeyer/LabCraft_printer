[CmdletBinding()]
param(
  [ValidateSet("Status", "Preflight", "Sync", "Configure", "Validate")]
  [string]$Action = "Status",

  [Parameter(Mandatory = $true)]
  [string]$PiHost,

  [string]$PiUser = "labcraft",
  [string]$SshIdentityFile = "",
  [string]$ProductionRepo = "/home/labcraft/LabCraft_printer",
  [string]$DevelopmentRepo = "/home/labcraft/LabCraft_printer-dev",
  [string]$SharedPython = "/home/labcraft/LabCraft_printer/env/bin/python",
  [string]$DevelopmentMachineDataRoot = "",
  [string]$WorkflowConfig = "/home/labcraft/.config/LabCraft/development_workflow.json",
  [string]$Operator = $env:USERNAME,
  [string]$OutputRoot = "verification_reports/development-workflow/status",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-RepoRoot() {
  return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-RepoPython([string]$RepoRoot) {
  foreach ($relative in @(
    "env\Scripts\python.exe",
    ".venv\Scripts\python.exe",
    "venv\Scripts\python.exe"
  )) {
    $candidate = Join-Path $RepoRoot $relative
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
      return $candidate
    }
  }
  throw "No repository-local Windows Python interpreter was found."
}

$repoRoot = Get-RepoRoot
$python = Get-RepoPython -RepoRoot $repoRoot
$arguments = @(
  "tools/pi_development_workflow.py",
  "--action", $Action.ToLowerInvariant(),
  "--pi-host", $PiHost,
  "--pi-user", $PiUser,
  "--production-repo", $ProductionRepo,
  "--development-repo", $DevelopmentRepo,
  "--shared-python", $SharedPython,
  "--workflow-config", $WorkflowConfig,
  "--operator", $Operator,
  "--output-root", $OutputRoot
)
if (-not [string]::IsNullOrWhiteSpace($SshIdentityFile)) {
  $arguments += @("--ssh-identity-file", $SshIdentityFile)
}
if (-not [string]::IsNullOrWhiteSpace($DevelopmentMachineDataRoot)) {
  $arguments += @(
    "--development-machine-data-root",
    $DevelopmentMachineDataRoot
  )
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
