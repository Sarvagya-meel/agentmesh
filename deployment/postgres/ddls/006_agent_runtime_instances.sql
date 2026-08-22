ALTER TABLE agentmesh_resources
    DROP CONSTRAINT IF EXISTS ck_agentmesh_resources_type;

ALTER TABLE agentmesh_resources
    ADD CONSTRAINT ck_agentmesh_resources_type
    CHECK (
        resource_type IN (
            'agent', 'agent_runtime', 'orchestrator', 'mcp_server', 'tool',
            'registry', 'ui', 'service'
        )
    );

ALTER TABLE agentmesh_resources
    DROP CONSTRAINT IF EXISTS ck_agentmesh_resources_status;

ALTER TABLE agentmesh_resources
    ADD CONSTRAINT ck_agentmesh_resources_status
    CHECK (
        status IN (
            'unknown', 'starting', 'ready', 'online', 'degraded', 'draining',
            'offline', 'stale', 'failed', 'disabled'
        )
    );

CREATE INDEX IF NOT EXISTS ix_agentmesh_runtime_parent_status
    ON agentmesh_resources (parent_resource_id, status, last_seen)
    WHERE resource_type = 'agent_runtime';
