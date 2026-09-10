[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$gitRoot = (& git -C $repoRoot rev-parse --show-toplevel).Trim()
if ([System.IO.Path]::GetFullPath($gitRoot) -ne [System.IO.Path]::GetFullPath($repoRoot)) {
    throw "Refusing to configure hooks outside the AgentMesh repository."
}

& git -C $repoRoot config --local core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) {
    throw "Unable to configure core.hooksPath."
}

Write-Host "AgentMesh Git hooks installed from .githooks."
Write-Host "Pre-push validation is authoritative locally; GitHub Actions reruns it remotely."
