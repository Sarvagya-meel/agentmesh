"""Message helpers shared by AgentMesh LangGraph components."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import BaseMessage


def provider_messages(messages: Sequence[BaseMessage]) -> list[dict[str, str]]:
    """Convert checkpointed LangChain messages to the platform provider contract."""

    roles = {"human": "user", "ai": "assistant", "system": "system"}
    converted: list[dict[str, str]] = []
    for message in messages:
        role = roles.get(message.type)
        if role is None:
            continue
        content = message.content
        converted.append(
            {
                "role": role,
                "content": content if isinstance(content, str) else str(content),
            }
        )
    return converted
