[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$Python,
  [switch]$IncludeFirmware,
  [switch]$CheckOnly
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if (-not [IO.Path]::IsPathRooted($Python) -or -not (Test-Path -LiteralPath $Python -PathType Leaf)) {
  throw "-Python must name an existing absolute Python executable."
}
$tool = Join-Path $PSScriptRoot "worktree_development.py"
$arguments = @("-B", $tool, "setup", "--python", $Python)
if ($IncludeFirmware) { $arguments += "--include-firmware" }
if ($CheckOnly) { $arguments += "--check-only" }
& $Python @arguments
exit $LASTEXITCODE
