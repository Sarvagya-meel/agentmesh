from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from langgraph.store.base import BaseStore

from agentmesh.core.models.exceptions import ValidationError


def load_opt_in_memories(
    store: BaseStore,
    *,
    agent_id: str,
    enabled: bool,
    user_id: str,
    opt_in: bool,
    updates: dict[str, str],
    delete_keys: list[str],
    retention_days: int,
) -> list[dict[str, Any]]:
    """Apply explicit memory changes and return unexpired user-scoped values."""

    if not (enabled and opt_in and user_id.strip()):
        return []
    namespace = ("agentmesh", agent_id, user_id.strip())
    for key in delete_keys:
        store.delete(namespace, _memory_key(key))
    now = datetime.now(UTC)
    for key, value in _safe_memory_updates(updates).items():
        store.put(
            namespace,
            _memory_key(key),
            {
                "name": key,
                "value": value,
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(days=retention_days)).isoformat(),
            },
        )
    memories = []
    for item in store.search(namespace, limit=50):
        expires_at = datetime.fromisoformat(str(item.value["expires_at"]))
        if expires_at >= now:
            memories.append(dict(item.value))
    return sorted(memories, key=lambda item: str(item.get("name", "")))


def _memory_key(value: str) -> str:
    normalized = "-".join(value.strip().lower().split())
    if not normalized:
        raise ValidationError("Memory keys cannot be empty.")
    return normalized[:100]


def _safe_memory_updates(values: dict[str, str]) -> dict[str, str]:
    blocked_terms = {"password", "secret", "token", "api_key", "credential"}
    safe: dict[str, str] = {}
    for key, value in values.items():
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if any(term in normalized_key for term in blocked_terms):
            raise ValidationError(f"Memory key {key!r} may contain a credential.")
        if normalized_value.lower().startswith(("sk-", "aq.")):
            raise ValidationError("Credential-like values cannot be stored in memory.")
        safe[key.strip()] = normalized_value[:2000]
    return safe
