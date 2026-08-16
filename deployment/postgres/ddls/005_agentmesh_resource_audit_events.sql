CREATE TABLE IF NOT EXISTS agentmesh_resource_audit_events (
    audit_id UUID PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES agentmesh_resources(resource_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    actor TEXT NOT NULL DEFAULT 'system',
    message TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    workflow_id UUID,
    event_id UUID REFERENCES agentmesh_events(event_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_agentmesh_resource_audit_severity
        CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical'))
);

ALTER TABLE agentmesh_resource_audit_events ADD COLUMN IF NOT EXISTS resource_id TEXT;
ALTER TABLE agentmesh_resource_audit_events ADD COLUMN IF NOT EXISTS event_type TEXT;
ALTER TABLE agentmesh_resource_audit_events ADD COLUMN IF NOT EXISTS severity TEXT DEFAULT 'info';
ALTER TABLE agentmesh_resource_audit_events ADD COLUMN IF NOT EXISTS actor TEXT DEFAULT 'system';
ALTER TABLE agentmesh_resource_audit_events ADD COLUMN IF NOT EXISTS message TEXT DEFAULT '';
ALTER TABLE agentmesh_resource_audit_events ADD COLUMN IF NOT EXISTS payload JSONB DEFAULT '{}'::jsonb;
ALTER TABLE agentmesh_resource_audit_events ADD COLUMN IF NOT EXISTS workflow_id UUID;
ALTER TABLE agentmesh_resource_audit_events ADD COLUMN IF NOT EXISTS event_id UUID;
ALTER TABLE agentmesh_resource_audit_events ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

UPDATE agentmesh_resource_audit_events SET severity = 'info' WHERE severity IS NULL;
UPDATE agentmesh_resource_audit_events SET actor = 'system' WHERE actor IS NULL;
UPDATE agentmesh_resource_audit_events SET message = '' WHERE message IS NULL;
UPDATE agentmesh_resource_audit_events SET payload = '{}'::jsonb WHERE payload IS NULL;
UPDATE agentmesh_resource_audit_events SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL;

ALTER TABLE agentmesh_resource_audit_events ALTER COLUMN resource_id SET NOT NULL;
ALTER TABLE agentmesh_resource_audit_events ALTER COLUMN event_type SET NOT NULL;
ALTER TABLE agentmesh_resource_audit_events ALTER COLUMN severity SET NOT NULL;
ALTER TABLE agentmesh_resource_audit_events ALTER COLUMN actor SET NOT NULL;
ALTER TABLE agentmesh_resource_audit_events ALTER COLUMN message SET NOT NULL;
ALTER TABLE agentmesh_resource_audit_events ALTER COLUMN payload SET NOT NULL;
ALTER TABLE agentmesh_resource_audit_events ALTER COLUMN created_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'agentmesh_resource_audit_events_resource_id_fkey'
    ) THEN
        ALTER TABLE agentmesh_resource_audit_events
            ADD CONSTRAINT agentmesh_resource_audit_events_resource_id_fkey
            FOREIGN KEY (resource_id)
            REFERENCES agentmesh_resources(resource_id)
            ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'agentmesh_resource_audit_events_event_id_fkey'
    ) THEN
        ALTER TABLE agentmesh_resource_audit_events
            ADD CONSTRAINT agentmesh_resource_audit_events_event_id_fkey
            FOREIGN KEY (event_id)
            REFERENCES agentmesh_events(event_id)
            ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_agentmesh_resource_audit_severity'
    ) THEN
        ALTER TABLE agentmesh_resource_audit_events
            ADD CONSTRAINT ck_agentmesh_resource_audit_severity
            CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_agentmesh_resource_audit_resource_created
    ON agentmesh_resource_audit_events (resource_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_agentmesh_resource_audit_workflow_created
    ON agentmesh_resource_audit_events (workflow_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_agentmesh_resource_audit_type_severity
    ON agentmesh_resource_audit_events (event_type, severity);
