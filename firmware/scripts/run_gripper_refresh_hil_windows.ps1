param(
  [Parameter(Mandatory=$true)]
  [string]$PiHost,

  [string]$PiUser = "labcraft",
  [string]$RemoteRepo = "/home/labcraft/LabCraft_printer",
  [string]$Port = "/dev/ttyAMA0",
  [string]$Config = "Debug",
  [string]$IdentityFile = "",
  [int]$QualificationTimeoutMs = 900000
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($PiHost -match '^(?<User>[^@]+)@(?<Host>.+)$') {
  if ([string]::IsNullOrWhiteSpace($PiUser) -or $PiUser -eq "labcraft") {
    $PiUser = $Matches.User
  }
  $PiHost = $Matches.Host
}

function Fail([string]$message) { throw $message }

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$baseHilScript = Join-Path $PSScriptRoot "run_fw_hil_windows.ps1"
$fixtureId = "dummy_blocked_head_motion_v1"
$sshTarget = "${PiUser}@${PiHost}"
$sshOptions = @()
$scpOptions = @()
if (-not [string]::IsNullOrWhiteSpace($IdentityFile)) {
  $identityPath = (Resolve-Path $IdentityFile).Path
  $sshOptions += @("-i", $identityPath)
  $scpOptions += @("-i", $identityPath)
}
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$remoteOutputRoot = "$RemoteRepo/hil_reports/m4_gripper_refresh_$stamp"
$localOutputParent = Join-Path $RepoRoot "hil_reports"
$localOutputRoot = Join-Path $localOutputParent "m4_gripper_refresh_$stamp"

Push-Location $RepoRoot
try {
  if (-not (Test-Path $baseHilScript)) {
    Fail "Missing base HIL runner: $baseHilScript"
  }

  Write-Host "=== Milestone 4 operator gate ==="
  Write-Host "This run actuates the gripper and print valve, then executes the selected motion/pressure suite."
  Write-Host "Required fixture: $fixtureId"
  Write-Host "Keep the operator present, support the dummy head whenever prompted, and keep the full XY/Z envelope clear."
  $confirmation = Read-Host "Type RUN after the fixture and operator are ready"
  if ($confirmation -cne "RUN") {
    Fail "Operator gate was not confirmed; no HIL actions were started."
  }

  Write-Host "=== Standard FULL flash and self-test ==="
  & powershell -ExecutionPolicy Bypass -File $baseHilScript `
    -PiHost $PiHost `
    -PiUser $PiUser `
    -RemoteRepo $RemoteRepo `
    -Profile FULL `
    -Port $Port `
    -Config $Config `
    -IdentityFile $IdentityFile `
    -SelfTestTimeoutMs 120000 `
    -ProgressTimeoutMs 30000 `
    -ActivityTimeoutMs 120000 `
    -StatusOnlyTimeoutMs 10000
  if ($LASTEXITCODE -ne 0) {
    Fail "Standard FULL HIL failed; selected gripper qualification was not started."
  }

  Write-Host "=== Upload exact qualification tooling ==="
  & ssh @sshOptions $sshTarget "mkdir -p '$RemoteRepo/tools/qualification/manifests' '$RemoteRepo/tools/qualification/campaigns' '$remoteOutputRoot'"
  if ($LASTEXITCODE -ne 0) { Fail "Could not prepare qualification paths on the Pi." }

  & scp @scpOptions "tools/run_selftest.py" "${sshTarget}:$RemoteRepo/tools/run_selftest.py"
  if ($LASTEXITCODE -ne 0) { Fail "Could not upload tools/run_selftest.py." }
  & scp @scpOptions "tools/run_qualification.py" "${sshTarget}:$RemoteRepo/tools/run_qualification.py"
  if ($LASTEXITCODE -ne 0) { Fail "Could not upload tools/run_qualification.py." }

  $qualificationFiles = Get-ChildItem "tools/qualification" -Recurse -File |
    Where-Object { $_.Extension -in @(".py", ".json") }
  foreach ($file in $qualificationFiles) {
    $relative = $file.FullName.Substring($RepoRoot.Path.Length + 1).Replace('\', '/')
    $remoteFile = "$RemoteRepo/$relative"
    $remoteDir = [System.IO.Path]::GetDirectoryName($remoteFile).Replace('\', '/')
    & ssh @sshOptions $sshTarget "mkdir -p '$remoteDir'"
    if ($LASTEXITCODE -ne 0) { Fail "Could not prepare remote directory for $relative." }
    & scp @scpOptions $file.FullName "${sshTarget}:$remoteFile"
    if ($LASTEXITCODE -ne 0) { Fail "Could not upload $relative." }
  }

  $remoteCommand = @"
set -e
cd '$RemoteRepo'
test -f local/machine_identity.json || { echo 'Missing required local/machine_identity.json' >&2; exit 2; }
if [ -f '$RemoteRepo/.venv/bin/activate' ]; then
  . '$RemoteRepo/.venv/bin/activate'
fi
python3 -u tools/run_qualification.py \
  --manifest gripper_seal_stress_v2 \
  --port '$Port' \
  --fixture '$fixtureId' \
  --operator-prompts \
  --progress-jsonl \
  --timeout-ms '$QualificationTimeoutMs' \
  --output-root '$remoteOutputRoot'
"@
  $remoteCommand = $remoteCommand -replace "`r", ""

  Write-Host "=== Production-path gripper FULL qualification ==="
  & ssh @sshOptions -tt $sshTarget bash -lc $remoteCommand
  $qualificationExitCode = $LASTEXITCODE

  Write-Host "=== Download qualification artifacts ==="
  New-Item -ItemType Directory -Force -Path $localOutputParent | Out-Null
  & scp @scpOptions -r "${sshTarget}:$remoteOutputRoot" "$localOutputParent"
  $downloadExitCode = $LASTEXITCODE
  if ($downloadExitCode -ne 0) {
    Fail "Qualification finished with rc=$qualificationExitCode, but its artifacts could not be downloaded."
  }

  $reportPath = Get-ChildItem $localOutputRoot -Recurse -File -Filter "report.json" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if ($null -eq $reportPath) {
    Fail "Downloaded qualification artifacts do not contain report.json."
  }
  $report = Get-Content $reportPath.FullName -Raw | ConvertFrom-Json
  $productionCheck = $report.host_checks |
    Where-Object { $_.name -eq "gripper_refresh_production_path" } |
    Select-Object -First 1

  Write-Host ""
  Write-Host "=== Milestone 4 qualification summary ==="
  Write-Host "Report: $($reportPath.FullName)"
  Write-Host "Overall status: $($report.overall_status)"
  Write-Host "Production-path host check: $($productionCheck.pass)"

  if ($qualificationExitCode -ne 0) {
    Fail "Selected gripper qualification failed with rc=$qualificationExitCode. Artifacts were retained at $localOutputRoot."
  }
  if ($report.overall_status -ne "pass" -or $null -eq $productionCheck -or $productionCheck.pass -ne $true) {
    Fail "Selected gripper qualification report did not meet the Milestone 4 acceptance contract."
  }

  Write-Host "MILESTONE 4 HIL: PASS"
}
finally {
  Pop-Location
}
