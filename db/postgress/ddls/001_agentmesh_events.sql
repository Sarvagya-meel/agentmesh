CREATE TABLE IF NOT EXISTS agentmesh_events (
    event_id UUID PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    workflow_id UUID NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    event_type TEXT NOT NULL,
    source_agent TEXT NOT NULL,
    routing_mode TEXT NOT NULL,
    target_agent TEXT,
    payload JSONB NOT NULL,
    causation_id UUID,
    causation_chain JSONB NOT NULL,
    routing_weights JSONB,
    metadata JSONB NOT NULL,
    sequence_number INTEGER NOT NULL,
    UNIQUE (workflow_id, sequence_number)
);

ALTER TABLE agentmesh_events ADD COLUMN IF NOT EXISTS conversation_id TEXT;
ALTER TABLE agentmesh_events ADD COLUMN IF NOT EXISTS workflow_id UUID;
ALTER TABLE agentmesh_events ADD COLUMN IF NOT EXISTS timestamp TIMESTAMPTZ;
ALTER TABLE agentmesh_events ADD COLUMN IF NOT EXISTS event_type TEXT;
ALTER TABLE agentmesh_events ADD COLUMN IF NOT EXISTS source_agent TEXT;
ALTER TABLE agentmesh_events ADD COLUMN IF NOT EXISTS routing_mode TEXT;
ALTER TABLE agentmesh_events ADD COLUMN IF NOT EXISTS target_agent TEXT;
ALTER TABLE agentmesh_events ADD COLUMN IF NOT EXISTS payload JSONB;
ALTER TABLE agentmesh_events ADD COLUMN IF NOT EXISTS causation_id UUID;
ALTER TABLE agentmesh_events ADD COLUMN IF NOT EXISTS causation_chain JSONB;
ALTER TABLE agentmesh_events ADD COLUMN IF NOT EXISTS routing_weights JSONB;
ALTER TABLE agentmesh_events ADD COLUMN IF NOT EXISTS metadata JSONB;
ALTER TABLE agentmesh_events ADD COLUMN IF NOT EXISTS sequence_number INTEGER;

UPDATE agentmesh_events SET payload = '{}'::jsonb WHERE payload IS NULL;
UPDATE agentmesh_events SET causation_chain = '[]'::jsonb WHERE causation_chain IS NULL;
UPDATE agentmesh_events SET metadata = '{}'::jsonb WHERE metadata IS NULL;

ALTER TABLE agentmesh_events ALTER COLUMN conversation_id SET NOT NULL;
ALTER TABLE agentmesh_events ALTER COLUMN workflow_id SET NOT NULL;
ALTER TABLE agentmesh_events ALTER COLUMN timestamp SET NOT NULL;
ALTER TABLE agentmesh_events ALTER COLUMN event_type SET NOT NULL;
ALTER TABLE agentmesh_events ALTER COLUMN source_agent SET NOT NULL;
ALTER TABLE agentmesh_events ALTER COLUMN routing_mode SET NOT NULL;
ALTER TABLE agentmesh_events ALTER COLUMN payload SET NOT NULL;
ALTER TABLE agentmesh_events ALTER COLUMN causation_chain SET NOT NULL;
ALTER TABLE agentmesh_events ALTER COLUMN metadata SET NOT NULL;
ALTER TABLE agentmesh_events ALTER COLUMN sequence_number SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'agentmesh_events_workflow_id_sequence_number_key'
    ) THEN
        ALTER TABLE agentmesh_events ADD UNIQUE (workflow_id, sequence_number);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_agentmesh_events_workflow_timestamp
    ON agentmesh_events (workflow_id, timestamp);

CREATE INDEX IF NOT EXISTS ix_agentmesh_events_type_target
    ON agentmesh_events (event_type, target_agent);

CREATE INDEX IF NOT EXISTS ix_agentmesh_events_workflow_type
    ON agentmesh_events (workflow_id, event_type);
