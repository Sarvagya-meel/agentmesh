CREATE TABLE IF NOT EXISTS agentmesh_agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0.0',
    description TEXT NOT NULL DEFAULT '',
    endpoint TEXT,
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    skills JSONB NOT NULL DEFAULT '[]'::jsonb,
    owner TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL DEFAULT 'online',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_agentmesh_agents_status
        CHECK (status IN ('online', 'offline', 'stale', 'starting'))
);

ALTER TABLE agentmesh_agents ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE agentmesh_agents ADD COLUMN IF NOT EXISTS version TEXT DEFAULT '1.0.0';
ALTER TABLE agentmesh_agents ADD COLUMN IF NOT EXISTS description TEXT DEFAULT '';
ALTER TABLE agentmesh_agents ADD COLUMN IF NOT EXISTS endpoint TEXT;
ALTER TABLE agentmesh_agents ADD COLUMN IF NOT EXISTS capabilities JSONB DEFAULT '[]'::jsonb;
ALTER TABLE agentmesh_agents ADD COLUMN IF NOT EXISTS skills JSONB DEFAULT '[]'::jsonb;
ALTER TABLE agentmesh_agents ADD COLUMN IF NOT EXISTS owner TEXT DEFAULT 'unknown';
ALTER TABLE agentmesh_agents ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'online';
ALTER TABLE agentmesh_agents ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;
ALTER TABLE agentmesh_agents ADD COLUMN IF NOT EXISTS registered_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE agentmesh_agents ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE agentmesh_agents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

UPDATE agentmesh_agents SET version = '1.0.0' WHERE version IS NULL;
UPDATE agentmesh_agents SET description = '' WHERE description IS NULL;
UPDATE agentmesh_agents SET capabilities = '[]'::jsonb WHERE capabilities IS NULL;
UPDATE agentmesh_agents SET skills = '[]'::jsonb WHERE skills IS NULL;
UPDATE agentmesh_agents SET owner = 'unknown' WHERE owner IS NULL;
UPDATE agentmesh_agents SET status = 'online' WHERE status IS NULL;
UPDATE agentmesh_agents SET metadata = '{}'::jsonb WHERE metadata IS NULL;
UPDATE agentmesh_agents SET registered_at = CURRENT_TIMESTAMP WHERE registered_at IS NULL;
UPDATE agentmesh_agents SET last_seen = CURRENT_TIMESTAMP WHERE last_seen IS NULL;
UPDATE agentmesh_agents SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL;

ALTER TABLE agentmesh_agents ALTER COLUMN name SET NOT NULL;
ALTER TABLE agentmesh_agents ALTER COLUMN version SET NOT NULL;
ALTER TABLE agentmesh_agents ALTER COLUMN description SET NOT NULL;
ALTER TABLE agentmesh_agents ALTER COLUMN capabilities SET NOT NULL;
ALTER TABLE agentmesh_agents ALTER COLUMN skills SET NOT NULL;
ALTER TABLE agentmesh_agents ALTER COLUMN owner SET NOT NULL;
ALTER TABLE agentmesh_agents ALTER COLUMN status SET NOT NULL;
ALTER TABLE agentmesh_agents ALTER COLUMN metadata SET NOT NULL;
ALTER TABLE agentmesh_agents ALTER COLUMN registered_at SET NOT NULL;
ALTER TABLE agentmesh_agents ALTER COLUMN last_seen SET NOT NULL;
ALTER TABLE agentmesh_agents ALTER COLUMN updated_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_agentmesh_agents_status'
    ) THEN
        ALTER TABLE agentmesh_agents
            ADD CONSTRAINT ck_agentmesh_agents_status
            CHECK (status IN ('online', 'offline', 'stale', 'starting'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_agentmesh_agents_status_last_seen
    ON agentmesh_agents (status, last_seen);

CREATE INDEX IF NOT EXISTS ix_agentmesh_agents_capabilities
    ON agentmesh_agents USING GIN (capabilities);

CREATE INDEX IF NOT EXISTS ix_agentmesh_agents_skills
    ON agentmesh_agents USING GIN (skills);
