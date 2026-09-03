from agentmesh.testing.sanity_catalog import cases_by_id, read_seeded_catalog


def test_uat_catalog_seed_ddl_has_core_runtime_coverage() -> None:
    cases = cases_by_id()

    for case_id in (
        "docker.compose.config",
        "docker.compose.build",
        "streamlit.registry.dashboard",
        "streamlit.agent.direct.invoke",
        "streamlit.agent.control_plane.assignment",
        "streamlit.workflow.orchestration",
        "streamlit.workflow.checkpoints",
        "api.workflow.approval_gates",
        "api.worker.retry.transient_failure",
        "api.worker.semantic_failure.replan",
        "postgres.workflow_events.persisted",
        "postgres.claims.retry_deadletter",
        "postgres.checkpoint.mapping",
        "langsmith.project_auth",
    ):
        assert case_id in cases


def test_uat_catalog_has_smoke_unit_validation_and_streamlit_cases() -> None:
    cases = read_seeded_catalog()

    assert {"smoke", "unit", "validation", "uat"}.issubset(
        {case.suite for case in cases}
    )
    assert {"streamlit", "api", "postgres", "docker", "langsmith"}.issubset(
        {case.execution_layer for case in cases}
    )


def test_langsmith_eval_cases_cover_multi_agent_quality_dimensions() -> None:
    eval_case_ids = {case.case_id for case in read_seeded_catalog() if case.langsmith_eval}

    assert {
        "streamlit.agent.direct.invoke",
        "streamlit.agent.control_plane.assignment",
        "streamlit.workflow.orchestration",
        "streamlit.workflow.checkpoints",
        "api.workflow.approval_gates",
        "langsmith.project_auth",
    }.issubset(eval_case_ids)
