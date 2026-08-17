# Docker operations guide

This document contains the standard commands for managing the AgentMesh Docker stack from the repository root.

## Quick commands for Powershell

### Start everything

```powershell
pwsh -File .\scripts\docker_component_manager.ps1 -Action start -Service all
```

### Restart one component

```powershell
pwsh -File .\scripts\docker_component_manager.ps1 -Action restart -Service orchestrator-supervisor-agent
```

### Stop one service

```powershell
pwsh -File .\scripts\docker_component_manager.ps1 -Action stop -Service agent-googleadk-chatagent
```

### View recent logs for the whole stack

```powershell
pwsh -File .\scripts\docker_component_manager.ps1 -Action logs -Service all
```

### Follow logs for one service

```powershell
pwsh -File .\scripts\docker_component_manager.ps1 -Action logs-iterative -Service orchestrator-supervisor-agent
```

### Health check

```powershell
pwsh -File .\scripts\docker_component_manager.ps1 -Action health
```

## Notes

- The manager script reads the repo-root `.env` automatically via `--project-directory $RepoRoot`.
- Use `localhost` URLs for host-side testing, such as:
  - http://localhost:8000/health
  - http://localhost:8101/health
  - http://localhost:8102/health
  - http://localhost:8501
- Docker service names such as `orchestrator-supervisor-agent` are only valid inside the compose network.

## Supported service names

- `postgres`
- `migrate`
- `orchestrator-supervisor-agent`
- `agent-langgraph-copilot`
- `agent-googleadk-chatagent`
- `streamlit`
- `all`
