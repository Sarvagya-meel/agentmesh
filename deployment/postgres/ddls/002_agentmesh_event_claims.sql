CREATE TABLE IF NOT EXISTS agentmesh_event_claims (
    event_id UUID PRIMARY KEY REFERENCES agentmesh_events(event_id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    claim_token UUID NOT NULL UNIQUE,
    claimed_at TIMESTAMPTZ NOT NULL,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    attempt_number INTEGER NOT NULL DEFAULT 1,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    next_attempt_at TIMESTAMPTZ,
    last_error_code TEXT,
    last_error_message TEXT,
    retryable BOOLEAN NOT NULL DEFAULT FALSE,
    dead_lettered_at TIMESTAMPTZ,
    idempotency_key TEXT NOT NULL DEFAULT gen_random_uuid()::text
);

ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS agent_id TEXT;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS worker_id TEXT;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS claim_token UUID;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS attempt_number INTEGER DEFAULT 1;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS max_attempts INTEGER DEFAULT 3;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS last_error_code TEXT;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS last_error_message TEXT;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS retryable BOOLEAN DEFAULT FALSE;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS dead_lettered_at TIMESTAMPTZ;
ALTER TABLE agentmesh_event_claims ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

UPDATE agentmesh_event_claims SET attempt_number = 1 WHERE attempt_number IS NULL;
UPDATE agentmesh_event_claims SET max_attempts = 3 WHERE max_attempts IS NULL;
UPDATE agentmesh_event_claims SET retryable = FALSE WHERE retryable IS NULL;
UPDATE agentmesh_event_claims
SET idempotency_key = gen_random_uuid()::text
WHERE idempotency_key IS NULL;

ALTER TABLE agentmesh_event_claims ALTER COLUMN agent_id SET NOT NULL;
ALTER TABLE agentmesh_event_claims ALTER COLUMN worker_id SET NOT NULL;
ALTER TABLE agentmesh_event_claims ALTER COLUMN claim_token SET NOT NULL;
ALTER TABLE agentmesh_event_claims ALTER COLUMN claimed_at SET NOT NULL;
ALTER TABLE agentmesh_event_claims ALTER COLUMN lease_expires_at SET NOT NULL;
ALTER TABLE agentmesh_event_claims ALTER COLUMN attempt_number SET NOT NULL;
ALTER TABLE agentmesh_event_claims ALTER COLUMN max_attempts SET NOT NULL;
ALTER TABLE agentmesh_event_claims ALTER COLUMN retryable SET NOT NULL;
ALTER TABLE agentmesh_event_claims ALTER COLUMN idempotency_key SET NOT NULL;

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

CREATE INDEX IF NOT EXISTS ix_agentmesh_event_claims_retry
    ON agentmesh_event_claims (next_attempt_at)
    WHERE completed_at IS NULL AND dead_lettered_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_agentmesh_event_claims_dead_letter
    ON agentmesh_event_claims (dead_lettered_at)
    WHERE dead_lettered_at IS NOT NULL;
