"""AgentCard — the metadata shape published by every agent at registration."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentmesh.core.models.exceptions import ValidationError


class AgentCard(BaseModel):
    """Metadata published by an agent when it comes online."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    agent_id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    endpoint: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    owner: str = "unknown"
    status: str = "online"
    metadata: dict[str, Any] = Field(default_factory=dict)
    registered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("agent_id", "name")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValidationError("agent_id and name must be non-empty strings.")
        return cleaned

    @field_validator("capabilities", "skills")
    @classmethod
    def validate_list(cls, value: list[str]) -> list[str]:
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        candidate = value.strip().lower()
        if candidate not in {"online", "offline", "stale", "starting"}:
            raise ValidationError("status must be one of: online, offline, stale, starting.")
        return candidate
