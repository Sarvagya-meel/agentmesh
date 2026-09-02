<#
.SYNOPSIS
Manage each AgentMesh Docker component individually or as a group.

.DESCRIPTION
This helper keeps the Docker Compose workflow consistent across local development.
It allows you to start, stop, restart, inspect, and follow logs for each service
without repeatedly typing docker compose commands.

.EXAMPLE
pwsh -File scripts\docker_component_manager.ps1 -Action start -Service all
pwsh -File scripts\docker_component_manager.ps1 -Action restart -Service all
pwsh -File scripts\docker_component_manager.ps1 -Action rebuild -Service all
pwsh -File scripts\docker_component_manager.ps1 -Action logs-iterative -Service agent-googleadk-chatagent

.NOTES
Available services:
  postgres
  migrate
  litellm
  control-plane
  supervisor
  agent-langgraph-copilot
  agent-langgraph-copilot-api
  agent-langgraph-copilot-worker
  agent-googleadk-chatagent
  agent-googleadk-chatagent-api
  agent-googleadk-chatagent-worker
  streamlit
  all
#>

param(
    [ValidateSet("start", "stop", "restart", "rebuild", "status", "logs", "logs-iterative", "health")]
    [string]$Action = "status",

    [string[]]$Service = @("all"),

    [string]$RepoRoot = $(Resolve-Path (Join-Path $PSScriptRoot "..")).Path,

    [switch]$NoBuild,

    [switch]$NoCache,

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

# Load .env file to determine COMPOSE_PROFILES
$envProfiles = "combined"
if (Test-Path $dotenvFile) {
    $envContent = Get-Content $dotenvFile -Raw
    if ($envContent -match "^COMPOSE_PROFILES=(.+)$" -or $envContent -match "^COMPOSE_PROFILES=(.+)$") {
        $envProfiles = $matches[1].Trim()
    }
}

# Service catalog based on profile
$combinedServices = @(
    "postgres",
    "migrate",
    "litellm",
    "control-plane",
    "supervisor",
    "agent-langgraph-copilot",
    "agent-googleadk-chatagent",
    "streamlit"
)

$splitServices = @(
    "postgres",
    "migrate",
    "litellm",
    "control-plane",
    "supervisor",
    "agent-langgraph-copilot-api",
    "agent-langgraph-copilot-worker",
    "agent-googleadk-chatagent-api",
    "agent-googleadk-chatagent-worker",
    "streamlit"
)

if ($envProfiles -eq "split") {
    $serviceCatalog = $splitServices
    Write-Host "[INFO] Using SPLIT profile. Services: $($serviceCatalog -join ', ')" -ForegroundColor Yellow
} else {
    $serviceCatalog = $combinedServices
    Write-Host "[INFO] Using COMBINED profile. Services: $($serviceCatalog -join ', ')" -ForegroundColor Yellow
}

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
        throw "Unknown service '$candidate'. Valid services for current profile: $($serviceCatalog -join ', ')"
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

function Wait-ForServiceReady {
    param([string]$ServiceName)

    # Migrate service only runs once - check if it completed successfully
    if ($ServiceName -eq "migrate") {
        Write-Host "Checking migrate service status..."
        $status = & docker compose --project-directory $composeDir -f $composeFile ps -q migrate 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $status) {
            Write-Host "Migrate container not found - running now..."
            return
        }
        
        $inspect = & docker inspect $status --format='{{.State.Status}}' 2>$null
        if ($LASTEXITCODE -eq 0) {
            if ($inspect -eq "exited") {
                $exitCode = & docker inspect $status --format='{{.State.ExitCode}}' 2>$null
                if ($exitCode -eq "0") {
                    Write-Host "Migrate completed successfully (exit code 0)"
                    return
                } else {
                    throw "Migrate failed with exit code: $exitCode"
                }
            } elseif ($inspect -eq "running") {
                Write-Host "Migrate is still running..."
                return
            }
        }
        return
    }

    $healthMap = @{
        "postgres" = "http://127.0.0.1:5432";
        "litellm" = "http://127.0.0.1:4000/health/liveliness";
        "control-plane" = "http://127.0.0.1:8000/health";
        "supervisor" = "http://127.0.0.1:8110/health";
        "agent-langgraph-copilot" = "http://127.0.0.1:8101/health";
        "agent-langgraph-copilot-api" = "http://127.0.0.1:8101/health";
        "agent-googleadk-chatagent" = "http://127.0.0.1:8102/health";
        "agent-googleadk-chatagent-api" = "http://127.0.0.1:8102/health";
        "streamlit" = "http://127.0.0.1:8501";
    }

    if (-not $healthMap.ContainsKey($ServiceName)) {
        return
    }

    $url = $healthMap[$ServiceName]
    $label = $ServiceName
    
    # Skip health check for postgres (different health mechanism)
    if ($ServiceName -eq "postgres") {
        Write-Host "Postgres health check handled by Docker healthcheck"
        return
    }
    
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
            Invoke-Compose -ComposeArgs @("up", "-d", $svc) -StepLabel "Starting $svc from the current image"
            Wait-ForServiceReady -ServiceName $svc
        }
    }

    "stop" {
        foreach ($svc in $servicesToManage) {
            Invoke-Compose -ComposeArgs @("stop", $svc) -StepLabel "Stopping $svc"
        }
    }

    "restart" {
        foreach ($svc in $servicesToManage) {
            if ($svc -eq "migrate") {
                Write-Host "==> Restarting $svc (rebuilds to apply any new/changed DDLs, then exits)"
                if ($NoBuild) {
                    Invoke-Compose -ComposeArgs @("up", "-d", "--force-recreate", $svc) -StepLabel "Restarting $svc"
                } else {
                    Invoke-Compose -ComposeArgs @("up", "--build", "-d", "--force-recreate", $svc) -StepLabel "Restarting $svc (with rebuild)"
                }
                Wait-ForServiceReady -ServiceName $svc
            } elseif ($NoBuild) {
                Invoke-Compose -ComposeArgs @("up", "-d", "--force-recreate", $svc) -StepLabel "Restarting $svc"
            } else {
                Invoke-Compose -ComposeArgs @("up", "--build", "-d", "--force-recreate", $svc) -StepLabel "Restarting $svc (with rebuild)"
            }
            Wait-ForServiceReady -ServiceName $svc
        }
    }

    "rebuild" {
        if (-not ($Service -contains "all")) {
            throw "Rebuild is a destructive full-stack action. Use -Action rebuild -Service all."
        }

        Write-Host "WARNING: rebuild deletes all AgentMesh containers, images, and database volumes." -ForegroundColor Yellow
        Invoke-Compose -ComposeArgs @("down", "--volumes", "--rmi", "all", "--remove-orphans") -StepLabel "Destroying the existing AgentMesh stack"

        Write-Host "==> Removing Docker build cache"
        & docker builder prune --all --force
        if ($LASTEXITCODE -ne 0) {
            throw "docker builder cache prune failed"
        }

        Invoke-Compose -ComposeArgs @("build", "--no-cache", "--pull") -StepLabel "Building every image from scratch"
        Invoke-Compose -ComposeArgs @("up", "-d") -StepLabel "Respawning the full AgentMesh stack"

        foreach ($svc in $serviceCatalog) {
            Wait-ForServiceReady -ServiceName $svc
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
            @{ Name = "LangGraph Agent (API)"; Url = "http://127.0.0.1:8101/health" },
            @{ Name = "Google ADK Agent"; Url = "http://127.0.0.1:8102/health" },
            @{ Name = "Google ADK Agent (API)"; Url = "http://127.0.0.1:8102/health" },
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
