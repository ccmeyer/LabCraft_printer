$CubeIde = "C:\ST\STM32CubeIDE_1.18.1\STM32CubeIDE"   # <-- change to your install
$ProjectDir = "C:\Users\conar\OneDrive\Documents\PlatformIO\Projects\LabCraft_printer\firmware"  # <-- folder containing .project/.cproject
$ProjName = "LabCraft_firmware"
$Cfg = "Debug"
$Ws = Join-Path $env:TEMP ("cubeide_ws_" + $ProjName + "_" + [guid]::NewGuid().ToString())

New-Item -ItemType Directory -Force -Path $Ws | Out-Null

Push-Location $CubeIde
.\headless-build.bat -no-indexer -data $Ws -import $ProjectDir -cleanBuild "$ProjName/$Cfg"
$exit = $LASTEXITCODE
Pop-Location

Write-Host "Headless build exit code: $exit"

$bin = Get-ChildItem -Path $ProjectDir -Recurse -Filter "*.bin" |
       Sort-Object LastWriteTime -Descending |
       Select-Object -First 1

if (-not $bin) { throw "No .bin produced under $ProjectDir" }

$artifactDir = Join-Path (Split-Path $ProjectDir -Parent) "firmware/artifacts"
New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null

Copy-Item $bin.FullName (Join-Path $artifactDir "$ProjName.bin") -Force
Write-Host "Copied: $($bin.FullName) -> $artifactDir\$ProjName.bin"

exit $exit