-- +goose Up
CREATE TABLE workflow_executions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    temporal_run_id  TEXT NOT NULL UNIQUE,
    workflow_type    TEXT NOT NULL,
    workspace_id     TEXT NOT NULL,
    agent_id         TEXT,
    connector_id     UUID,
    status           TEXT NOT NULL,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at     TIMESTAMPTZ,
    error_message    TEXT
);

CREATE INDEX ON workflow_executions (workspace_id, started_at DESC);
CREATE INDEX ON workflow_executions (connector_id, started_at DESC);

-- +goose Down
DROP TABLE IF EXISTS workflow_executions;
