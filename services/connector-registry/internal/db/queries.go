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
}

// MockQueries is a simple in-memory implementation of Queries for testing.
type MockQueries struct {
	connectors map[string]*Connector
}

func NewMockQueries() *MockQueries {
	return &MockQueries{
		connectors: make(map[string]*Connector),
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

// Error types
type QueryError string

const (
	ErrConnectorNotFound QueryError = "connector not found"
)

func (e QueryError) Error() string {
	return string(e)
}
