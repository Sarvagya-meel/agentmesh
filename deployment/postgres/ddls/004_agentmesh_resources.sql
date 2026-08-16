CREATE TABLE IF NOT EXISTS agentmesh_resources (
    resource_id TEXT PRIMARY KEY,
    resource_type TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    endpoint TEXT,
    owner TEXT NOT NULL DEFAULT 'unknown',
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    parent_resource_id TEXT REFERENCES agentmesh_resources(resource_id) ON DELETE SET NULL,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_agentmesh_resources_type
        CHECK (resource_type IN ('agent', 'orchestrator', 'mcp_server', 'tool', 'registry', 'ui', 'service')),
    CONSTRAINT ck_agentmesh_resources_status
        CHECK (status IN ('unknown', 'starting', 'online', 'offline', 'stale', 'failed', 'disabled'))
);

ALTER TABLE agentmesh_resources ADD COLUMN IF NOT EXISTS resource_type TEXT;
ALTER TABLE agentmesh_resources ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE agentmesh_resources ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'unknown';
ALTER TABLE agentmesh_resources ADD COLUMN IF NOT EXISTS endpoint TEXT;
ALTER TABLE agentmesh_resources ADD COLUMN IF NOT EXISTS owner TEXT DEFAULT 'unknown';
ALTER TABLE agentmesh_resources ADD COLUMN IF NOT EXISTS capabilities JSONB DEFAULT '[]'::jsonb;
ALTER TABLE agentmesh_resources ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;
ALTER TABLE agentmesh_resources ADD COLUMN IF NOT EXISTS parent_resource_id TEXT;
ALTER TABLE agentmesh_resources ADD COLUMN IF NOT EXISTS registered_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE agentmesh_resources ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE agentmesh_resources ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;

UPDATE agentmesh_resources SET status = 'unknown' WHERE status IS NULL;
UPDATE agentmesh_resources SET owner = 'unknown' WHERE owner IS NULL;
UPDATE agentmesh_resources SET capabilities = '[]'::jsonb WHERE capabilities IS NULL;
UPDATE agentmesh_resources SET metadata = '{}'::jsonb WHERE metadata IS NULL;
UPDATE agentmesh_resources SET registered_at = CURRENT_TIMESTAMP WHERE registered_at IS NULL;
UPDATE agentmesh_resources SET last_seen = CURRENT_TIMESTAMP WHERE last_seen IS NULL;
UPDATE agentmesh_resources SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL;

ALTER TABLE agentmesh_resources ALTER COLUMN resource_type SET NOT NULL;
ALTER TABLE agentmesh_resources ALTER COLUMN name SET NOT NULL;
ALTER TABLE agentmesh_resources ALTER COLUMN status SET NOT NULL;
ALTER TABLE agentmesh_resources ALTER COLUMN owner SET NOT NULL;
ALTER TABLE agentmesh_resources ALTER COLUMN capabilities SET NOT NULL;
ALTER TABLE agentmesh_resources ALTER COLUMN metadata SET NOT NULL;
ALTER TABLE agentmesh_resources ALTER COLUMN registered_at SET NOT NULL;
ALTER TABLE agentmesh_resources ALTER COLUMN last_seen SET NOT NULL;
ALTER TABLE agentmesh_resources ALTER COLUMN updated_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'agentmesh_resources_parent_resource_id_fkey'
    ) THEN
        ALTER TABLE agentmesh_resources
            ADD CONSTRAINT agentmesh_resources_parent_resource_id_fkey
            FOREIGN KEY (parent_resource_id)
            REFERENCES agentmesh_resources(resource_id)
            ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_agentmesh_resources_type'
    ) THEN
        ALTER TABLE agentmesh_resources
            ADD CONSTRAINT ck_agentmesh_resources_type
            CHECK (resource_type IN ('agent', 'orchestrator', 'mcp_server', 'tool', 'registry', 'ui', 'service'));
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_agentmesh_resources_status'
    ) THEN
        ALTER TABLE agentmesh_resources
            ADD CONSTRAINT ck_agentmesh_resources_status
            CHECK (status IN ('unknown', 'starting', 'online', 'offline', 'stale', 'failed', 'disabled'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_agentmesh_resources_type_status
    ON agentmesh_resources (resource_type, status);

CREATE INDEX IF NOT EXISTS ix_agentmesh_resources_parent
    ON agentmesh_resources (parent_resource_id);

CREATE INDEX IF NOT EXISTS ix_agentmesh_resources_last_seen
    ON agentmesh_resources (last_seen);

CREATE INDEX IF NOT EXISTS ix_agentmesh_resources_capabilities
    ON agentmesh_resources USING GIN (capabilities);
