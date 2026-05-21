-- +goose Up
CREATE TABLE knowledge_sync_state (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connector_id     UUID NOT NULL REFERENCES knowledge_connectors(id) ON DELETE CASCADE,
    resource_id      TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    last_synced_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (connector_id, resource_id)
);

CREATE INDEX ON knowledge_sync_state (connector_id);

-- +goose Down
DROP TABLE IF EXISTS knowledge_sync_state;
