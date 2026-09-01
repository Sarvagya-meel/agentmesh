CREATE INDEX IF NOT EXISTS idx_agentmesh_events_pending_supervisor_actions
    ON agentmesh_events (target_agent, timestamp, sequence_number)
    WHERE event_type = 'SUPERVISOR_ACTION_REQUESTED';

CREATE INDEX IF NOT EXISTS idx_agentmesh_events_action_causation
    ON agentmesh_events (causation_id, event_type)
    WHERE event_type IN (
        'SUPERVISOR_ACTION_COMPLETED',
        'SUPERVISOR_ACTION_FAILED',
        'SUPERVISOR_ACTION_RETRY_SCHEDULED'
    );

CREATE INDEX IF NOT EXISTS idx_agentmesh_events_task_validation
    ON agentmesh_events (workflow_id, event_type, sequence_number)
    WHERE event_type IN (
        'TASK_OUTPUT_RECEIVED',
        'TASK_VALIDATION_REQUESTED',
        'TASK_VALIDATION_COMPLETED'
    );
