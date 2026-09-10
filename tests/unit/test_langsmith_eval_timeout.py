from __future__ import annotations

import pytest

from tests.tools import langsmith_eval


def test_live_workflow_has_a_bounded_completion_deadline(monkeypatch) -> None:
    times = iter([0.0, 181.0])
    monkeypatch.setattr(langsmith_eval.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        langsmith_eval,
        "post_json",
        lambda _url, _payload: {"workflow_id": "workflow-1", "status": "RUNNING"},
    )

    with pytest.raises(TimeoutError, match="did not complete within 180s"):
        langsmith_eval.collect_live_workflow("http://localhost:8000")
