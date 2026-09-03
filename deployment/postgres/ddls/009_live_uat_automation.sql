-- Keep the original case definitions; attach executable automation to their IDs.
UPDATE agentmesh_uat_cases
SET metadata = metadata || jsonb_build_object(
        'automated_test_file', 'tests/live/test_demo_uat.py',
        'opt_in_environment', 'AGENTMESH_LIVE_UAT=1',
        'requires_running_stack', TRUE
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE case_id IN (
    'streamlit.registry.dashboard',
    'streamlit.registry.connect_url',
    'streamlit.navigation.top_pages',
    'streamlit.agent.direct.invoke',
    'streamlit.agent.control_plane.assignment',
    'streamlit.workflow.orchestration',
    'streamlit.workflow.checkpoints',
    'postgres.checkpoint.mapping'
);

UPDATE agentmesh_uat_cases
SET metadata = metadata || jsonb_build_object(
        'browser_smoke_script', 'scripts/browser_smoke.cjs',
        'viewports', jsonb_build_array('1440x1000', '390x844')
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE case_id IN ('streamlit.navigation.top_pages', 'streamlit.registry.connect_url');
