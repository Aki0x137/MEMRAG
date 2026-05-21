-- name: ListConnectors :many
SELECT id, workspace_id, source_type, display_name, credential_ref, config, contains_pii,
       sharing_scope, agent_scope, allowed_agent_ids, allowed_agent_tags, sync_schedule,
       sync_status, last_synced_at, last_error, created_at, updated_at
FROM knowledge_connectors
WHERE workspace_id = $1;

-- name: GetConnector :one
SELECT id, workspace_id, source_type, display_name, credential_ref, config, contains_pii,
       sharing_scope, agent_scope, allowed_agent_ids, allowed_agent_tags, sync_schedule,
       sync_status, last_synced_at, last_error, created_at, updated_at
FROM knowledge_connectors
WHERE id = $1 AND workspace_id = $2;

-- name: ListActiveGrants :many
SELECT id, connector_id, grantee_workspace_id, status, granted_at, revoked_at, created_at
FROM knowledge_sharing_grants
WHERE grantee_workspace_id = $1 AND status = 'active';
