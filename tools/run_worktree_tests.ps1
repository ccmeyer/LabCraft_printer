[CmdletBinding()]
param([string[]]$PytestArgs = @())
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$python = Join-Path $PSScriptRoot "..\env\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
  throw "Run tools/setup_worktree.ps1 first; this worktree has no env interpreter."
}
& $python (Join-Path $PSScriptRoot "worktree_development.py") test -- @PytestArgs
exit $LASTEXITCODE
