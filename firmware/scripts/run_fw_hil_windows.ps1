param(
  [Parameter(Mandatory=$true)]
  [string]$PiHost,                 # e.g. "labcraftpi.local" or "192.168.1.50"

  [string]$PiUser = "labcraft",     # change if needed
  [string]$RemoteRepo = "/home/labcraft/LabCraft_printer",  # repo path on Pi
  [string]$Profile = "FULL",
  [string]$Port = "/dev/ttyAMA0",
  [string]$Config = "Debug",

  # Local paths (defaults assume you run from repo root)
  [string]$LocalBin = "firmware\artifacts\LabCraft_firmware.bin",
  [string]$LocalSelfTest = "tools\run_selftest.py",
  [string]$RemoteVenv = ""          # default: "$RemoteRepo/.venv"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PiHost -match '^(?<User>[^@]+)@(?<Host>.+)$') {
  if ([string]::IsNullOrWhiteSpace($PiUser) -or $PiUser -eq "labcraft") {
    $PiUser = $Matches.User
  }
  $PiHost = $Matches.Host
}

function Require-Cmd([string]$name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw "Missing command '$name'. Install/enable OpenSSH client (ssh/scp) on Windows."
  }
}

function Fail([string]$msg) { throw $msg }

Require-Cmd "ssh"
Require-Cmd "scp"

# Resolve repo root (this script is firmware/scripts/*.ps1)
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Push-Location $RepoRoot
$sshTarget = "${PiUser}@${PiHost}"
try {
  $LocalBinAbs = Resolve-Path $LocalBin
  if (-not (Test-Path $LocalSelfTest)) { Fail "Missing $LocalSelfTest. Did you add tools/run_selftest.py?" }

  # 1) Local checks: host tests + headless build
  Write-Host "=== Local firmware checks ==="
  & powershell -ExecutionPolicy Bypass -File "firmware/scripts/run_fw_checks.ps1" -Config $Config
  if ($LASTEXITCODE -ne 0) { Fail "Local firmware checks failed." }

  # 2) Copy artifacts to Pi
  $remoteBinDir = "$RemoteRepo/firmware/artifacts"
  $remoteToolsDir = "$RemoteRepo/tools"
  $ts = Get-Date -Format "yyyyMMdd_HHmmss"
  $remoteReport = "$RemoteRepo/hil_reports/selftest_$ts.json"

  Write-Host "=== Upload to Pi ==="
  ssh "$sshTarget" "mkdir -p '$remoteBinDir' '$remoteToolsDir' '$RemoteRepo/hil_reports'"
  $remoteBinFile  = "$remoteBinDir/LabCraft_firmware.bin"
  $remoteSelfTest = "$remoteToolsDir/run_selftest.py"

  # scp expects: user@host:/path
  $scpBinTarget      = "${sshTarget}:$remoteBinFile"
  $scpSelfTestTarget = "${sshTarget}:$remoteSelfTest"
  $scpReportSource   = "${sshTarget}:$remoteReport"

scp "$($LocalBinAbs.Path)" $scpBinTarget
  scp "$LocalSelfTest" $scpSelfTestTarget

  # 3) Run flash + selftest on Pi
  if ([string]::IsNullOrWhiteSpace($RemoteVenv)) {
    $RemoteVenv = "$RemoteRepo/.venv"
  }

  $cmd = @"
set -e
cd '$RemoteRepo'
if [ -f '$RemoteVenv/bin/activate' ]; then
  . '$RemoteVenv/bin/activate'
fi
chmod +x firmware/hil/flash_and_test.sh
./firmware/hil/flash_and_test.sh --bin firmware/artifacts/LabCraft_firmware.bin --port '$Port' --profile '$Profile' --report '$remoteReport'
"@
$cmd = $cmd -replace "`r", ""

  Write-Host "=== Flash + selftest on Pi ==="
  ssh "$sshTarget" bash -lc $cmd
  if ($LASTEXITCODE -ne 0) { Fail "Pi flash/selftest failed." }

  # 4) Pull report back
  $localReportDir = Join-Path $RepoRoot "hil_reports"
  New-Item -ItemType Directory -Force -Path $localReportDir | Out-Null
  $localReport = Join-Path $localReportDir ("selftest_$ts.json")

  Write-Host "=== Download report ==="
  scp $scpReportSource       "$localReport"

  # 5) Summarize report
  $reportObj = Get-Content $localReport -Raw | ConvertFrom-Json
  $failed = [int]$reportObj.summary.failed
  $passed = [int]$reportObj.summary.passed
  $total  = [int]$reportObj.summary.total

  Write-Host ""
  Write-Host "=== Selftest summary ==="
  Write-Host "Report: $localReport"
  Write-Host "Run ID: $($reportObj.run_id)  Profile: $($reportObj.profile)"
  Write-Host "Passed: $passed / $total   Failed: $failed"

  if ($failed -gt 0 -or $reportObj.aborted -eq $true) {
    Write-Host "SELFTEST: FAIL"
    exit 2
  } else {
    Write-Host "SELFTEST: PASS"
    exit 0
  }
}
finally {
  Pop-Location
}
