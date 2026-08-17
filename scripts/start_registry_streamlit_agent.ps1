<#
PowerShell helper to start services in order: registry -> streamlit -> agent
Usage:
  # from any location
  C:\> pwsh -File scripts\start_registry_streamlit_agent.ps1

Notes:
- This starts the orchestrator (registry) using docker compose, waits until its /health endpoint responds,
  starts Streamlit without compose dependencies (so it can be started before agents), then starts one agent
  (agent-langgraph-copilot) and waits for its health endpoint.
- Streamlit may show empty data until agents register.
#>

param(
    [string]$RepoRoot = "C:\Users\sarva\OneDrive\Documents\ProjectSpace\agentmesh",
    [int]$WaitInterval = 2
)

Set-Location $RepoRoot
$compose = "deployment/docker/compose.yml"

Write-Output "Starting registry (orchestrator-supervisor-agent)..."
docker compose -f $compose up -d orchestrator-supervisor-agent

Write-Output "Waiting for registry health at http://127.0.0.1:8000/health ..."
while ($true) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8000/health -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { break }
    } catch {
        # ignore and retry
    }
    Write-Output "waiting for registry..."
    Start-Sleep -Seconds $WaitInterval
}
Write-Output "Registry is healthy."

Write-Output "Starting Streamlit (no-deps) ..."
docker compose -f $compose up -d --no-deps streamlit

Write-Output "Waiting for Streamlit at http://127.0.0.1:8501 ..."
while ($true) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8501 -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { break }
    } catch {
    }
    Write-Output "waiting for streamlit..."
    Start-Sleep -Seconds $WaitInterval
}
Write-Output "Streamlit appears available at http://127.0.0.1:8501"

Write-Output "Starting agent: agent-langgraph-copilot ..."
docker compose -f $compose up -d agent-langgraph-copilot

Write-Output "Waiting for agent health at http://127.0.0.1:8101/health ..."
while ($true) {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8101/health -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { break }
    } catch {
    }
    Write-Output "waiting for agent..."
    Start-Sleep -Seconds $WaitInterval
}
Write-Output "Agent is healthy. All requested services started."
