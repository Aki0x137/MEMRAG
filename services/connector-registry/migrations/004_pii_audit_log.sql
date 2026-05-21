-- +goose Up
CREATE TABLE pii_audit_log (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connector_id     UUID NOT NULL,
    workspace_id     TEXT NOT NULL,
    resource_id      TEXT NOT NULL,
    chunk_index      INTEGER NOT NULL,
    entity_category  TEXT NOT NULL,
    action_taken     TEXT NOT NULL CHECK (action_taken IN ('masked','redacted','dropped')),
    detected_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ON pii_audit_log (connector_id, detected_at);
CREATE INDEX ON pii_audit_log (workspace_id, detected_at);

-- +goose Down
DROP TABLE IF EXISTS pii_audit_log;
