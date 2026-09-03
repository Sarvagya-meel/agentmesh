<#
PowerShell helper to start services in order: registry -> streamlit -> agent(s)
Usage:
  # from any location
  C:\> pwsh -File scripts\start_registry_streamlit_agent.ps1

Notes:
- This starts the orchestrator (registry) using docker compose, waits until its /health endpoint responds,
  starts Streamlit without compose dependencies, then starts the appropriate agent(s) based on COMPOSE_PROFILES
- Streamlit may show empty data until agents register.
- COMPOSE_PROFILES in .env determines whether to start combined or split agents
#>

param(
    [string]$RepoRoot = "C:\Users\sarva\OneDrive\Documents\ProjectSpace\agentmesh",
    [int]$WaitInterval = 2
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path $RepoRoot).Path
Set-Location $RepoRoot
$compose = "deployment/docker/compose.yml"
$dotenvFile = Join-Path $RepoRoot ".env"

# Load COMPOSE_PROFILES from .env
$composeProfiles = "combined"
if (Test-Path $dotenvFile) {
    $envContent = Get-Content $dotenvFile -Raw
    if ($envContent -match "^COMPOSE_PROFILES\s*=\s*([^`r`n]+)") {
        $composeProfiles = $matches[1].Trim()
    }
}

Write-Host "[INFO] Using COMPOSE_PROFILES=$composeProfiles" -ForegroundColor Yellow

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
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            if ($r.StatusCode -eq 200) {
                Write-Host "Healthy: $Label -> $Url"
                return
            }
        } catch {
            # ignore and retry
        }
        Write-Host "waiting for $Label..."
        Start-Sleep -Seconds $PollSeconds
    }
    throw "Timed out waiting for $Label at $Url"
}

function Wait-ForMigrate {
    param([string]$ServiceName = "migrate")
    
    Write-Host "Waiting for migrate service to complete..."
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        $status = docker compose -f $compose ps -q $ServiceName 2>$null
        if ($LASTEXITCODE -eq 0 -and $status) {
            $inspect = docker inspect $status --format='{{.State.Status}}' 2>$null
            if ($inspect -eq "exited") {
                $exitCode = docker inspect $status --format='{{.State.ExitCode}}' 2>$null
                if ($exitCode -eq "0") {
                    Write-Host "Migrate completed successfully (exit code 0)"
                    return $true
                } else {
                    throw "Migrate failed with exit code: $exitCode"
                }
            } elseif ($inspect -eq "running") {
                Write-Host "Migrate is still running..."
                Start-Sleep -Seconds 2
                continue
            }
        } else {
            Write-Host "Migrate container not found or not running - starting now..."
            return $false
        }
    }
    throw "Timed out waiting for migrate service"
}

Write-Output "Starting LiteLLM, control plane, and supervisor..."
docker compose -f $compose up -d litellm control-plane supervisor
Wait-ForHttp -Url "http://127.0.0.1:8000/health" -Label "control-plane"
Wait-ForHttp -Url "http://127.0.0.1:8110/health" -Label "supervisor"

Write-Output "Starting Streamlit (no-deps) ..."
docker compose -f $compose up -d --no-deps streamlit
Wait-ForHttp -Url "http://127.0.0.1:8501" -Label "streamlit"

# Start agent(s) based on profile
if ($composeProfiles -eq "split") {
    Write-Output "Starting agent: agent-langgraph-copilot-api (split profile)..."
    docker compose -f $compose up -d agent-langgraph-copilot-api
    Wait-ForHttp -Url "http://127.0.0.1:8101/health" -Label "agent-langgraph-copilot-api"
    
    Write-Output "Starting agent: agent-googleadk-chatagent-api (split profile)..."
    docker compose -f $compose up -d agent-googleadk-chatagent-api
    Wait-ForHttp -Url "http://127.0.0.1:8102/health" -Label "agent-googleadk-chatagent-api"
    
    Write-Output "Agent API services are healthy."
} else {
    Write-Output "Starting agent: agent-langgraph-copilot (combined profile)..."
    docker compose -f $compose up -d agent-langgraph-copilot
    Wait-ForHttp -Url "http://127.0.0.1:8101/health" -Label "agent-langgraph-copilot"
    
    Write-Output "Starting agent: agent-googleadk-chatagent (combined profile)..."
    docker compose -f $compose up -d agent-googleadk-chatagent
    Wait-ForHttp -Url "http://127.0.0.1:8102/health" -Label "agent-googleadk-chatagent"
    
    Write-Output "Combined agents are healthy."
}

Write-Output "All requested services started."
Write-Output "API: http://127.0.0.1:8000"
Write-Output "UI: http://127.0.0.1:8501"
