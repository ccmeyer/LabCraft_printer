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
  [switch]$PreserveExperimentName,
  [switch]$IncludeDropletImagerCaptures,
  [string[]]$ProcessName = @(),
  [string[]]$RunId = @(),

  [switch]$Replay,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$script:SshCommonArguments = @(
  "-o", "ServerAliveInterval=15",
  "-o", "ServerAliveCountMax=8",
  "-o", "TCPKeepAlive=yes"
)

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

function Join-UniqueDest([string]$Root, [string]$ExperimentBaseName, [bool]$PreserveName = $false) {
  $safeBaseName = Sanitize-FileComponent $ExperimentBaseName
  if ($PreserveName) {
    $candidate = Join-Path $Root $safeBaseName
    if (-not (Test-Path $candidate)) {
      return $candidate
    }
    $suffix = [guid]::NewGuid().ToString("N").Substring(0, 6)
    return Join-Path $Root "${safeBaseName}_$suffix"
  }

  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $base = "${stamp}_$safeBaseName"
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
  $output = & ssh @script:SshCommonArguments $Target $remoteCommand 2>&1
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    $text = (($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()
    throw "ssh failed ($exitCode): $text"
  }
  return ,@($output | ForEach-Object { $_.ToString() })
}

function Invoke-Scp([string[]]$Arguments) {
  & scp @script:SshCommonArguments @Arguments
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    throw "scp failed ($exitCode). See console output above."
  }
}

function Read-JsonFileOrNull([string]$PathValue) {
  if (-not (Test-Path $PathValue)) {
    return $null
  }

  try {
    return Get-Content $PathValue -Raw | ConvertFrom-Json
  } catch {
    return $null
  }
}

function Write-JsonFile([object]$Value, [string]$PathValue, [int]$Depth = 12) {
  $Value | ConvertTo-Json -Depth $Depth | Set-Content -Encoding UTF8 $PathValue
}

function Get-StableExperimentDestination([string]$Root, [string]$ExperimentBaseName) {
  return Join-Path $Root (Sanitize-FileComponent $ExperimentBaseName)
}

function Get-RelativePathString([string]$BasePath, [string]$TargetPath) {
  $baseFull = [System.IO.Path]::GetFullPath($BasePath)
  $targetFull = [System.IO.Path]::GetFullPath($TargetPath)
  if (-not $baseFull.EndsWith([string][System.IO.Path]::DirectorySeparatorChar)) {
    $baseFull += [System.IO.Path]::DirectorySeparatorChar
  }

  $baseUri = New-Object System.Uri($baseFull)
  $targetUri = New-Object System.Uri($targetFull)
  $relativeUri = $baseUri.MakeRelativeUri($targetUri)
  return [System.Uri]::UnescapeDataString($relativeUri.ToString()).Replace('/', '\')
}

function Format-ByteSize([Int64]$Bytes) {
  $suffixes = @("B", "KB", "MB", "GB", "TB")
  $size = [double]$Bytes
  $suffixIndex = 0
  while ($size -ge 1024 -and $suffixIndex -lt ($suffixes.Count - 1)) {
    $size /= 1024
    $suffixIndex += 1
  }

  if ($suffixIndex -eq 0) {
    return ("{0} {1}" -f [Int64]$Bytes, $suffixes[$suffixIndex])
  }
  return ("{0:N1} {1}" -f $size, $suffixes[$suffixIndex])
}

function Get-PropertySum([object[]]$Items, [string]$PropertyName) {
  $sum = [Int64]0
  foreach ($item in @($Items)) {
    if ($null -eq $item) {
      continue
    }

    $prop = $item.PSObject.Properties[$PropertyName]
    if ($null -eq $prop) {
      continue
    }

    $value = $prop.Value
    if ($null -eq $value) {
      continue
    }

    $sum += [Int64]$value
  }
  return $sum
}

function Get-WholeExperimentExclusions([bool]$IncludeDropletImages = $false) {
  if ($IncludeDropletImages) {
    return @()
  }
  return @("droplet_imager_captures")
}

function Find-ExistingWholeExperimentDestination([string]$Root, [string]$RemoteExperimentPath) {
  if (-not (Test-Path $Root)) {
    return $null
  }

  $candidates = @()
  foreach ($dir in (Get-ChildItem $Root -Directory -ErrorAction SilentlyContinue)) {
    $statePath = Join-Path $dir.FullName "pull_state.json"
    if (-not (Test-Path $statePath)) {
      continue
    }

    $state = Read-JsonFileOrNull -PathValue $statePath
    if ($null -eq $state) {
      continue
    }

    if ([string]$state.copy_mode -ne "WholeExperiment") {
      continue
    }

    $selectedPath = [string](($state.remote).selected_experiment_path)
    if ($selectedPath -ne $RemoteExperimentPath) {
      continue
    }

    $candidates += [pscustomobject]@{
      Path = $dir.FullName
      Status = [string]$state.status
      UpdatedUtc = (Get-Item $statePath).LastWriteTimeUtc
    }
  }

  if ($candidates.Count -eq 0) {
    return $null
  }

  $pending = @($candidates | Where-Object { $_.Status -ne "completed" } | Sort-Object UpdatedUtc -Descending)
  if ($pending.Count -gt 0) {
    return $pending[0].Path
  }
  return $null
}

function Get-RemoteExperimentManifest([string]$Target, [string]$ExperimentPath, [string[]]$ExcludeTopLevelDirs = @()) {
  $rootLit = ConvertTo-ShellLiteral $ExperimentPath
  $findExpr = "\( -type d -printf 'D|%P|0\n' -o -type f -printf 'F|%P|%s\n' \)"

  $excludeNames = @($ExcludeTopLevelDirs | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique)
  if ($excludeNames.Count -gt 0) {
    $pruneTerms = @()
    foreach ($name in $excludeNames) {
      $pruneTerms += "-path " + (ConvertTo-ShellLiteral "./$name")
      $pruneTerms += "-path " + (ConvertTo-ShellLiteral "./$name/*")
    }
    $findExpr = "\( " + ($pruneTerms -join " -o ") + " \) -prune -o " + $findExpr
  }

  $cmd = @(
    "if [ ! -d $rootLit ]; then"
    "  echo '__MISSING_ROOT__';"
    "  exit 3;"
    "fi;"
    "cd $rootLit;"
    "find . $findExpr | sort"
  ) -join " "

  $lines = Invoke-SshCapture -Target $Target -Command $cmd
  if (($lines.Count -eq 1) -and ($lines[0].Trim() -eq "__MISSING_ROOT__")) {
    throw "Remote experiment directory not found: $ExperimentPath"
  }

  $entries = @()
  foreach ($line in $lines) {
    $trimmed = $line.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed)) {
      continue
    }

    $parts = $trimmed -split "\|", 3
    if ($parts.Count -lt 3) {
      continue
    }

    $relativePath = [string]$parts[1]
    if ([string]::IsNullOrWhiteSpace($relativePath)) {
      continue
    }

    $size = [Int64]0
    [void][Int64]::TryParse([string]$parts[2], [ref]$size)
    $entries += [pscustomobject]@{
      EntryType = if ($parts[0] -eq "D") { "dir" } else { "file" }
      RelativePath = $relativePath.Replace('\', '/')
      Size = [Int64]$size
    }
  }
  return ,@($entries)
}

function New-CopyUnit([string]$RelativePath, [string]$Kind) {
  return [pscustomobject][ordered]@{
    relative_path = $RelativePath
    kind = $Kind
    file_count = 0
    total_bytes = [Int64]0
    status = "pending"
    completed_utc = ""
    last_error = ""
  }
}

function Get-CopyUnitDescriptor([string]$RelativePath, [string]$EntryType) {
  $normalized = $RelativePath.Replace('\', '/').Trim()
  $normalized = $normalized.TrimStart('.')
  $normalized = $normalized.Trim('/')
  if ([string]::IsNullOrWhiteSpace($normalized)) {
    return $null
  }

  $parts = @($normalized -split "/")
  $isDir = ($EntryType -eq "dir")

  if ($parts[0] -ne "calibration_recordings") {
    if ($parts.Count -eq 1) {
      return [pscustomobject]@{
        RelativePath = $normalized
        Kind = if ($isDir) { "dir" } else { "file" }
      }
    }

    return [pscustomobject]@{
      RelativePath = $parts[0]
      Kind = "dir"
    }
  }

  if ($parts.Count -eq 1) {
    if ($isDir) {
      return $null
    }
    return [pscustomobject]@{
      RelativePath = $normalized
      Kind = "file"
    }
  }

  if ($parts.Count -eq 2) {
    return [pscustomobject]@{
      RelativePath = $normalized
      Kind = if ($isDir) { "dir" } else { "file" }
    }
  }

  if ($parts[2] -like "run_*") {
    return [pscustomobject]@{
      RelativePath = ($parts[0..2] -join "/")
      Kind = "dir"
    }
  }

  if ($parts.Count -eq 3) {
    return [pscustomobject]@{
      RelativePath = $normalized
      Kind = if ($isDir) { "dir" } else { "file" }
    }
  }

  return [pscustomobject]@{
    RelativePath = ($parts[0..2] -join "/")
    Kind = "dir"
  }
}

function Get-WholeExperimentCopyUnits([object[]]$Entries) {
  $unitMap = @{}

  foreach ($entry in @($Entries)) {
    $descriptor = Get-CopyUnitDescriptor -RelativePath ([string]$entry.RelativePath) -EntryType ([string]$entry.EntryType)
    if ($null -eq $descriptor) {
      continue
    }

    $key = [string]$descriptor.RelativePath
    if (-not $unitMap.ContainsKey($key)) {
      $unitMap[$key] = New-CopyUnit -RelativePath $key -Kind ([string]$descriptor.Kind)
    }

    if ([string]$entry.EntryType -eq "file") {
      $unitMap[$key].file_count = [int]$unitMap[$key].file_count + 1
      $unitMap[$key].total_bytes = [Int64]$unitMap[$key].total_bytes + [Int64]$entry.Size
    }
  }

  $keys = @($unitMap.Keys | Sort-Object { $_.Length })
  foreach ($key in $keys) {
    if (-not $unitMap.ContainsKey($key)) {
      continue
    }

    $unit = $unitMap[$key]
    if ([string]$unit.kind -ne "dir") {
      continue
    }

    $hasChildUnit = $false
    $prefix = "$key/"
    foreach ($otherKey in @($unitMap.Keys)) {
      if ($otherKey -ne $key -and $otherKey.StartsWith($prefix)) {
        $hasChildUnit = $true
        break
      }
    }

    if ($hasChildUnit) {
      [void]$unitMap.Remove($key)
    }
  }

  $units = @(
    $unitMap.Values |
      Sort-Object @{ Expression = { if ([string]$_.kind -eq "file") { 0 } else { 1 } } }, @{ Expression = { $_.relative_path } }
  )
  return ,@($units)
}

function Get-LocalUnitStats([string]$ExperimentDir) {
  $stats = @{}
  if (-not (Test-Path $ExperimentDir)) {
    return $stats
  }

  foreach ($file in (Get-ChildItem $ExperimentDir -Recurse -File -ErrorAction SilentlyContinue)) {
    $relativePath = (Get-RelativePathString -BasePath $ExperimentDir -TargetPath $file.FullName).Replace('\', '/')
    $descriptor = Get-CopyUnitDescriptor -RelativePath $relativePath -EntryType "file"
    if ($null -eq $descriptor) {
      continue
    }

    $key = [string]$descriptor.RelativePath
    if (-not $stats.ContainsKey($key)) {
      $stats[$key] = [ordered]@{
        file_count = 0
        total_bytes = [Int64]0
      }
    }

    $stats[$key].file_count = [int]$stats[$key].file_count + 1
    $stats[$key].total_bytes = [Int64]$stats[$key].total_bytes + [Int64]$file.Length
  }
  return $stats
}

function Test-CopyUnitComplete([object]$Unit, [string]$ExperimentDir, [hashtable]$LocalStats) {
  $localPath = Join-Path $ExperimentDir ($Unit.relative_path.Replace('/', '\'))
  if ([string]$Unit.kind -eq "file") {
    if (-not (Test-Path $localPath -PathType Leaf)) {
      return $false
    }
    return ([Int64](Get-Item $localPath).Length -eq [Int64]$Unit.total_bytes)
  }

  if (-not (Test-Path $localPath -PathType Container)) {
    return $false
  }

  if ([int]$Unit.file_count -eq 0) {
    return $true
  }

  if (-not $LocalStats.ContainsKey([string]$Unit.relative_path)) {
    return $false
  }

  $local = $LocalStats[[string]$Unit.relative_path]
  return (
    ([int]$local.file_count -eq [int]$Unit.file_count) -and
    ([Int64]$local.total_bytes -eq [Int64]$Unit.total_bytes)
  )
}

function Update-CopyUnitStatuses([object[]]$Units, [string]$ExperimentDir, [hashtable]$LocalStats) {
  foreach ($unit in @($Units)) {
    if (Test-CopyUnitComplete -Unit $unit -ExperimentDir $ExperimentDir -LocalStats $LocalStats) {
      $unit.status = "completed"
      $unit.last_error = ""
    } else {
      $unit.status = "pending"
      $unit.completed_utc = ""
    }
  }
}

function Set-CopyStateProgress([System.Collections.IDictionary]$State, [object[]]$Units) {
  $completedUnits = 0
  $pendingUnits = 0
  foreach ($unit in @($Units)) {
    if ([string]$unit.status -eq "completed") {
      $completedUnits += 1
    } else {
      $pendingUnits += 1
    }
  }

  $State.plan.completed_units = $completedUnits
  $State.plan.pending_units = $pendingUnits
}

function Write-PullState([System.Collections.IDictionary]$State, [string]$StatePath) {
  Write-JsonFile -Value $State -PathValue $StatePath -Depth 14
}

function Invoke-CopyUnit(
  [string]$Target,
  [string]$RemoteExperimentPath,
  [string]$LocalExperimentPath,
  [object]$Unit,
  [int]$Index,
  [int]$TotalUnits,
  [Int64]$CompletedBytes,
  [Int64]$TotalBytes
) {
  $relativePathWin = $Unit.relative_path.Replace('/', '\')
  $localTarget = Join-Path $LocalExperimentPath $relativePathWin
  $localParent = Split-Path -Parent $localTarget
  if (-not [string]::IsNullOrWhiteSpace($localParent)) {
    New-Item -ItemType Directory -Force -Path $localParent | Out-Null
  }

  $progressPct = if ($TotalBytes -gt 0) { [math]::Round(($CompletedBytes * 100.0) / $TotalBytes, 1) } else { 100.0 }
  $copyVerb = if ([string]$Unit.kind -eq "file") { "Copying file" } else { "Copying directory" }
  Write-Host ("[{0}/{1}] {2} {3} ({4}, {5} files)" -f $Index, $TotalUnits, $copyVerb, $Unit.relative_path, (Format-ByteSize ([Int64]$Unit.total_bytes)), [int]$Unit.file_count)
  Write-Host ("  Overall completed before this unit: {0}/{1} ({2}%)" -f (Format-ByteSize $CompletedBytes), (Format-ByteSize $TotalBytes), $progressPct)

  $remotePath = "$RemoteExperimentPath/$($Unit.relative_path)"
  if ([string]$Unit.kind -eq "file") {
    Invoke-Scp -Arguments @((New-ScpRemoteSpec -Target $Target -RemotePath $remotePath), $localParent)
    return
  }

  Invoke-Scp -Arguments @("-r", (New-ScpRemoteSpec -Target $Target -RemotePath $remotePath), $localParent)
}

function Invoke-WholeExperimentCopy(
  [string]$Target,
  [object]$SelectedExperiment,
  [string]$DestinationDir,
  [string[]]$ExcludedPaths = @(),
  [bool]$DryRun = $false
) {
  Write-Host "Building remote copy plan..."
  $entries = Get-RemoteExperimentManifest -Target $Target -ExperimentPath ([string]$SelectedExperiment.Path) -ExcludeTopLevelDirs $ExcludedPaths
  $units = Get-WholeExperimentCopyUnits -Entries $entries
  $totalBytes = Get-PropertySum -Items $units -PropertyName "total_bytes"
  $totalFiles = [int](Get-PropertySum -Items $units -PropertyName "file_count")

  $localStats = Get-LocalUnitStats -ExperimentDir $DestinationDir
  Update-CopyUnitStatuses -Units $units -ExperimentDir $DestinationDir -LocalStats $localStats

  $statePath = Join-Path $DestinationDir "pull_state.json"
  $state = [ordered]@{
    schema_version = 2
    updated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    status = "in_progress"
    copy_mode = "WholeExperiment"
    excluded_paths = @($ExcludedPaths)
    remote = [ordered]@{
      selected_experiment_name = [string]$SelectedExperiment.Name
      selected_experiment_path = [string]$SelectedExperiment.Path
    }
    local = [ordered]@{
      experiment_dir = $DestinationDir
      state_path = $statePath
    }
    plan = [ordered]@{
      unit_count = $units.Count
      total_files = $totalFiles
      total_bytes = $totalBytes
      completed_units = 0
      pending_units = 0
    }
    units = @($units)
  }
  Set-CopyStateProgress -State $state -Units $units

  if ($DryRun) {
    return [pscustomobject]@{
      Entries = $entries
      Units = $units
      State = $state
      StatePath = $statePath
      TotalBytes = $totalBytes
      TotalFiles = $totalFiles
    }
  }

  New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
  Write-PullState -State $state -StatePath $statePath

  $totalUnits = $units.Count
  $completedUnits = @($units | Where-Object { [string]$_.status -eq "completed" })
  $completedBytes = Get-PropertySum -Items $completedUnits -PropertyName "total_bytes"
  $index = 0

  foreach ($unit in @($units)) {
    $index += 1
    if ([string]$unit.status -eq "completed") {
      Write-Host ("[{0}/{1}] Skipping completed {2}: {3}" -f $index, $totalUnits, [string]$unit.kind, [string]$unit.relative_path)
      continue
    }

    try {
      Invoke-CopyUnit -Target $Target -RemoteExperimentPath ([string]$SelectedExperiment.Path) -LocalExperimentPath $DestinationDir -Unit $unit -Index $index -TotalUnits $totalUnits -CompletedBytes $completedBytes -TotalBytes $totalBytes
      $unit.status = "completed"
      $unit.completed_utc = [DateTimeOffset]::UtcNow.ToString("o")
      $unit.last_error = ""
      $completedBytes = [Int64]$completedBytes + [Int64]$unit.total_bytes
    } catch {
      $unit.status = "failed"
      $unit.last_error = $_.Exception.Message
      $state.updated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
      $state.status = "in_progress"
      Set-CopyStateProgress -State $state -Units $units
      Write-PullState -State $state -StatePath $statePath
      throw
    }

    $state.updated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
    $state.status = "in_progress"
    Set-CopyStateProgress -State $state -Units $units
    Write-PullState -State $state -StatePath $statePath
  }

  $state.updated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
  $state.status = "completed"
  Set-CopyStateProgress -State $state -Units $units
  Write-PullState -State $state -StatePath $statePath

  return [pscustomobject]@{
    Entries = $entries
    Units = $units
    State = $state
    StatePath = $statePath
    TotalBytes = $totalBytes
    TotalFiles = $totalFiles
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

  $hasWildcard = $Substring.IndexOfAny([char[]]@('*', '?', '[')) -ge 0
  $pattern = if ($hasWildcard) { $Substring } else { "*$Substring*" }
  $matchLabel = if ($hasWildcard) { "pattern" } else { "substring" }

  $matches = @($Experiments | Where-Object { $_.Name -like $pattern })
  if ($matches.Count -eq 0) {
    throw "No experiments matched $matchLabel '$Substring'."
  }
  if ($matches.Count -gt 1) {
    $candidates = $matches | ForEach-Object { $_.Name } | Sort-Object
    throw ("Experiment $matchLabel '$Substring' was ambiguous. Candidates: " + ($candidates -join ", "))
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
  if ($Manifest.copy_plan) {
    if (@($Manifest.copy_plan.excluded_paths).Count -gt 0) {
      Write-Host "Excluded paths: $(@($Manifest.copy_plan.excluded_paths) -join ', ')"
    }
    if ([int]$Manifest.copy_plan.total_units -gt 0) {
      Write-Host "Copy units: $($Manifest.copy_plan.completed_units)/$($Manifest.copy_plan.total_units) complete"
      Write-Host "Planned payload: $(Format-ByteSize ([Int64]$Manifest.copy_plan.total_bytes)) across $($Manifest.copy_plan.total_files) files"
    }
  }
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

$wholeExperimentExclusions = if ($CopyMode -eq "WholeExperiment") {
  Get-WholeExperimentExclusions -IncludeDropletImages $IncludeDropletImagerCaptures.IsPresent
} else {
  @()
}

$wholeExperimentResume = $false
if ($CopyMode -eq "WholeExperiment") {
  if ($PreserveExperimentName.IsPresent) {
    $destDir = Get-StableExperimentDestination -Root $LocalRootAbs -ExperimentBaseName $selected.Name
    $wholeExperimentResume = (Test-Path $destDir)
  } else {
    $resumeDest = Find-ExistingWholeExperimentDestination -Root $LocalRootAbs -RemoteExperimentPath $selected.Path
    if ($resumeDest) {
      $destDir = $resumeDest
      $wholeExperimentResume = $true
    } else {
      $destDir = Join-UniqueDest -Root $LocalRootAbs -ExperimentBaseName $selected.Name -PreserveName $false
    }
  }
} else {
  $destDir = Join-UniqueDest -Root $LocalRootAbs -ExperimentBaseName $selected.Name -PreserveName $PreserveExperimentName.IsPresent
}

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
  if ($wholeExperimentResume) {
    Write-Host "Resume existing pull: yes"
  }
  if ($CopyMode -eq "WholeExperiment" -and @($wholeExperimentExclusions).Count -gt 0) {
    Write-Host "Excluded paths: $($wholeExperimentExclusions -join ', ')"
  }
  if ($predictedSelectedDir) {
    Write-Host "Selected records destination: $predictedSelectedDir"
  }
  if ($CopyMode -eq "WholeExperiment") {
    $dryRunPlan = Invoke-WholeExperimentCopy -Target $sshTarget -SelectedExperiment $selected -DestinationDir $destDir -ExcludedPaths $wholeExperimentExclusions -DryRun $true
    Write-Host "Copy units: $($dryRunPlan.State.plan.completed_units)/$($dryRunPlan.State.plan.unit_count) complete"
    Write-Host "Planned payload: $(Format-ByteSize ([Int64]$dryRunPlan.TotalBytes)) across $($dryRunPlan.TotalFiles) files"
  }
  Write-Host "Suggested commands:"
  foreach ($cmd in $previewCommands) {
    Write-Host "  $cmd"
  }
  exit 0
}

New-Item -ItemType Directory -Force -Path $LocalRootAbs | Out-Null

$wholeCopyResult = $null
if ($CopyMode -eq "WholeExperiment") {
  if ($wholeExperimentResume) {
    Write-Host "Resuming whole experiment copy from Pi..."
  } else {
    Write-Host "Copying whole experiment from Pi..."
  }
  $wholeCopyResult = Invoke-WholeExperimentCopy -Target $sshTarget -SelectedExperiment $selected -DestinationDir $destDir -ExcludedPaths $wholeExperimentExclusions
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

$copyPlanSummary = if ($wholeCopyResult) {
  [ordered]@{
    excluded_paths = @($wholeExperimentExclusions)
    state_path = $wholeCopyResult.StatePath
    total_units = [int]$wholeCopyResult.State.plan.unit_count
    completed_units = [int]$wholeCopyResult.State.plan.completed_units
    pending_units = [int]$wholeCopyResult.State.plan.pending_units
    total_files = [int]$wholeCopyResult.State.plan.total_files
    total_bytes = [Int64]$wholeCopyResult.State.plan.total_bytes
  }
} else {
  [ordered]@{
    excluded_paths = @()
    state_path = ""
    total_units = 0
    completed_units = 0
    pending_units = 0
    total_files = 0
    total_bytes = [Int64]0
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
  schema_version = 2
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
    state_path = [string]$copyPlanSummary.state_path
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
  copy_plan = $copyPlanSummary
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
