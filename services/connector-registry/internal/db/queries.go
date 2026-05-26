package db

import (
	"context"
)

// Queries defines database operations for the connector registry.
type Queries interface {
	InsertConnector(ctx context.Context, connector *Connector) error
	GetConnectorByID(ctx context.Context, id string) (*Connector, error)
	GetConnectorsByWorkspace(ctx context.Context, workspaceID string) ([]*Connector, error)
	UpdateConnector(ctx context.Context, connector *Connector) error
	DeleteConnector(ctx context.Context, id string) error
	CreateGrant(ctx context.Context, connectorID string, granteeWorkspaceID string) (*SharingGrant, error)
	RevokeGrant(ctx context.Context, connectorID string, grantID string) error
	ListActiveGrants(ctx context.Context, workspaceID string) ([]*SharingGrant, error)
}

// MockQueries is a simple in-memory implementation of Queries for testing.
type MockQueries struct {
	connectors map[string]*Connector
	grants     map[string]*SharingGrant
}

func NewMockQueries() *MockQueries {
	return &MockQueries{
		connectors: make(map[string]*Connector),
		grants:     make(map[string]*SharingGrant),
	}
}

func (m *MockQueries) InsertConnector(ctx context.Context, connector *Connector) error {
	m.connectors[connector.ID] = connector
	return nil
}

func (m *MockQueries) GetConnectorByID(ctx context.Context, id string) (*Connector, error) {
	connector, ok := m.connectors[id]
	if !ok {
		return nil, ErrConnectorNotFound
	}
	return connector, nil
}

func (m *MockQueries) GetConnectorsByWorkspace(ctx context.Context, workspaceID string) ([]*Connector, error) {
	var result []*Connector
	for _, c := range m.connectors {
		if c.WorkspaceID == workspaceID {
			result = append(result, c)
		}
	}
	return result, nil
}

func (m *MockQueries) UpdateConnector(ctx context.Context, connector *Connector) error {
	if _, ok := m.connectors[connector.ID]; !ok {
		return ErrConnectorNotFound
	}
	m.connectors[connector.ID] = connector
	return nil
}

func (m *MockQueries) DeleteConnector(ctx context.Context, id string) error {
	delete(m.connectors, id)
	return nil
}

func (m *MockQueries) CreateGrant(ctx context.Context, connectorID string, granteeWorkspaceID string) (*SharingGrant, error) {
	grant := &SharingGrant{
		ID:                 connectorID + ":" + granteeWorkspaceID,
		ConnectorID:        connectorID,
		GranteeWorkspaceID: granteeWorkspaceID,
		Status:             "active",
	}
	m.grants[grant.ID] = grant
	return grant, nil
}

func (m *MockQueries) RevokeGrant(ctx context.Context, connectorID string, grantID string) error {
	grant, ok := m.grants[grantID]
	if !ok || grant.ConnectorID != connectorID {
		return ErrConnectorNotFound
	}
	grant.Status = "revoked"
	m.grants[grantID] = grant
	return nil
}

func (m *MockQueries) ListActiveGrants(ctx context.Context, workspaceID string) ([]*SharingGrant, error) {
	var result []*SharingGrant
	for _, grant := range m.grants {
		if grant.GranteeWorkspaceID == workspaceID && grant.Status == "active" {
			result = append(result, grant)
		}
	}
	return result, nil
}

// Error types
type QueryError string

const (
	ErrConnectorNotFound QueryError = "connector not found"
)

func (e QueryError) Error() string {
	return string(e)
}
