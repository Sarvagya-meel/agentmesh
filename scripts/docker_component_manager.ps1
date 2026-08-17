<#
.SYNOPSIS
Manage each AgentMesh Docker component individually or as a group.

.DESCRIPTION
This helper keeps the Docker Compose workflow consistent across local development.
It allows you to start, stop, restart, inspect, and follow logs for each service
without repeatedly typing docker compose commands.

.EXAMPLE
pwsh -File scripts\docker_component_manager.ps1 -Action start -Service orchestrator-supervisor-agent
pwsh -File scripts\docker_component_manager.ps1 -Action restart -Service all
pwsh -File scripts\docker_component_manager.ps1 -Action logs-iterative -Service agent-googleadk-chatagent

.NOTES
Available services:
  postgres
  migrate
  orchestrator-supervisor-agent
  agent-langgraph-copilot
  agent-googleadk-chatagent
  streamlit
  all
#>

param(
    [ValidateSet("start", "stop", "restart", "status", "logs", "logs-iterative", "health")]
    [string]$Action = "status",

    [string[]]$Service = @("all"),

    [string]$RepoRoot = $(Resolve-Path (Join-Path $PSScriptRoot "..")).Path,

    [switch]$NoBuild,

    [int]$TailLines = 80,

    [int]$WaitSeconds = 2,

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$composeFile = Join-Path $RepoRoot "deployment\docker\compose.yml"
$composeDir = Split-Path -Path $composeFile -Parent
$dotenvFile = Join-Path $RepoRoot ".env"

if (-not (Test-Path $composeFile)) {
    throw "Compose file not found: $composeFile"
}

$serviceCatalog = @(
    "postgres",
    "migrate",
    "orchestrator-supervisor-agent",
    "agent-langgraph-copilot",
    "agent-googleadk-chatagent",
    "streamlit"
)

function Resolve-RequestedServices {
    param([string[]]$Requested)

    $normalized = @()
    foreach ($item in $Requested) {
        $candidate = $item.Trim()
        if (-not $candidate) { continue }
        if ($candidate -ieq "all") {
            $normalized += $serviceCatalog
            continue
        }
        if ($serviceCatalog -contains $candidate) {
            $normalized += $candidate
            continue
        }
        throw "Unknown service '$candidate'. Valid services: $($serviceCatalog -join ', ')"
    }

    if (-not $normalized) {
        throw "No services were selected."
    }

    return $normalized | Select-Object -Unique
}

function Invoke-Compose {
    param(
        [string[]]$ComposeArgs,
        [string]$StepLabel
    )

    Write-Host "==> $StepLabel"
    # Use --env-file to specify the .env file location (project root)
    & docker compose --project-directory $composeDir -f $composeFile --env-file $dotenvFile @ComposeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose command failed: $StepLabel"
    }
}

function Wait-ForHttp {
    param(
        [string]$Url,
        [string]$Label,
        [int]$TimeoutSec = 60,
        [int]$PollSeconds = 2
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                Write-Host "Healthy: $Label -> $Url"
                return
            }
        } catch {
            Start-Sleep -Seconds $PollSeconds
        }
    }

    throw "Timed out waiting for $Label at $Url"
}

function Wait-ForServiceHealth {
    param([string]$ServiceName)

    $healthMap = @{
        "orchestrator-supervisor-agent" = "http://127.0.0.1:8000/health";
        "agent-langgraph-copilot" = "http://127.0.0.1:8101/health";
        "agent-googleadk-chatagent" = "http://127.0.0.1:8102/health";
        "streamlit" = "http://127.0.0.1:8501";
    }

    if (-not $healthMap.ContainsKey($ServiceName)) {
        return
    }

    $url = $healthMap[$ServiceName]
    $label = $ServiceName
    Wait-ForHttp -Url $url -Label $label -TimeoutSec 90 -PollSeconds 2
}

$servicesToManage = Resolve-RequestedServices -Requested $Service
Write-Host "Repo root: $RepoRoot"
Write-Host "Compose file: $composeFile"
Write-Host "Selected services: $($servicesToManage -join ', ')"
Write-Host "Action: $Action"
Write-Host ""

switch ($Action) {
    "start" {
        foreach ($svc in $servicesToManage) {
            if ($NoBuild) {
                Invoke-Compose -ComposeArgs @("up", "-d", $svc) -StepLabel "Starting $svc"
            } else {
                    Invoke-Compose -ComposeArgs @("up", "--build", "-d", $svc) -StepLabel "Starting $svc (with build)"
            }
            Wait-ForServiceHealth -ServiceName $svc
        }
    }

    "stop" {
        foreach ($svc in $servicesToManage) {
            Invoke-Compose -ComposeArgs @("stop", $svc) -StepLabel "Stopping $svc"
        }
    }

    "restart" {
        foreach ($svc in $servicesToManage) {
            if ($NoBuild) {
                    Invoke-Compose -ComposeArgs @("up", "-d", "--force-recreate", $svc) -StepLabel "Restarting $svc"
            } else {
                    Invoke-Compose -ComposeArgs @("up", "--build", "-d", "--force-recreate", $svc) -StepLabel "Restarting $svc (with rebuild)"
            }
            Wait-ForServiceHealth -ServiceName $svc
        }
    }

    "status" {
        Invoke-Compose -ComposeArgs @("ps") -StepLabel "Status"
    }

    "logs" {
        foreach ($svc in $servicesToManage) {
            Write-Host "===== $svc ====="
            & docker compose --project-directory $composeDir -f $composeFile logs --tail $TailLines $svc
            if ($LASTEXITCODE -ne 0) {
                throw "docker logs failed for $svc"
            }
            Write-Host ""
        }
    }

    "logs-iterative" {
        foreach ($svc in $servicesToManage) {
            Write-Host "===== FOLLOWING LOGS FOR $svc ====="
            & docker compose --project-directory $composeDir -f $composeFile logs --tail $TailLines -f $svc
            if ($LASTEXITCODE -ne 0) {
                throw "Follow logs failed for $svc"
            }
            Write-Host ""
            Start-Sleep -Seconds $WaitSeconds
        }
    }

    "health" {
        $healthChecks = @(
            @{ Name = "Orchestrator"; Url = "http://127.0.0.1:8000/health" },
            @{ Name = "LangGraph Agent"; Url = "http://127.0.0.1:8101/health" },
            @{ Name = "Google ADK Agent"; Url = "http://127.0.0.1:8102/health" },
            @{ Name = "Streamlit"; Url = "http://127.0.0.1:8501" }
        )

        foreach ($check in $healthChecks) {
            try {
                $result = Invoke-WebRequest -Uri $check.Url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
                Write-Host "[OK] $($check.Name) -> HTTP $($result.StatusCode)"
            } catch {
                Write-Host "[FAIL] $($check.Name) -> $($check.Url)"
            }
        }
    }
}
