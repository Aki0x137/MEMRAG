# Contract: Connector Management API

**Service**: `connector-registry` (Go 1.22, port 8082)  
**Feature**: FR-032  
**Date**: 2026-05-14

All endpoints require `X-Workspace-ID` header. Authentication is handled by the API gateway
(HMAC-validated upstream); the connector-registry trusts the workspace ID from the header.
All responses are `application/json`. Breaking changes increment the major version.

---

## Base URL

```
http://connector-registry:8082/v1
```

In `ENVIRONMENT=test` mode the same service is available; mock external connector APIs
are started alongside it by Compose.

---

## Endpoints

### `POST /v1/connectors`

Create a new knowledge connector for the calling workspace.

**Request body**:

```json
{
  "source_type": "github | confluence | slack | rds_schema",
  "display_name": "string (required, max 128 chars)",
  "credential_ref": "string (path in secrets store, required)",
  "config": {
    // source-specific — see per-connector config schemas below
  },
  "contains_pii": false,
  "sharing_scope": "private | workspace_internal | allowlist | platform_public",
  "agent_scope": "all | by_id | by_tag",
  "allowed_agent_ids": [],
  "allowed_agent_tags": [],
  "sync_schedule": "0 2 * * *"
}
```

**`config` schema by source_type**:

```json
// github
{ "owner": "string", "repo": "string", "branch": "string", "file_extensions": [".py",".go",".md"] }

// confluence
{ "base_url": "https://org.atlassian.net", "space_keys": ["ENG","ARCH"] }

// slack
{ "channel_ids": ["C04ABC123", "C04XYZ456"] }

// rds_schema
{ "host": "string", "port": 5432, "database": "string", "schema_filters": ["public"] }
```

**Response `201 Created`**:

```json
{
  "id": "uuid",
  "workspace_id": "string",
  "source_type": "string",
  "display_name": "string",
  "contains_pii": false,
  "sharing_scope": "private",
  "sync_status": "pending",
  "created_at": "ISO8601"
}
```

**Errors**:
- `400` — validation failure (missing required fields, unknown source_type)
- `409` — a connector with the same `source_type + config` already exists for this workspace

---

### `GET /v1/connectors`

List all connectors for the calling workspace.

**Query params**: `?source_type=github` (optional filter), `?sync_status=error` (optional filter)

**Response `200 OK`**:

```json
{
  "connectors": [
    {
      "id": "uuid",
      "source_type": "string",
      "display_name": "string",
      "sync_status": "string",
      "last_synced_at": "ISO8601 | null",
      "sharing_scope": "string",
      "contains_pii": false
    }
  ]
}
```

---

### `GET /v1/connectors/{id}`

Get full connector detail including config (excluding credential value).

**Response `200 OK`**: full connector object (same fields as POST request body + id, timestamps).

**Errors**: `404` if not found or belongs to different workspace.

---

### `PATCH /v1/connectors/{id}`

Update mutable connector fields. Partial update — only supplied fields are changed.

**Request body** (all fields optional):

```json
{
  "display_name": "string",
  "config": { ... },
  "contains_pii": true,
  "sharing_scope": "workspace_internal",
  "agent_scope": "by_tag",
  "allowed_agent_tags": ["domain:hr"],
  "sync_schedule": "0 6 * * *"
}
```

**Response `200 OK`**: updated connector object.

**Errors**: `400` validation, `404` not found.

---

### `DELETE /v1/connectors/{id}`

Remove connector and all associated sync state. Qdrant chunks for this connector are
enqueued for background deletion (async — may take up to one sync cycle to purge from index).

**Response `204 No Content`**

**Errors**: `404` not found.

---

### `GET /v1/connectors/{id}/status`

Retrieve current sync status and last error detail.

**Response `200 OK`**:

```json
{
  "id": "uuid",
  "sync_status": "ok | running | error | pii_detected_mismatch | pending",
  "last_synced_at": "ISO8601 | null",
  "last_error": "string | null",
  "resources_indexed": 1024,
  "resources_skipped": 87,
  "pii_events_last_sync": 3
}
```

---

### `PATCH /v1/connectors/{id}/pii-review`

**HITL endpoint** — approve or abort a halted `pii_detected_mismatch` ingestion workflow.
Sends a Temporal signal to the waiting `IngestionWorkflow`.

**Request body**:

```json
{
  "action": "approve | abort",
  "reviewer_note": "string (optional, max 512 chars)"
}
```

**`approve`**: signals the workflow to resume ingestion with `contains_pii` silently upgraded
to `true` for this sync cycle. Sets `sync_status: running`.

**`abort`**: signals the workflow to stop. Sets `sync_status: error` with a note
indicating operator-initiated abort.

**Response `200 OK`**:

```json
{
  "id": "uuid",
  "action_taken": "approve | abort",
  "sync_status": "running | error",
  "temporal_signal_sent": true
}
```

**Errors**:
- `400` — invalid action value
- `404` — connector not found
- `409` — connector is not in `pii_detected_mismatch` state

---

## Sharing Grants Sub-Resource

### `POST /v1/connectors/{id}/grants`

Grant a specific workspace access to a `sharing_scope: allowlist` connector.

**Request body**: `{ "grantee_workspace_id": "string" }`

**Response `201 Created`**: `{ "grant_id": "uuid", "status": "active" }`

---

### `DELETE /v1/connectors/{id}/grants/{grant_id}`

Revoke a sharing grant. Takes effect within 60 seconds (Redis TTL expiry of `grants:` key).

**Response `204 No Content`**

---

## Error Response Format

All 4xx and 5xx errors return:

```json
{
  "error": {
    "code": "VALIDATION_ERROR | NOT_FOUND | CONFLICT | INTERNAL_ERROR",
    "message": "human-readable description",
    "field": "offending field name (only for VALIDATION_ERROR)"
  }
}
```
