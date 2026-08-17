#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/deployment/docker/compose.yml"
ACTION="${1:-status}"
SERVICE="${2:-all}"

SERVICES=(
  postgres
  migrate
  orchestrator-supervisor-agent
  agent-langgraph-copilot
  agent-googleadk-chatagent
  streamlit
)

resolve_services() {
  if [[ "$SERVICE" == "all" ]]; then
    printf '%s\n' "${SERVICES[@]}"
    return
  fi

  printf '%s\n' "$SERVICE"
}

compose_cmd() {
  docker compose --project-directory "$REPO_ROOT" -f "$COMPOSE_FILE" "$@"
}

case "$ACTION" in
  start)
    for svc in $(resolve_services); do
      echo "==> starting $svc"
      compose_cmd up -d "$svc"
    done
    ;;
  stop)
    for svc in $(resolve_services); do
      echo "==> stopping $svc"
      compose_cmd stop "$svc"
    done
    ;;
  restart)
    for svc in $(resolve_services); do
      echo "==> restarting $svc"
      compose_cmd up -d --force-recreate "$svc"
    done
    ;;
  status)
    compose_cmd ps
    ;;
  logs)
    for svc in $(resolve_services); do
      echo "===== $svc ====="
      compose_cmd logs --tail 80 "$svc"
      echo
    done
    ;;
  logs-iterative)
    for svc in $(resolve_services); do
      echo "===== FOLLOWING $svc ====="
      compose_cmd logs --tail 80 -f "$svc"
      echo
    done
    ;;
  health)
    for url in \
      http://127.0.0.1:8000/health \
      http://127.0.0.1:8101/health \
      http://127.0.0.1:8102/health \
      http://127.0.0.1:8501
    do
      if curl -fsS "$url" >/dev/null 2>&1; then
        echo "[OK] $url"
      else
        echo "[FAIL] $url"
      fi
    done
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs|logs-iterative|health} [service|all]"
    exit 1
    ;;
esac
