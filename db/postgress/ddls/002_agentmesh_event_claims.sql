CREATE TABLE IF NOT EXISTS agentmesh_event_claims (
    event_id UUID PRIMARY KEY REFERENCES agentmesh_events(event_id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    claim_token UUID NOT NULL UNIQUE,
    claimed_at TIMESTAMPTZ NOT NULL,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);

ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS agent_id TEXT;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS worker_id TEXT;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS claim_token UUID;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

ALTER TABLE agentmesh_event_claims ALTER COLUMN agent_id SET NOT NULL;
ALTER TABLE agentmesh_event_claims ALTER COLUMN worker_id SET NOT NULL;
ALTER TABLE agentmesh_event_claims ALTER COLUMN claim_token SET NOT NULL;
ALTER TABLE agentmesh_event_claims ALTER COLUMN claimed_at SET NOT NULL;
ALTER TABLE agentmesh_event_claims ALTER COLUMN lease_expires_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'agentmesh_event_claims_event_id_fkey'
    ) THEN
        ALTER TABLE agentmesh_event_claims
            ADD CONSTRAINT agentmesh_event_claims_event_id_fkey
            FOREIGN KEY (event_id) REFERENCES agentmesh_events(event_id) ON DELETE CASCADE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'agentmesh_event_claims_claim_token_key'
    ) THEN
        ALTER TABLE agentmesh_event_claims
            ADD CONSTRAINT agentmesh_event_claims_claim_token_key UNIQUE (claim_token);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_agentmesh_event_claims_agent_lease
    ON agentmesh_event_claims (agent_id, lease_expires_at);

CREATE INDEX IF NOT EXISTS ix_agentmesh_event_claims_worker
    ON agentmesh_event_claims (worker_id);
