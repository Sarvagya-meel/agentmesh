from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def newest_events(events: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return workflow events in reverse durable sequence order."""
    return sorted(
        events,
        key=lambda event: int(event.get("sequence_number") or 0),
        reverse=True,
    )


def activity_hash(activity: Mapping[str, Any]) -> str:
    """Return a stable digest for deciding whether the rendered activity changed."""
    canonical = json.dumps(
        activity,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def event_route(event: Mapping[str, Any]) -> str:
    source = str(event.get("source_agent") or "unknown")
    destination = str(event.get("target_agent") or "broadcast")
    return f"{source} -> {destination}"


def event_label(event: Mapping[str, Any]) -> str:
    event_type = str(event.get("event_type") or "EVENT")
    return event_type.replace("_", " ").title()


def normalize_registry_url(value: str) -> str:
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a complete HTTP or HTTPS registry URL.")
    if parsed.query or parsed.fragment:
        raise ValueError("Registry URL cannot include a query string or fragment.")
    normalized_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, "", ""))
