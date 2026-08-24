param(
  [Parameter(Mandatory=$true)]
  [string]$PiHost,                 # e.g. "labcraftpi.local" or "192.168.1.50"

  [string]$PiUser = "labcraft",     # change if needed
  [string]$RemoteRepo = "/home/labcraft/LabCraft_printer",  # repo path on Pi
  [string]$Profile = "SAFE",
  [ValidateSet("Full", "Bisect")]
  [string]$Mode = "Full",
  [string]$Port = "/dev/ttyAMA0",
  [string]$Config = "Debug",
  [string]$IdentityFile = "",
  [int]$SelfTestTimeoutMs = 120000,
  [int]$ProgressTimeoutMs = 30000,
  [int]$ActivityTimeoutMs = 120000,
  [int]$StatusOnlyTimeoutMs = 10000,
  [switch]$PreauthorizeConfirmationPrompts,
  [switch]$CoordinatedXyShallowEdgeSuite,
  [switch]$CameraBenchmark,
  [int]$CameraBenchmarkCycles = 100,
  [int]$CameraBenchmarkExposureUs = 20000,
  [int]$CameraBenchmarkFlashDelayUs = 5000,
  [int]$CameraBenchmarkFlashWidthUs = 1000,
  [int]$CameraBenchmarkNumDroplets = 1,
  [int]$CameraBenchmarkAttemptTimeoutMs = 250,
  [int]$CameraBenchmarkMaxNewFrames = 6,
  [ValidateSet("auto", "pre_selftest", "post_selftest")]
  [string]$CameraBenchmarkOrder = "auto",
  [ValidateSet("flash_only", "print_then_flash")]
  [string]$CameraBenchmarkMode = "flash_only",
  [int]$CameraBenchmarkPreflightPressureTimeoutMs = 1000,

  # Local paths (defaults assume you run from repo root)
  [string]$LocalBin = "firmware\artifacts\LabCraft_firmware.bin",
  [string]$LocalSelfTest = "tools\run_selftest.py",
  [string]$LocalCameraBenchmark = "tools\camera_flash_benchmark.py",
  [string]$LocalFlashAndTest = "firmware\hil\flash_and_test.sh",
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
$sshOptions = @()
$scpOptions = @()
if (-not [string]::IsNullOrWhiteSpace($IdentityFile)) {
  $identityPath = (Resolve-Path $IdentityFile).Path
  $sshOptions += @("-i", $identityPath)
  $scpOptions += @("-i", $identityPath)
}
try {
  $LocalBinAbs = Resolve-Path $LocalBin
  if (-not (Test-Path $LocalSelfTest)) { Fail "Missing $LocalSelfTest. Did you add tools/run_selftest.py?" }
  if (-not (Test-Path $LocalCameraBenchmark)) { Fail "Missing $LocalCameraBenchmark. Did you add tools/camera_flash_benchmark.py?" }
  if (-not (Test-Path $LocalFlashAndTest)) { Fail "Missing $LocalFlashAndTest." }

  # 1) Local checks: host tests + headless build
  Write-Host "=== Local firmware checks ==="
  & powershell -ExecutionPolicy Bypass -File "firmware/scripts/run_fw_checks.ps1" -Config $Config
  if ($LASTEXITCODE -ne 0) { Fail "Local firmware checks failed." }

  # 2) Copy artifacts to Pi
  $remoteBinDir = "$RemoteRepo/firmware/artifacts"
  $remoteToolsDir = "$RemoteRepo/tools"
  $remoteHilDir = "$RemoteRepo/firmware/hil"
  $ts = Get-Date -Format "yyyyMMdd_HHmmss"
  $remoteReport = "$RemoteRepo/hil_reports/selftest_$ts.json"
  $remoteBenchmarkReport = "$RemoteRepo/hil_reports/selftest_${ts}_camera_benchmark.json"

  Write-Host "=== Upload to Pi ==="
  & ssh @sshOptions "$sshTarget" "mkdir -p '$remoteBinDir' '$remoteToolsDir' '$remoteHilDir' '$RemoteRepo/hil_reports'"
  $remoteBinFile  = "$remoteBinDir/LabCraft_firmware.bin"
  $remoteSelfTest = "$remoteToolsDir/run_selftest.py"
  $remoteCameraBenchmark = "$remoteToolsDir/camera_flash_benchmark.py"
  $remoteFlashAndTest = "$remoteHilDir/flash_and_test.sh"

  # scp expects: user@host:/path
  $scpBinTarget      = "${sshTarget}:$remoteBinFile"
  $scpSelfTestTarget = "${sshTarget}:$remoteSelfTest"
  $scpCameraBenchmarkTarget = "${sshTarget}:$remoteCameraBenchmark"
  $scpFlashAndTestTarget = "${sshTarget}:$remoteFlashAndTest"
  $scpReportSource   = "${sshTarget}:$remoteReport"
  $scpBenchmarkReportSource = "${sshTarget}:$remoteBenchmarkReport"

  & scp @scpOptions "$($LocalBinAbs.Path)" $scpBinTarget
  & scp @scpOptions "$LocalSelfTest" $scpSelfTestTarget
  & scp @scpOptions "$LocalCameraBenchmark" $scpCameraBenchmarkTarget
  & scp @scpOptions "$LocalFlashAndTest" $scpFlashAndTestTarget

  # 3) Run flash + selftest on Pi
  if ([string]::IsNullOrWhiteSpace($RemoteVenv)) {
    $RemoteVenv = "$RemoteRepo/.venv"
  }

  $remoteMode = $Mode.ToLowerInvariant()
  $remoteProfile = $Profile
  if ($Mode -eq "Bisect") {
    $remoteProfile = "SAFE"
  }

  $effectiveSelfTestTimeoutMs = $SelfTestTimeoutMs
  $effectiveStatusOnlyTimeoutMs = $StatusOnlyTimeoutMs
  if ($CoordinatedXyShallowEdgeSuite.IsPresent) {
    if (-not $PSBoundParameters.ContainsKey("SelfTestTimeoutMs")) {
      $effectiveSelfTestTimeoutMs = 240000
    }
    if (-not $PSBoundParameters.ContainsKey("StatusOnlyTimeoutMs")) {
      $effectiveStatusOnlyTimeoutMs = 120000
    }
  }

  $flashArgs = @(
    "./firmware/hil/flash_and_test.sh"
    "--bin", "firmware/artifacts/LabCraft_firmware.bin"
    "--port", $Port
    "--profile", $remoteProfile
    "--mode", $remoteMode
    "--report", $remoteReport
    "--selftest-timeout-ms", $effectiveSelfTestTimeoutMs
    "--progress-timeout-ms", $ProgressTimeoutMs
    "--activity-timeout-ms", $ActivityTimeoutMs
    "--status-only-timeout-ms", $effectiveStatusOnlyTimeoutMs
  )
  if ($CameraBenchmark.IsPresent) {
    $flashArgs += @(
      "--camera-benchmark"
      "--camera-benchmark-cycles", $CameraBenchmarkCycles
      "--camera-benchmark-exposure-us", $CameraBenchmarkExposureUs
      "--camera-benchmark-flash-delay-us", $CameraBenchmarkFlashDelayUs
      "--camera-benchmark-flash-width-us", $CameraBenchmarkFlashWidthUs
      "--camera-benchmark-num-droplets", $CameraBenchmarkNumDroplets
      "--camera-benchmark-attempt-timeout-ms", $CameraBenchmarkAttemptTimeoutMs
      "--camera-benchmark-max-new-frames", $CameraBenchmarkMaxNewFrames
      "--camera-benchmark-order", $CameraBenchmarkOrder
      "--camera-benchmark-mode", $CameraBenchmarkMode
      "--camera-benchmark-preflight-pressure-timeout-ms", $CameraBenchmarkPreflightPressureTimeoutMs
    )
  }
  if ($CoordinatedXyShallowEdgeSuite.IsPresent) {
    $flashArgs += "--coordinated-xy-shallow-edge-suite"
  }
  if ($PreauthorizeConfirmationPrompts.IsPresent) {
    $flashArgs += "--preauthorize-confirmation-prompts"
  }

  $cmd = @"
set -e
cd '$RemoteRepo'
if [ -f '$RemoteVenv/bin/activate' ]; then
  . '$RemoteVenv/bin/activate'
fi
python3 - <<'PY'
from pathlib import Path
path = Path('$remoteFlashAndTest')
path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n'))
PY
chmod +x firmware/hil/flash_and_test.sh
$(($flashArgs | ForEach-Object { "'$_'" }) -join " ")
"@
$cmd = $cmd -replace "`r", ""

  Write-Host "=== Flash + selftest on Pi ==="
  & ssh @sshOptions "$sshTarget" bash -lc $cmd
  $remoteHilExitCode = $LASTEXITCODE
  if ($remoteHilExitCode -ne 0) {
    Write-Warning "Pi flash/selftest exited with rc=$remoteHilExitCode; attempting to download its failure report."
  }

  # 4) Pull report back
  $localReportDir = Join-Path $RepoRoot "hil_reports"
  New-Item -ItemType Directory -Force -Path $localReportDir | Out-Null
  $localReport = Join-Path $localReportDir ("selftest_$ts.json")

  Write-Host "=== Download report ==="
  & scp @scpOptions $scpReportSource "$localReport"
  $reportDownloaded = $LASTEXITCODE -eq 0 -and (Test-Path $localReport)
  if (-not $reportDownloaded) {
    if ($remoteHilExitCode -ne 0) {
      Fail "Pi flash/selftest failed with rc=$remoteHilExitCode and its report could not be downloaded from $scpReportSource."
    }
    Fail "Self-test report could not be downloaded from $scpReportSource."
  }
  if ($CameraBenchmark.IsPresent) {
    $localBenchmark = Join-Path $localReportDir ("selftest_${ts}_camera_benchmark.json")
    & scp @scpOptions $scpBenchmarkReportSource "$localBenchmark"
    if ($LASTEXITCODE -eq 0) {
      Write-Host "Benchmark report: $localBenchmark"
    } else {
      Write-Host "Benchmark report not found on Pi (selftest report still downloaded)."
    }
  }

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
  } elseif ($remoteHilExitCode -ne 0) {
    Fail "Pi flash/selftest exited with rc=$remoteHilExitCode despite a passing report."
  } else {
    Write-Host "SELFTEST: PASS"
    exit 0
  }
}
finally {
  Pop-Location
}
