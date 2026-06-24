param(
  [string]$Config = "Debug",
  [string]$CubeIde = "C:\ST\STM32CubeIDE_1.18.1\STM32CubeIDE",
  [string]$ProjectDir = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjName = "LabCraft_firmware"

if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
  $ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
  $ProjectDir = (Resolve-Path $ProjectDir).Path
}

if (-not (Test-Path $CubeIde)) {
  throw "STM32CubeIDE directory not found: $CubeIde"
}

$headlessBuild = Join-Path $CubeIde "headless-build.bat"
if (-not (Test-Path $headlessBuild)) {
  throw "headless-build.bat not found under STM32CubeIDE directory: $CubeIde"
}

$Ws = Join-Path $env:TEMP ("cubeide_ws_" + $ProjName + "_" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $Ws | Out-Null

Push-Location $CubeIde
try {
  & $headlessBuild -no-indexer -data $Ws -import $ProjectDir -cleanBuild "$ProjName/$Config"
  $exit = $LASTEXITCODE
} finally {
  Pop-Location
}

Write-Host "Headless build exit code: $exit"

$bin = Get-ChildItem -Path $ProjectDir -Recurse -Filter "*.bin" |
       Sort-Object LastWriteTime -Descending |
       Select-Object -First 1

if (-not $bin) { throw "No .bin produced under $ProjectDir" }

$artifactDir = Join-Path $ProjectDir "artifacts"
New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null

$artifactPath = Join-Path $artifactDir "$ProjName.bin"
if (([System.IO.Path]::GetFullPath($bin.FullName)) -ne ([System.IO.Path]::GetFullPath($artifactPath))) {
    Copy-Item $bin.FullName $artifactPath -Force
    Write-Host "Copied: $($bin.FullName) -> $artifactPath"
} else {
    Write-Host "Artifact already up to date at $artifactPath"
}

exit $exit
