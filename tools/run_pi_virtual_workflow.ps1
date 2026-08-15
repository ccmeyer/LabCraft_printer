[CmdletBinding(DefaultParameterSetName = "Scenario")]
param(
  [Parameter(Mandatory = $true)]
  [string]$PiHost,

  [string]$PiUser = "labcraft",
  [string]$RemoteRepo = "/home/labcraft/LabCraft_printer",
  [Parameter(ParameterSetName = "Scenario")]
  [string]$HostLabel = "pi5-sil-primary-v1",

  [Parameter(ParameterSetName = "Scenario")]
  [ValidateSet(
    "virtual_print_array_96_v1",
    "virtual_print_array_384x10_v1",
    "calibration_storage_legacy_baseline_8x25_v1",
    "calibration_storage_shadow_8x25_v1"
  )]
  [string]$Scenario = "virtual_print_array_96_v1",

  [Parameter(Mandatory = $true, ParameterSetName = "Suite")]
  [ValidateSet("pi_primary", "pi_stress")]
  [string]$Suite,

  [Parameter(ParameterSetName = "Suite")]
  [ValidateRange(0, [int]::MaxValue)]
  [int]$Seed = 1,

  [Parameter(ParameterSetName = "Suite")]
  [switch]$ReplaySuite,

  [ValidateSet("offscreen", "minimal")]
  [string]$QtPlatform = "offscreen",

  [Parameter(ParameterSetName = "Scenario")]
  [int]$WarmupRuns = 1,
  [Parameter(ParameterSetName = "Scenario")]
  [int]$MeasuredRuns = 5,
  [double]$SpeedMultiplier = 1,
  [double]$TimeoutSeconds = 600,

  [switch]$PreflightOnly,
  [switch]$SafetyProofOnly,
  [Parameter(ParameterSetName = "Scenario")]
  [switch]$CreateCandidateBaseline,
  [Parameter(ParameterSetName = "Scenario")]
  [string]$BaselineDestination = "",
  [Parameter(ParameterSetName = "Scenario")]
  [string]$CompareBaseline = "",

  [string]$LocalArchiveRoot = "verification_reports/virtual_workflows/pi-pulls",
  [Parameter(ParameterSetName = "Scenario")]
  [switch]$KeepRemoteArtifacts,
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
    throw "Missing command '$Name'. Install/enable the Windows OpenSSH client."
  }
}

function ConvertTo-ShellLiteral([string]$Value) {
  return "'" + $Value.Replace("'", "'\''") + "'"
}

function Invoke-SshCapture(
  [string]$Target,
  [string]$Command,
  [int[]]$AllowedExitCodes = @(0)
) {
  $remoteCommand = "bash -lc " + (ConvertTo-ShellLiteral $Command)
  if ($DryRun.IsPresent) {
    Write-Host "DRY RUN ssh $Target $remoteCommand"
    return @()
  }
  $output = & ssh @script:SshCommonArguments $Target $remoteCommand 2>&1
  $exitCode = $LASTEXITCODE
  $script:LastSshExitCode = $exitCode
  $lines = @($output | ForEach-Object { $_.ToString() })
  foreach ($line in $lines) {
    Write-Host $line
  }
  if ($exitCode -notin $AllowedExitCodes) {
    $text = ($lines -join [Environment]::NewLine).Trim()
    throw "ssh failed ($exitCode): $text"
  }
  return ,$lines
}

function Invoke-Scp([string[]]$Arguments) {
  if ($DryRun.IsPresent) {
    Write-Host ("DRY RUN scp " + ($Arguments -join " "))
    return
  }
  & scp @script:SshCommonArguments @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "scp failed ($LASTEXITCODE)."
  }
}

function Get-RepoRoot() {
  return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Resolve-RepoPath([string]$Value, [string]$RepoRoot) {
  if ([System.IO.Path]::IsPathRooted($Value)) {
    return [System.IO.Path]::GetFullPath($Value)
  }
  return [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $Value))
}

function Get-PreferredPython([string]$RepoRoot) {
  foreach ($relative in @(
    "env\Scripts\python.exe",
    "venv\Scripts\python.exe",
    ".venv\Scripts\python.exe"
  )) {
    $candidate = Join-Path $RepoRoot $relative
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
      return $candidate
    }
  }
  throw "No repository-local Windows Python interpreter was found."
}

function Find-OutputPath([string[]]$Lines, [string]$Prefix) {
  $matches = @(
    $Lines |
      Where-Object { $_.StartsWith($Prefix, [StringComparison]::Ordinal) } |
      ForEach-Object { $_.Substring($Prefix.Length).Trim() }
  )
  if ($matches.Count -ne 1 -or [string]::IsNullOrWhiteSpace($matches[0])) {
    throw "Expected exactly one '$Prefix' output line."
  }
  return [string]$matches[0]
}

function New-RemoteCommand(
  [string]$RemoteRepoPath,
  [string[]]$Arguments
) {
  $changeDirectory = "cd " + (ConvertTo-ShellLiteral $RemoteRepoPath)
  $launcher = "bash scripts/pi/run_virtual_workflow_sil.sh"
  $argumentText = @($Arguments | ForEach-Object { ConvertTo-ShellLiteral $_ }) -join " "
  return $changeDirectory + " && " + $launcher + " " + $argumentText
}

if ($PSCmdlet.ParameterSetName -eq "Scenario" -and
    ($WarmupRuns -lt 0 -or $MeasuredRuns -lt 1)) {
  throw "WarmupRuns must be >= 0 and MeasuredRuns must be >= 1."
}
if ($SpeedMultiplier -le 0 -or $TimeoutSeconds -le 0) {
  throw "SpeedMultiplier and TimeoutSeconds must be positive."
}
if ($CreateCandidateBaseline.IsPresent -and [string]::IsNullOrWhiteSpace($BaselineDestination)) {
  throw "-CreateCandidateBaseline requires -BaselineDestination."
}
if (-not [string]::IsNullOrWhiteSpace($BaselineDestination) -and -not $CreateCandidateBaseline.IsPresent) {
  throw "-BaselineDestination requires -CreateCandidateBaseline."
}
if ($CreateCandidateBaseline.IsPresent -and ($WarmupRuns -lt 1 -or $MeasuredRuns -lt 5)) {
  throw "Candidate baseline creation requires at least one warm-up and five measured runs."
}
if ($PreflightOnly.IsPresent -and $SafetyProofOnly.IsPresent) {
  throw "-PreflightOnly and -SafetyProofOnly are mutually exclusive."
}

Require-Cmd "ssh"
Require-Cmd "scp"

$repoRoot = Get-RepoRoot
$python = Get-PreferredPython -RepoRoot $repoRoot
$target = if ($PiHost.Contains("@")) { $PiHost } else { "$PiUser@$PiHost" }
$collectionId = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$remoteOutputRoot = "$RemoteRepo/verification_reports/virtual_workflows/pi-sil"
$remoteSafetyRoot = "$remoteOutputRoot/pi-safety-$collectionId"
$remotePreflight = "$remoteSafetyRoot/preflight.json"
$remoteProof = "$remoteSafetyRoot/hardware_proof.json"
$remoteTrace = "$remoteSafetyRoot/hardware_access_trace.txt"

Write-Host "Pi SIL target: $target"
Write-Host "Remote repository: $RemoteRepo"
Write-Host "Collection id: $collectionId"
Write-Host "Qt platform: $QtPlatform"
if ($PSCmdlet.ParameterSetName -eq "Suite") {
  Write-Host "Suite: $Suite"
  Write-Host "Seed: $Seed"
} else {
  Write-Host "Scenario: $Scenario"
}

$preflightArgs = @(
  "preflight",
  "--output-root", $remoteOutputRoot,
  "--qt-platform", $QtPlatform,
  "--output", $remotePreflight
)
[void](Invoke-SshCapture -Target $target -Command (
  New-RemoteCommand -RemoteRepoPath $RemoteRepo -Arguments $preflightArgs
))
if ($PreflightOnly.IsPresent) {
  Write-Host "Pi SIL preflight completed: $remotePreflight"
  exit 0
}

$proofArgs = @(
  "prove",
  "--output-root", $remoteOutputRoot,
  "--qt-platform", $QtPlatform,
  "--preflight", $remotePreflight,
  "--output", $remoteProof
)
[void](Invoke-SshCapture -Target $target -Command (
  New-RemoteCommand -RemoteRepoPath $RemoteRepo -Arguments $proofArgs
))
if ($SafetyProofOnly.IsPresent) {
  Write-Host "Pi SIL safety proof completed: $remoteProof"
  exit 0
}

if ($PSCmdlet.ParameterSetName -eq "Suite") {
  $suiteCollectArgs = @(
    "collect",
    "--output-root", $remoteOutputRoot,
    "--qt-platform", $QtPlatform,
    "--preflight", $remotePreflight,
    "--proof", $remoteProof,
    "--",
    "--suite", $Suite,
    "--seed", $Seed.ToString([Globalization.CultureInfo]::InvariantCulture),
    "--speed-multiplier", $SpeedMultiplier.ToString([Globalization.CultureInfo]::InvariantCulture)
  )
  if ($PSBoundParameters.ContainsKey("TimeoutSeconds")) {
    $suiteCollectArgs += @(
      "--timeout-seconds",
      $TimeoutSeconds.ToString([Globalization.CultureInfo]::InvariantCulture)
    )
  }
  $suiteLines = Invoke-SshCapture -Target $target -Command (
    New-RemoteCommand -RemoteRepoPath $RemoteRepo -Arguments $suiteCollectArgs
  ) -AllowedExitCodes @(0, 2)

  if ($DryRun.IsPresent) {
    $remoteAggregates = @(
      "$remoteOutputRoot/$Suite/<run>/aggregate.json"
    )
    if ($ReplaySuite.IsPresent) {
      $replayArgs = @(
        "replay",
        "--output-root", $remoteOutputRoot,
        "--aggregate", $remoteAggregates[0]
      )
      [void](Invoke-SshCapture -Target $target -Command (
        New-RemoteCommand -RemoteRepoPath $RemoteRepo -Arguments $replayArgs
      ) -AllowedExitCodes @(0, 2))
      $remoteAggregates += "$remoteOutputRoot/$Suite/<replay>/aggregate.json"
    }
    $dryBundle = "$remoteOutputRoot/bundles/pi-suite-$collectionId.zip"
    $dryBundleArgs = @(
      "bundle",
      "--output-root", $remoteOutputRoot,
      "--proof", $remoteProof,
      "--trace", $remoteTrace,
      "--output", $dryBundle
    )
    foreach ($aggregatePath in $remoteAggregates) {
      $dryBundleArgs += @("--aggregate", $aggregatePath)
    }
    [void](Invoke-SshCapture -Target $target -Command (
      New-RemoteCommand -RemoteRepoPath $RemoteRepo -Arguments $dryBundleArgs
    ))
    Invoke-Scp -Arguments @("${target}:$dryBundle", $LocalArchiveRoot)
    Write-Host "Dry run complete; no remote operation, artifact, or cleanup occurred."
    exit 0
  }

  $suiteExit = $script:LastSshExitCode
  $remoteAggregates = @(
    (Find-OutputPath -Lines $suiteLines -Prefix "Aggregate:")
  )
  if ($ReplaySuite.IsPresent) {
    $replayArgs = @(
      "replay",
      "--output-root", $remoteOutputRoot,
      "--aggregate", $remoteAggregates[0]
    )
    $replayLines = Invoke-SshCapture -Target $target -Command (
      New-RemoteCommand -RemoteRepoPath $RemoteRepo -Arguments $replayArgs
    ) -AllowedExitCodes @(0, 2)
    $replayExit = $script:LastSshExitCode
    $remoteAggregates += Find-OutputPath -Lines $replayLines -Prefix "Aggregate:"
    if ($replayExit -eq 2) {
      $suiteExit = 2
    }
  }

  $remoteBundle = "$remoteOutputRoot/bundles/pi-suite-$collectionId.zip"
  $bundleArgs = @(
    "bundle",
    "--output-root", $remoteOutputRoot,
    "--proof", $remoteProof,
    "--trace", $remoteTrace,
    "--output", $remoteBundle
  )
  foreach ($aggregatePath in $remoteAggregates) {
    $bundleArgs += @("--aggregate", $aggregatePath)
  }
  [void](Invoke-SshCapture -Target $target -Command (
    New-RemoteCommand -RemoteRepoPath $RemoteRepo -Arguments $bundleArgs
  ))

  $localArchiveRootAbs = Resolve-RepoPath -Value $LocalArchiveRoot -RepoRoot $repoRoot
  New-Item -ItemType Directory -Force -Path $localArchiveRootAbs | Out-Null
  $localArchive = Join-Path $localArchiveRootAbs ([IO.Path]::GetFileName($remoteBundle))
  $localManifest = "$localArchive.manifest.json"
  $localHash = "$localArchive.sha256.json"
  foreach ($path in @($localArchive, $localManifest, $localHash)) {
    if (Test-Path -LiteralPath $path) {
      throw "Refusing to overwrite local Pi SIL suite artifact: $path"
    }
  }
  Invoke-Scp -Arguments @("${target}:$remoteBundle", $localArchive)
  Invoke-Scp -Arguments @("${target}:$remoteBundle.manifest.json", $localManifest)
  Invoke-Scp -Arguments @("${target}:$remoteBundle.sha256.json", $localHash)
  $expectedHash = [string]((Get-Content -LiteralPath $localHash -Raw | ConvertFrom-Json).sha256)
  $actualHash = (Get-FileHash -LiteralPath $localArchive -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actualHash -ne $expectedHash.ToLowerInvariant()) {
    throw "Retrieved Pi SIL suite archive SHA-256 does not match the remote sidecar."
  }
  & $python -m tools.virtual_workflows.pi_sil extract `
    --archive $localArchive `
    --manifest $localManifest `
    --destination $repoRoot
  if ($LASTEXITCODE -ne 0) {
    throw "Local Pi SIL suite artifact extraction/validation failed ($LASTEXITCODE)."
  }
  $manifest = Get-Content -LiteralPath $localManifest -Raw | ConvertFrom-Json
  foreach ($relative in @($manifest.aggregate_paths)) {
    $localAggregate = Join-Path $repoRoot ([string]$relative)
    $aggregateHash = (Get-FileHash -LiteralPath $localAggregate -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "Retrieved aggregate: $localAggregate"
    Write-Host "Retrieved aggregate SHA-256: $aggregateHash"
  }
  Write-Host "Retrieved suite bundle: $localArchive"
  Write-Host "Retrieved suite bundle SHA-256: $actualHash"
  Write-Host "Remote suite evidence retained: $remoteOutputRoot"
  if ($suiteExit -eq 2) {
    exit 2
  }
  Write-Host "Pi SIL suite collection, replay, and artifact validation completed."
  exit 0
}

$remoteBaseline = "$remoteSafetyRoot/candidate_baseline.json"
$collectArgs = @(
  "collect",
  "--output-root", $remoteOutputRoot,
  "--qt-platform", $QtPlatform,
  "--preflight", $remotePreflight,
  "--proof", $remoteProof,
  "--",
  "--scenario", $Scenario,
  "--speed-multiplier", $SpeedMultiplier.ToString([Globalization.CultureInfo]::InvariantCulture),
  "--timeout-seconds", $TimeoutSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
  "--warmup-runs", $WarmupRuns.ToString([Globalization.CultureInfo]::InvariantCulture),
  "--measured-runs", $MeasuredRuns.ToString([Globalization.CultureInfo]::InvariantCulture),
  "--host-label", $HostLabel,
  "--emit-report-set"
)
if ($CreateCandidateBaseline.IsPresent) {
  $collectArgs += @(
    "--accept-baseline", $remoteBaseline,
    "--threshold-maturity", "candidate"
  )
}
$collectionLines = Invoke-SshCapture -Target $target -Command (
  New-RemoteCommand -RemoteRepoPath $RemoteRepo -Arguments $collectArgs
)
if ($DryRun.IsPresent) {
  Write-Host "Dry run complete; no artifacts were created or copied."
  exit 0
}
$remoteReportSet = Find-OutputPath -Lines $collectionLines -Prefix "Report set:"

$remoteBundle = "$remoteOutputRoot/bundles/pi-sil-$collectionId.zip"
$bundleArgs = @(
  "bundle",
  "--output-root", $remoteOutputRoot,
  "--report-set", $remoteReportSet,
  "--proof", $remoteProof,
  "--trace", $remoteTrace,
  "--output", $remoteBundle
)
[void](Invoke-SshCapture -Target $target -Command (
  New-RemoteCommand -RemoteRepoPath $RemoteRepo -Arguments $bundleArgs
))

$localArchiveRootAbs = Resolve-RepoPath -Value $LocalArchiveRoot -RepoRoot $repoRoot
New-Item -ItemType Directory -Force -Path $localArchiveRootAbs | Out-Null
$localArchive = Join-Path $localArchiveRootAbs ([IO.Path]::GetFileName($remoteBundle))
$localManifest = "$localArchive.manifest.json"
$localHash = "$localArchive.sha256.json"
if (Test-Path -LiteralPath $localArchive) {
  throw "Refusing to overwrite local Pi SIL archive: $localArchive"
}

Invoke-Scp -Arguments @("${target}:$remoteBundle", $localArchive)
Invoke-Scp -Arguments @("${target}:$remoteBundle.manifest.json", $localManifest)
Invoke-Scp -Arguments @("${target}:$remoteBundle.sha256.json", $localHash)

$expectedHash = [string]((Get-Content -LiteralPath $localHash -Raw | ConvertFrom-Json).sha256)
$actualHash = (Get-FileHash -LiteralPath $localArchive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $expectedHash.ToLowerInvariant()) {
  throw "Retrieved Pi SIL archive SHA-256 does not match the remote sidecar."
}

& $python -m tools.virtual_workflows.pi_sil extract `
  --archive $localArchive `
  --manifest $localManifest `
  --destination $repoRoot
if ($LASTEXITCODE -ne 0) {
  throw "Local Pi SIL artifact extraction/validation failed ($LASTEXITCODE)."
}

$manifest = Get-Content -LiteralPath $localManifest -Raw | ConvertFrom-Json
$localReportSet = Join-Path $repoRoot ([string]$manifest.report_set_path)
Write-Host "Retrieved report set: $localReportSet"

if ($CreateCandidateBaseline.IsPresent) {
  $localBaselineDestination = Resolve-RepoPath -Value $BaselineDestination -RepoRoot $repoRoot
  if (Test-Path -LiteralPath $localBaselineDestination) {
    throw "Refusing to overwrite candidate baseline: $localBaselineDestination"
  }
  $baselineParent = Split-Path -Parent $localBaselineDestination
  New-Item -ItemType Directory -Force -Path $baselineParent | Out-Null
  $temporaryBaseline = Join-Path $localArchiveRootAbs "candidate_baseline_$collectionId.json"
  Invoke-Scp -Arguments @("${target}:$remoteBaseline", $temporaryBaseline)
  & $python -m tools.virtual_workflows.pi_sil install-baseline `
    --source $temporaryBaseline `
    --destination $localBaselineDestination
  if ($LASTEXITCODE -ne 0) {
    throw "Candidate baseline validation/install failed ($LASTEXITCODE)."
  }
  Write-Host "Candidate baseline: $localBaselineDestination"
}

if (-not [string]::IsNullOrWhiteSpace($CompareBaseline)) {
  $comparePath = Resolve-RepoPath -Value $CompareBaseline -RepoRoot $repoRoot
  & $python tools\run_virtual_workflow.py --compare $comparePath $localReportSet
  $comparisonExit = $LASTEXITCODE
  if ($comparisonExit -notin @(0, 4)) {
    throw "Pi SIL comparison failed ($comparisonExit)."
  }
  if ($comparisonExit -eq 4) {
    exit 4
  }
}

if (-not $KeepRemoteArtifacts.IsPresent) {
  $cleanupArgs = @(
    "cleanup",
    "--output-root", $remoteOutputRoot,
    "--manifest", "$remoteBundle.manifest.json"
  )
  [void](Invoke-SshCapture -Target $target -Command (
    New-RemoteCommand -RemoteRepoPath $RemoteRepo -Arguments $cleanupArgs
  ))
}

Write-Host "Pi SIL collection and artifact validation completed."
