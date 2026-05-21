-- +goose Up
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE knowledge_connectors (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id        TEXT NOT NULL,
    source_type         TEXT NOT NULL CHECK (source_type IN ('github', 'confluence', 'slack', 'rds_schema')),
    display_name        TEXT NOT NULL,
    credential_ref      TEXT NOT NULL,
    config              JSONB NOT NULL,
    contains_pii        BOOLEAN NOT NULL DEFAULT FALSE,
    sharing_scope       TEXT NOT NULL DEFAULT 'private'
                            CHECK (sharing_scope IN ('private','workspace_internal','allowlist','platform_public')),
    agent_scope         TEXT NOT NULL DEFAULT 'all'
                            CHECK (agent_scope IN ('all','by_id','by_tag')),
    allowed_agent_ids   TEXT[] NOT NULL DEFAULT '{}',
    allowed_agent_tags  TEXT[] NOT NULL DEFAULT '{}',
    sync_schedule       TEXT,
    sync_status         TEXT NOT NULL DEFAULT 'pending'
                            CHECK (sync_status IN ('pending','running','ok','error','pii_detected_mismatch')),
    last_synced_at      TIMESTAMPTZ,
    last_error          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON knowledge_connectors (workspace_id);
CREATE INDEX ON knowledge_connectors (sync_status);

-- +goose Down
DROP TABLE IF EXISTS knowledge_connectors;
