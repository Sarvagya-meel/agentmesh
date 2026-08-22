"""Provider-neutral contracts for model clients used across AgentMesh."""

from __future__ import annotations

from typing import Any, Protocol


class TextCompletionClient(Protocol):
    """Generate plain-text model output from a chat-style message sequence."""

    model: str

    def create_text_completion(self, *, messages: list[dict[str, str]]) -> str:
        """Generate one assistant response."""


class StructuredOutputClient(Protocol):
    """Generate a JSON object constrained by a supplied schema."""

    model: str

    def create_structured_output(
        self,
        *,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Return one JSON object conforming to the supplied schema."""
