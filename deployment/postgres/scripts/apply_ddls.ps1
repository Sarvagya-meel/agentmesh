param(
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$DdlDir = "$(Split-Path -Parent $PSScriptRoot)\ddls",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not $DatabaseUrl) {
    $envFile = Join-Path (Get-Location) ".env"
    if (Test-Path -LiteralPath $envFile) {
        Get-Content -LiteralPath $envFile | ForEach-Object {
            if ($_ -match "^DATABASE_URL=(.*)$") {
                $DatabaseUrl = $matches[1]
            }
        }
    }
}

if (-not $DatabaseUrl) {
    throw "DATABASE_URL is required."
}

$argsList = @(
    (Join-Path $PSScriptRoot "apply_ddls.py"),
    "--database-url",
    $DatabaseUrl,
    "--ddls-dir",
    $DdlDir
)

if ($DryRun) {
    $argsList += "--dry-run"
}

python @argsList
