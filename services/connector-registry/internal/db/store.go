package db

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"time"

	"github.com/lib/pq"
)

type Connector struct {
	ID               string
	WorkspaceID      string
	SourceType       string
	DisplayName      string
	CredentialRef    string
	Config           json.RawMessage
	ContainsPII      bool
	SharingScope     string
	AgentScope       string
	AllowedAgentIDs  []string
	AllowedAgentTags []string
	SyncSchedule     sql.NullString
	SyncStatus       string
	LastSyncedAt     sql.NullTime
	LastError        sql.NullString
	CreatedAt        time.Time
	UpdatedAt        time.Time
}

type SharingGrant struct {
	ID                 string
	ConnectorID        string
	GranteeWorkspaceID string
	Status             string
	GrantedAt          sql.NullTime
	RevokedAt          sql.NullTime
	CreatedAt          time.Time
}

type CreateConnectorInput struct {
	WorkspaceID      string
	SourceType       string
	DisplayName      string
	CredentialRef    string
	Config           json.RawMessage
	ContainsPII      bool
	SharingScope     string
	AgentScope       string
	AllowedAgentIDs  []string
	AllowedAgentTags []string
	SyncSchedule     sql.NullString
}

type UpdateConnectorInput struct {
	DisplayName      sql.NullString
	Config           json.RawMessage
	ContainsPII      sql.NullBool
	SharingScope     sql.NullString
	AgentScope       sql.NullString
	AllowedAgentIDs  []string
	AllowedAgentTags []string
	SyncSchedule     sql.NullString
	SyncStatus       sql.NullString
	LastError        sql.NullString
}

type ListConnectorsFilter struct {
	WorkspaceID string
	SourceType  string
	SyncStatus  string
}

type Store struct {
	db *sql.DB
}

func NewStore(db *sql.DB) *Store {
	return &Store{db: db}
}

func (s *Store) CreateConnector(ctx context.Context, input CreateConnectorInput) (Connector, error) {
	query := `
		INSERT INTO knowledge_connectors (
			workspace_id, source_type, display_name, credential_ref, config, contains_pii,
			sharing_scope, agent_scope, allowed_agent_ids, allowed_agent_tags, sync_schedule, sync_status
		) VALUES (
			$1, $2, $3, $4, $5, $6,
			$7, $8, $9, $10, $11, 'pending'
		)
		RETURNING id, workspace_id, source_type, display_name, credential_ref, config, contains_pii,
		          sharing_scope, agent_scope, allowed_agent_ids, allowed_agent_tags, sync_schedule,
		          sync_status, last_synced_at, last_error, created_at, updated_at`

	var connector Connector
	err := s.db.QueryRowContext(
		ctx,
		query,
		input.WorkspaceID,
		input.SourceType,
		input.DisplayName,
		input.CredentialRef,
		input.Config,
		input.ContainsPII,
		input.SharingScope,
		input.AgentScope,
		pq.Array(input.AllowedAgentIDs),
		pq.Array(input.AllowedAgentTags),
		input.SyncSchedule,
	).Scan(
		&connector.ID,
		&connector.WorkspaceID,
		&connector.SourceType,
		&connector.DisplayName,
		&connector.CredentialRef,
		&connector.Config,
		&connector.ContainsPII,
		&connector.SharingScope,
		&connector.AgentScope,
		pq.Array(&connector.AllowedAgentIDs),
		pq.Array(&connector.AllowedAgentTags),
		&connector.SyncSchedule,
		&connector.SyncStatus,
		&connector.LastSyncedAt,
		&connector.LastError,
		&connector.CreatedAt,
		&connector.UpdatedAt,
	)
	return connector, err
}

func (s *Store) GetConnector(ctx context.Context, workspaceID string, connectorID string) (Connector, error) {
	query := `
		SELECT id, workspace_id, source_type, display_name, credential_ref, config, contains_pii,
		       sharing_scope, agent_scope, allowed_agent_ids, allowed_agent_tags, sync_schedule,
		       sync_status, last_synced_at, last_error, created_at, updated_at
		FROM knowledge_connectors
		WHERE workspace_id = $1 AND id = $2`

	var connector Connector
	err := s.db.QueryRowContext(ctx, query, workspaceID, connectorID).Scan(
		&connector.ID,
		&connector.WorkspaceID,
		&connector.SourceType,
		&connector.DisplayName,
		&connector.CredentialRef,
		&connector.Config,
		&connector.ContainsPII,
		&connector.SharingScope,
		&connector.AgentScope,
		pq.Array(&connector.AllowedAgentIDs),
		pq.Array(&connector.AllowedAgentTags),
		&connector.SyncSchedule,
		&connector.SyncStatus,
		&connector.LastSyncedAt,
		&connector.LastError,
		&connector.CreatedAt,
		&connector.UpdatedAt,
	)
	return connector, err
}

func (s *Store) ListConnectors(ctx context.Context, filter ListConnectorsFilter) ([]Connector, error) {
	query := `
		SELECT id, workspace_id, source_type, display_name, credential_ref, config, contains_pii,
		       sharing_scope, agent_scope, allowed_agent_ids, allowed_agent_tags, sync_schedule,
		       sync_status, last_synced_at, last_error, created_at, updated_at
		FROM knowledge_connectors
		WHERE workspace_id = $1
		  AND ($2 = '' OR source_type = $2)
		  AND ($3 = '' OR sync_status = $3)
		ORDER BY created_at DESC`

	rows, err := s.db.QueryContext(ctx, query, filter.WorkspaceID, filter.SourceType, filter.SyncStatus)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var connectors []Connector
	for rows.Next() {
		var connector Connector
		if err := rows.Scan(
			&connector.ID,
			&connector.WorkspaceID,
			&connector.SourceType,
			&connector.DisplayName,
			&connector.CredentialRef,
			&connector.Config,
			&connector.ContainsPII,
			&connector.SharingScope,
			&connector.AgentScope,
			pq.Array(&connector.AllowedAgentIDs),
			pq.Array(&connector.AllowedAgentTags),
			&connector.SyncSchedule,
			&connector.SyncStatus,
			&connector.LastSyncedAt,
			&connector.LastError,
			&connector.CreatedAt,
			&connector.UpdatedAt,
		); err != nil {
			return nil, err
		}
		connectors = append(connectors, connector)
	}
	return connectors, rows.Err()
}

func (s *Store) UpdateConnector(ctx context.Context, workspaceID string, connectorID string, input UpdateConnectorInput) (Connector, error) {
	query := `
		UPDATE knowledge_connectors
		SET display_name = COALESCE(NULLIF($3, ''), display_name),
		    config = CASE WHEN $4::jsonb IS NULL THEN config ELSE $4::jsonb END,
		    contains_pii = COALESCE($5, contains_pii),
		    sharing_scope = COALESCE(NULLIF($6, ''), sharing_scope),
		    agent_scope = COALESCE(NULLIF($7, ''), agent_scope),
		    allowed_agent_ids = CASE WHEN $8::text[] IS NULL THEN allowed_agent_ids ELSE $8::text[] END,
		    allowed_agent_tags = CASE WHEN $9::text[] IS NULL THEN allowed_agent_tags ELSE $9::text[] END,
		    sync_schedule = COALESCE($10, sync_schedule),
		    sync_status = COALESCE(NULLIF($11, ''), sync_status),
		    last_error = COALESCE($12, last_error),
		    updated_at = NOW()
		WHERE workspace_id = $1 AND id = $2
		RETURNING id, workspace_id, source_type, display_name, credential_ref, config, contains_pii,
		          sharing_scope, agent_scope, allowed_agent_ids, allowed_agent_tags, sync_schedule,
		          sync_status, last_synced_at, last_error, created_at, updated_at`

	var configValue any
	if len(input.Config) > 0 {
		configValue = input.Config
	}

	var connector Connector
	err := s.db.QueryRowContext(
		ctx,
		query,
		workspaceID,
		connectorID,
		input.DisplayName.String,
		configValue,
		nullableBool(input.ContainsPII),
		input.SharingScope.String,
		input.AgentScope.String,
		nullableArray(input.AllowedAgentIDs),
		nullableArray(input.AllowedAgentTags),
		input.SyncSchedule,
		input.SyncStatus.String,
		input.LastError,
	).Scan(
		&connector.ID,
		&connector.WorkspaceID,
		&connector.SourceType,
		&connector.DisplayName,
		&connector.CredentialRef,
		&connector.Config,
		&connector.ContainsPII,
		&connector.SharingScope,
		&connector.AgentScope,
		pq.Array(&connector.AllowedAgentIDs),
		pq.Array(&connector.AllowedAgentTags),
		&connector.SyncSchedule,
		&connector.SyncStatus,
		&connector.LastSyncedAt,
		&connector.LastError,
		&connector.CreatedAt,
		&connector.UpdatedAt,
	)
	return connector, err
}

func (s *Store) DeleteConnector(ctx context.Context, workspaceID string, connectorID string) error {
	result, err := s.db.ExecContext(ctx, `DELETE FROM knowledge_connectors WHERE workspace_id = $1 AND id = $2`, workspaceID, connectorID)
	if err != nil {
		return err
	}
	rowsAffected, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if rowsAffected == 0 {
		return fmt.Errorf("connector not found")
	}
	return nil
}

func (s *Store) CreateGrant(ctx context.Context, connectorID string, granteeWorkspaceID string) (SharingGrant, error) {
	query := `
		INSERT INTO knowledge_sharing_grants (connector_id, grantee_workspace_id, status, granted_at)
		VALUES ($1, $2, 'active', NOW())
		RETURNING id, connector_id, grantee_workspace_id, status, granted_at, revoked_at, created_at`

	var grant SharingGrant
	err := s.db.QueryRowContext(ctx, query, connectorID, granteeWorkspaceID).Scan(
		&grant.ID,
		&grant.ConnectorID,
		&grant.GranteeWorkspaceID,
		&grant.Status,
		&grant.GrantedAt,
		&grant.RevokedAt,
		&grant.CreatedAt,
	)
	return grant, err
}

func (s *Store) RevokeGrant(ctx context.Context, connectorID string, grantID string) error {
	result, err := s.db.ExecContext(
		ctx,
		`UPDATE knowledge_sharing_grants SET status = 'revoked', revoked_at = NOW() WHERE connector_id = $1 AND id = $2`,
		connectorID,
		grantID,
	)
	if err != nil {
		return err
	}
	rowsAffected, err := result.RowsAffected()
	if err != nil {
		return err
	}
	if rowsAffected == 0 {
		return fmt.Errorf("grant not found")
	}
	return nil
}

func (s *Store) ListActiveGrants(ctx context.Context, workspaceID string) ([]SharingGrant, error) {
	rows, err := s.db.QueryContext(
		ctx,
		`SELECT id, connector_id, grantee_workspace_id, status, granted_at, revoked_at, created_at
		 FROM knowledge_sharing_grants
		 WHERE grantee_workspace_id = $1 AND status = 'active'`,
		workspaceID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var grants []SharingGrant
	for rows.Next() {
		var grant SharingGrant
		if err := rows.Scan(
			&grant.ID,
			&grant.ConnectorID,
			&grant.GranteeWorkspaceID,
			&grant.Status,
			&grant.GrantedAt,
			&grant.RevokedAt,
			&grant.CreatedAt,
		); err != nil {
			return nil, err
		}
		grants = append(grants, grant)
	}
	return grants, rows.Err()
}

func nullableArray(values []string) any {
	if values == nil {
		return nil
	}
	return pq.Array(values)
}

func nullableBool(value sql.NullBool) any {
	if !value.Valid {
		return nil
	}
	return value.Bool
}