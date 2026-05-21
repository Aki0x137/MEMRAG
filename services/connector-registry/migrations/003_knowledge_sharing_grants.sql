-- +goose Up
CREATE TABLE knowledge_sharing_grants (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connector_id         UUID NOT NULL REFERENCES knowledge_connectors(id) ON DELETE CASCADE,
    grantee_workspace_id TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','active','revoked')),
    granted_at           TIMESTAMPTZ,
    revoked_at           TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (connector_id, grantee_workspace_id)
);

CREATE INDEX ON knowledge_sharing_grants (connector_id);
CREATE INDEX ON knowledge_sharing_grants (grantee_workspace_id, status);

-- +goose Down
DROP TABLE IF EXISTS knowledge_sharing_grants;
