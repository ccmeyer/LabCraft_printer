param(
  [string]$Config = "Debug"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Require-Command($name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "ERROR: '$name' was not found on PATH."
    Write-Host "Install it, then restart VS Code/PowerShell and retry."
    Write-Host "Suggested: winget install Kitware.CMake"
    exit 3
  }
}

function Require-Success($label) {
  if ($LASTEXITCODE -ne 0) {
    throw "$label failed with exit code $LASTEXITCODE"
  }
}

Require-Command "cmake"

# Make script independent of where it's called from:
# This script lives at firmware/scripts, so repo root is two levels up.
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Push-Location $repoRoot

try {
  # Ensure submodule exists
  $cpputestCmake = Join-Path $repoRoot "firmware/third_party/cpputest/CMakeLists.txt"
  if (-not (Test-Path $cpputestCmake)) {
    Write-Host "CppUTest not present. Run: git submodule update --init --recursive"
    exit 2
  }

  $sourceDir = Join-Path $repoRoot "firmware/tests_host"
  $buildDir  = Join-Path $repoRoot "firmware/tests_host/build"
  New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

  # Configure
  cmake -S $sourceDir -B $buildDir
  Require-Success "CMake configure"

  # Build
  cmake --build $buildDir --config $Config
  Require-Success "CMake build"

  # Find the test executable robustly (handles Debug/Release subdirs, different generators)
  $exe = Get-ChildItem -Path $buildDir -Recurse -File -Filter "fw_tests*.exe" |
         Sort-Object LastWriteTime -Descending |
         Select-Object -First 1

  if (-not $exe) {
    throw "No fw_tests*.exe found under $buildDir. Build may not have produced an executable."
  }

  Write-Host "Running: $($exe.FullName)"
  & $exe.FullName
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}