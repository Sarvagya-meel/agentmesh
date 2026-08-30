from agentmesh.testing.sanity_catalog import SANITY_CASES, cases_by_id


def test_sanity_catalog_has_core_runtime_coverage() -> None:
    cases = cases_by_id()

    for case_id in (
        "docker.compose.config",
        "orchestrator.health",
        "langgraph.ready",
        "adk.ready",
        "registry.online_agents",
        "workflow.approval_gates",
        "langsmith.project_auth",
    ):
        assert case_id in cases


def test_langsmith_eval_cases_cover_multi_agent_quality_dimensions() -> None:
    eval_case_ids = {case.case_id for case in SANITY_CASES if case.langsmith_eval}

    assert {
        "invoke.langgraph",
        "invoke.adk",
        "workflow.approval_gates",
        "events.workflow_audit",
        "langsmith.project_auth",
    }.issubset(eval_case_ids)
