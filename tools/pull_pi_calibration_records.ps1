[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$PiHost,

  [string]$PiUser = "labcraft",
  [string]$RemoteRepo = "/home/labcraft/LabCraft_printer",

  [string]$ExperimentName = "",
  [string]$ExperimentMatch = "",
  [switch]$Latest,

  [ValidateSet("WholeExperiment", "CalibrationOnly")]
  [string]$CopyMode = "WholeExperiment",

  [string]$LocalRoot = "tmp/pi_calibration",
  [string[]]$ProcessName = @(),
  [string[]]$RunId = @(),

  [switch]$Replay,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Require-Cmd([string]$Name) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "Missing command '$Name'. Install/enable OpenSSH client (ssh/scp) on Windows."
  }
}

function Fail([string]$Message) {
  throw $Message
}

function ConvertTo-ShellLiteral([string]$Value) {
  return "'" + $Value.Replace("'", "'\''") + "'"
}

function New-ScpRemoteSpec([string]$Target, [string]$RemotePath) {
  if ($RemotePath -match "\s") {
    $escaped = $RemotePath.Replace('"', '\"')
    return "${Target}:`"$escaped`""
  }
  return "${Target}:$RemotePath"
}

function Resolve-AbsolutePathString([string]$PathValue, [string]$BaseDir) {
  if ([System.IO.Path]::IsPathRooted($PathValue)) {
    return [System.IO.Path]::GetFullPath($PathValue)
  }
  return [System.IO.Path]::GetFullPath((Join-Path $BaseDir $PathValue))
}

function Sanitize-FileComponent([string]$Value) {
  $invalid = [System.IO.Path]::GetInvalidFileNameChars()
  $sanitized = $Value
  foreach ($ch in $invalid) {
    $sanitized = $sanitized.Replace([string]$ch, "_")
  }
  return $sanitized
}

function Join-UniqueDest([string]$Root, [string]$ExperimentBaseName) {
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $base = "${stamp}_$(Sanitize-FileComponent $ExperimentBaseName)"
  $candidate = Join-Path $Root $base
  if (-not (Test-Path $candidate)) {
    return $candidate
  }
  $suffix = [guid]::NewGuid().ToString("N").Substring(0, 6)
  return Join-Path $Root "${base}_$suffix"
}

function Get-RepoRoot() {
  return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Invoke-SshCapture([string]$Target, [string]$Command) {
  $remoteCommand = "bash -lc " + (ConvertTo-ShellLiteral $Command)
  $output = & ssh $Target $remoteCommand 2>&1
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    $text = (($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()
    throw "ssh failed ($exitCode): $text"
  }
  return ,@($output | ForEach-Object { $_.ToString() })
}

function Invoke-Scp([string[]]$Arguments) {
  $output = & scp @Arguments 2>&1
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    $text = (($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()
    throw "scp failed ($exitCode): $text"
  }
}

function Test-RemotePathExists([string]$Target, [string]$RemotePath, [string]$Kind = "either") {
  $pathLit = ConvertTo-ShellLiteral $RemotePath
  $testExpr = switch ($Kind) {
    "file" { "-f $pathLit" }
    "dir"  { "-d $pathLit" }
    default { "-e $pathLit" }
  }
  $cmd = "if [ $testExpr ]; then printf '1'; fi"
  $out = Invoke-SshCapture -Target $Target -Command $cmd
  return ((($out -join "").Trim()) -eq "1")
}

function Get-RemoteExperiments([string]$Target, [string]$ExperimentsRoot) {
  $rootLit = ConvertTo-ShellLiteral $ExperimentsRoot
  $cmd = @(
    "if [ ! -d $rootLit ]; then"
    "  echo '__MISSING_ROOT__';"
    "  exit 3;"
    "fi;"
    "find $rootLit -mindepth 1 -maxdepth 1 -type d -printf '%T@|%f|%p\n' | sort -nr"
  ) -join " "

  $lines = Invoke-SshCapture -Target $Target -Command $cmd
  if (($lines.Count -eq 1) -and ($lines[0].Trim() -eq "__MISSING_ROOT__")) {
    throw "Remote experiments root not found: $ExperimentsRoot"
  }

  $rows = @()
  foreach ($line in $lines) {
    $trimmed = $line.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) {
      continue
    }
    $parts = $trimmed -split "\|", 3
    if ($parts.Count -lt 3) {
      continue
    }
    $mtime = 0.0
    [void][double]::TryParse($parts[0], [ref]$mtime)
    $rows += [pscustomobject]@{
      MTime = [double]$mtime
      Name  = [string]$parts[1]
      Path  = [string]$parts[2]
    }
  }
  return ,@($rows)
}

function Select-RemoteExperiment([object[]]$Experiments, [string]$ExactName, [string]$Substring, [bool]$UseLatest) {
  if (-not $Experiments -or $Experiments.Count -eq 0) {
    throw "No experiments found in remote experiments root."
  }

  if ($UseLatest) {
    return $Experiments | Select-Object -First 1
  }

  if (-not [string]::IsNullOrWhiteSpace($ExactName)) {
    $matches = @($Experiments | Where-Object { $_.Name -ieq $ExactName })
    if ($matches.Count -eq 0) {
      throw "Experiment not found: $ExactName"
    }
    return $matches[0]
  }

  $matches = @($Experiments | Where-Object { $_.Name -like "*$Substring*" })
  if ($matches.Count -eq 0) {
    throw "No experiments matched substring '$Substring'."
  }
  if ($matches.Count -gt 1) {
    $candidates = $matches | ForEach-Object { $_.Name } | Sort-Object
    throw ("Experiment match '$Substring' was ambiguous. Candidates: " + ($candidates -join ", "))
  }
  return $matches[0]
}

function Get-PhaseSummary([string]$CalibrationFilePath) {
  $summary = [ordered]@{
    run_count = 0
    phase_counts = [ordered]@{}
    phase_latest_timestamps = [ordered]@{}
  }
  if (-not (Test-Path $CalibrationFilePath)) {
    return $summary
  }

  try {
    $payload = Get-Content $CalibrationFilePath -Raw | ConvertFrom-Json
  } catch {
    $summary["error"] = "Failed to parse calibration.json: $($_.Exception.Message)"
    return $summary
  }

  $runs = @($payload.runs)
  $summary.run_count = $runs.Count
  $phaseCounts = @{}
  $phaseLatest = @{}

  foreach ($run in $runs) {
    $stepsObj = $run.steps
    if ($null -eq $stepsObj) {
      continue
    }
    foreach ($prop in $stepsObj.PSObject.Properties) {
      $phase = [string]$prop.Name
      $records = @($prop.Value)
      if (-not $phaseCounts.ContainsKey($phase)) {
        $phaseCounts[$phase] = 0
      }
      $phaseCounts[$phase] += $records.Count
      foreach ($record in $records) {
        $stamp = [string]($record.timestamp)
        if ([string]::IsNullOrWhiteSpace($stamp)) {
          continue
        }
        if ((-not $phaseLatest.ContainsKey($phase)) -or ($stamp -gt $phaseLatest[$phase])) {
          $phaseLatest[$phase] = $stamp
        }
      }
    }
  }

  foreach ($phase in ($phaseCounts.Keys | Sort-Object)) {
    $latestStamp = ""
    if ($phaseLatest.ContainsKey($phase)) {
      $latestStamp = [string]$phaseLatest[$phase]
    }
    $summary.phase_counts[$phase] = [int]$phaseCounts[$phase]
    $summary.phase_latest_timestamps[$phase] = $latestStamp
  }
  return $summary
}

function Get-RecordingInventory([string]$RecordingsRoot) {
  $inventory = [ordered]@{}
  if (-not (Test-Path $RecordingsRoot)) {
    return $inventory
  }
  foreach ($processDir in (Get-ChildItem $RecordingsRoot -Directory | Sort-Object Name)) {
    $runDirs = @(Get-ChildItem $processDir.FullName -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "run_*" } | Sort-Object Name)
    $inventory[$processDir.Name] = [ordered]@{
      path = $processDir.FullName
      count = [int]$runDirs.Count
      run_ids = @($runDirs | ForEach-Object { $_.Name })
    }
  }
  return $inventory
}

function Contains-ValueCaseInsensitive([string[]]$Values, [string]$Candidate) {
  foreach ($value in @($Values)) {
    if ($null -ne $value -and $value.Equals($Candidate, [System.StringComparison]::OrdinalIgnoreCase)) {
      return $true
    }
  }
  return $false
}

function Materialize-SelectedRecords([string]$ExperimentDir, [string[]]$ProcessFilters, [string[]]$RunFilters) {
  $hasProcessFilters = (@($ProcessFilters).Count -gt 0)
  $hasRunFilters = (@($RunFilters).Count -gt 0)
  if (-not ($hasProcessFilters -or $hasRunFilters)) {
    return $null
  }

  $recordingsRoot = Join-Path $ExperimentDir "calibration_recordings"
  if (-not (Test-Path $recordingsRoot)) {
    return $null
  }

  $selectedDir = Join-Path $ExperimentDir "selected_records"
  $selectedRecordingsRoot = Join-Path $selectedDir "calibration_recordings"
  New-Item -ItemType Directory -Force -Path $selectedRecordingsRoot | Out-Null

  foreach ($name in @("calibration.json", "experiment_design.json")) {
    $src = Join-Path $ExperimentDir $name
    if (Test-Path $src) {
      Copy-Item -Path $src -Destination (Join-Path $selectedDir $name) -Force
    }
  }

  foreach ($processDir in (Get-ChildItem $recordingsRoot -Directory | Sort-Object Name)) {
    if ($hasProcessFilters -and -not (Contains-ValueCaseInsensitive -Values $ProcessFilters -Candidate $processDir.Name)) {
      continue
    }

    $runDirs = @(Get-ChildItem $processDir.FullName -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "run_*" })
    if ($hasRunFilters) {
      $runDirs = @($runDirs | Where-Object { Contains-ValueCaseInsensitive -Values $RunFilters -Candidate $_.Name })
    }
    if ($runDirs.Count -eq 0) {
      continue
    }

    $destProcessDir = Join-Path $selectedRecordingsRoot $processDir.Name
    New-Item -ItemType Directory -Force -Path $destProcessDir | Out-Null
    foreach ($runDir in $runDirs) {
      Copy-Item -Path $runDir.FullName -Destination (Join-Path $destProcessDir $runDir.Name) -Recurse -Force
    }
  }

  return $selectedDir
}

function Get-FirstRunPath([System.Collections.IDictionary]$Inventory) {
  foreach ($processName in ($Inventory.Keys | Sort-Object)) {
    $entry = $Inventory[$processName]
    $runIds = @($entry.run_ids)
    if ($runIds.Count -gt 0) {
      return Join-Path $entry.path $runIds[0]
    }
  }
  return $null
}

function Get-PreferredPython([string]$RepoRoot) {
  $candidates = @(
    (Join-Path $RepoRoot "env\Scripts\python.exe"),
    (Join-Path $RepoRoot ".venv\Scripts\python.exe")
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd) {
    return $pythonCmd.Source
  }
  $pyCmd = Get-Command py -ErrorAction SilentlyContinue
  if ($pyCmd) {
    return "$($pyCmd.Source) -3"
  }
  return $null
}

function Write-PullSummary([System.Collections.IDictionary]$Manifest) {
  Write-Host ""
  Write-Host "=== Pi Calibration Pull Summary ==="
  Write-Host "Remote experiment: $($Manifest.remote.selected_experiment_path)"
  Write-Host "Local destination: $($Manifest.local.experiment_dir)"
  Write-Host "Copy mode: $($Manifest.copy_mode)"
  if ($Manifest.local.selected_records_dir) {
    Write-Host "Selected records: $($Manifest.local.selected_records_dir)"
  }

  $phaseSummary = $Manifest.phase_summary
  if ($phaseSummary.run_count -gt 0) {
    Write-Host "Calibration runs in calibration.json: $($phaseSummary.run_count)"
    foreach ($phase in $phaseSummary.phase_counts.Keys) {
      $count = $phaseSummary.phase_counts[$phase]
      $stamp = $phaseSummary.phase_latest_timestamps[$phase]
      Write-Host "  - $phase : $count (latest $stamp)"
    }
  } else {
    Write-Host "No calibration.json records found."
  }

  $inventory = $Manifest.process_inventory
  if ($inventory.Count -gt 0) {
    Write-Host "Recording inventory:"
    foreach ($process in $inventory.Keys) {
      $entry = $inventory[$process]
      $runIds = @($entry.run_ids)
      $runPreview = if ($runIds.Count -gt 0) { $runIds -join ", " } else { "(no runs)" }
      Write-Host "  - $process : $($entry.count) runs"
      Write-Host "    $runPreview"
    }
  } else {
    Write-Host "No calibration_recordings directory found."
  }

  Write-Host "Suggested commands:"
  foreach ($cmd in @($Manifest.suggested_commands)) {
    Write-Host "  $cmd"
  }
}

Require-Cmd "ssh"
Require-Cmd "scp"

$selectorCount = 0
if (-not [string]::IsNullOrWhiteSpace($ExperimentName)) { $selectorCount += 1 }
if (-not [string]::IsNullOrWhiteSpace($ExperimentMatch)) { $selectorCount += 1 }
if ($Latest.IsPresent) { $selectorCount += 1 }
if ($selectorCount -ne 1) {
  Fail "Provide exactly one experiment selector: -ExperimentName, -ExperimentMatch, or -Latest."
}

if ($PiHost -match '^(?<User>[^@]+)@(?<Host>.+)$') {
  if ([string]::IsNullOrWhiteSpace($PiUser) -or $PiUser -eq "labcraft") {
    $PiUser = $Matches.User
  }
  $PiHost = $Matches.Host
}

$RepoRoot = Get-RepoRoot
$LocalRootAbs = Resolve-AbsolutePathString -PathValue $LocalRoot -BaseDir $RepoRoot
$RemoteExperimentsRoot = "$RemoteRepo/FreeRTOS-interface/Experiments"
$sshTarget = "${PiUser}@${PiHost}"

Write-Host "Resolving experiments from: $RemoteExperimentsRoot"
$experiments = Get-RemoteExperiments -Target $sshTarget -ExperimentsRoot $RemoteExperimentsRoot
$selected = Select-RemoteExperiment -Experiments $experiments -ExactName $ExperimentName -Substring $ExperimentMatch -UseLatest $Latest.IsPresent

$destDir = Join-UniqueDest -Root $LocalRootAbs -ExperimentBaseName $selected.Name
$predictedRecordingsRoot = Join-Path $destDir "calibration_recordings"
$predictedSelectedDir = if ((@($ProcessName).Count -gt 0) -or (@($RunId).Count -gt 0)) {
  Join-Path $destDir "selected_records"
} else {
  ""
}

$previewCommands = @(
  ".\env\Scripts\python.exe tools\replay_calibration_run.py --root `"$predictedRecordingsRoot`"",
  ".\env\Scripts\python.exe tools\replay_calibration_run.py --run-dir `"<run_dir>`""
)

if ($DryRun.IsPresent) {
  Write-Host ""
  Write-Host "=== Dry Run ==="
  Write-Host "SSH target: $sshTarget"
  Write-Host "Selected experiment: $($selected.Name)"
  Write-Host "Remote experiment path: $($selected.Path)"
  Write-Host "Local destination: $destDir"
  Write-Host "Copy mode: $CopyMode"
  if ($predictedSelectedDir) {
    Write-Host "Selected records destination: $predictedSelectedDir"
  }
  Write-Host "Suggested commands:"
  foreach ($cmd in $previewCommands) {
    Write-Host "  $cmd"
  }
  exit 0
}

New-Item -ItemType Directory -Force -Path $LocalRootAbs | Out-Null

if ($CopyMode -eq "WholeExperiment") {
  $stagingRoot = Join-Path $LocalRootAbs (".staging_" + [guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null
  try {
    Write-Host "Copying whole experiment from Pi..."
    Invoke-Scp -Arguments @("-r", (New-ScpRemoteSpec -Target $sshTarget -RemotePath $selected.Path), $stagingRoot)
    $copiedDir = Join-Path $stagingRoot $selected.Name
    if (-not (Test-Path $copiedDir)) {
      $dirs = @(Get-ChildItem $stagingRoot -Directory | Sort-Object Name)
      if ($dirs.Count -ne 1) {
        throw "Could not identify copied experiment directory under staging root."
      }
      $copiedDir = $dirs[0].FullName
    }
    Move-Item -Path $copiedDir -Destination $destDir
  } finally {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $stagingRoot
  }
} else {
  Write-Host "Copying calibration-only artifacts from Pi..."
  New-Item -ItemType Directory -Force -Path $destDir | Out-Null

  $remoteCalibrationJson = "$($selected.Path)/calibration.json"
  $remoteRecordings = "$($selected.Path)/calibration_recordings"
  $remoteExperimentDesign = "$($selected.Path)/experiment_design.json"

  if (Test-RemotePathExists -Target $sshTarget -RemotePath $remoteCalibrationJson -Kind "file") {
    Invoke-Scp -Arguments @((New-ScpRemoteSpec -Target $sshTarget -RemotePath $remoteCalibrationJson), $destDir)
  }
  if (Test-RemotePathExists -Target $sshTarget -RemotePath $remoteRecordings -Kind "dir") {
    Invoke-Scp -Arguments @("-r", (New-ScpRemoteSpec -Target $sshTarget -RemotePath $remoteRecordings), $destDir)
  }
  if (Test-RemotePathExists -Target $sshTarget -RemotePath $remoteExperimentDesign -Kind "file") {
    Invoke-Scp -Arguments @((New-ScpRemoteSpec -Target $sshTarget -RemotePath $remoteExperimentDesign), $destDir)
  }
}

$selectedDir = Materialize-SelectedRecords -ExperimentDir $destDir -ProcessFilters $ProcessName -RunFilters $RunId
$phaseSummary = Get-PhaseSummary -CalibrationFilePath (Join-Path $destDir "calibration.json")
$processInventory = Get-RecordingInventory -RecordingsRoot (Join-Path $destDir "calibration_recordings")
$selectedInventory = if ($selectedDir) {
  Get-RecordingInventory -RecordingsRoot (Join-Path $selectedDir "calibration_recordings")
} else {
  [ordered]@{}
}

$primaryReplayRoot = if ($selectedDir -and (Test-Path (Join-Path $selectedDir "calibration_recordings"))) {
  Join-Path $selectedDir "calibration_recordings"
} else {
  Join-Path $destDir "calibration_recordings"
}
$exampleRun = if ($selectedInventory.Count -gt 0) {
  Get-FirstRunPath -Inventory $selectedInventory
} else {
  Get-FirstRunPath -Inventory $processInventory
}

$suggestedCommands = @()
if (Test-Path $primaryReplayRoot) {
  $suggestedCommands += ".\env\Scripts\python.exe tools\replay_calibration_run.py --root `"$primaryReplayRoot`""
}
if ($exampleRun) {
  $suggestedCommands += ".\env\Scripts\python.exe tools\replay_calibration_run.py --run-dir `"$exampleRun`""
} else {
  $suggestedCommands += ".\env\Scripts\python.exe tools\replay_calibration_run.py --run-dir `"<run_dir>`""
}

$manifest = [ordered]@{
  schema_version = 1
  pulled_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
  copy_mode = $CopyMode
  dry_run = $false
  replay_requested = [bool]$Replay.IsPresent
  remote = [ordered]@{
    pi_host = $PiHost
    pi_user = $PiUser
    ssh_target = $sshTarget
    remote_repo = $RemoteRepo
    experiments_root = $RemoteExperimentsRoot
    selected_experiment_name = $selected.Name
    selected_experiment_path = $selected.Path
  }
  local = [ordered]@{
    root = $LocalRootAbs
    experiment_dir = $destDir
    selected_records_dir = if ($selectedDir) { $selectedDir } else { "" }
  }
  applied_filters = [ordered]@{
    process_name = @($ProcessName)
    run_id = @($RunId)
  }
  calibration_files = [ordered]@{
    calibration_json = [ordered]@{
      exists = [bool](Test-Path (Join-Path $destDir "calibration.json"))
      path = Join-Path $destDir "calibration.json"
    }
    calibration_recordings = [ordered]@{
      exists = [bool](Test-Path (Join-Path $destDir "calibration_recordings"))
      path = Join-Path $destDir "calibration_recordings"
    }
  }
  phase_summary = $phaseSummary
  process_inventory = $processInventory
  selected_process_inventory = $selectedInventory
  suggested_commands = @($suggestedCommands)
}

$manifestPath = Join-Path $destDir "pull_summary.json"
$manifest | ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 $manifestPath
Write-PullSummary -Manifest $manifest
Write-Host "Manifest written to: $manifestPath"

if ($Replay.IsPresent) {
  if (-not (Test-Path $primaryReplayRoot)) {
    Write-Warning "Replay requested, but no local calibration_recordings root was found."
    exit 0
  }

  $pythonExe = Get-PreferredPython -RepoRoot $RepoRoot
  if (-not $pythonExe) {
    Write-Warning "Replay requested, but no local Python interpreter was found. Run one of the suggested commands manually."
    exit 0
  }

  $replayScript = Join-Path $RepoRoot "tools\replay_calibration_run.py"
  Write-Host "Running replay analysis against: $primaryReplayRoot"
  if ($pythonExe -like "* -3") {
    $parts = $pythonExe -split " ", 2
    & $parts[0] $parts[1] $replayScript --root $primaryReplayRoot
  } else {
    & $pythonExe $replayScript --root $primaryReplayRoot
  }
}
