package temporal

import (
	"context"
	"fmt"
	"os"

	"go.temporal.io/sdk/client"
)

type TemporalClient struct {
	client client.Client
}

func NewTemporalClient() (*TemporalClient, error) {
	temporalHost := os.Getenv("TEMPORAL_HOST")
	if temporalHost == "" {
		temporalHost = "temporal:7233"
	}

	c, err := client.Dial(client.Options{
		HostPort: temporalHost,
	})
	if err != nil {
		return nil, fmt.Errorf("unable to create Temporal client: %w", err)
	}

	return &TemporalClient{client: c}, nil
}

// StartIngestionWorkflow enqueues an ingestion workflow for a connector.
func (tc *TemporalClient) StartIngestionWorkflow(
	ctx context.Context,
	connectorID string,
	workspaceID string,
	containsPII bool,
) (string, error) {
	opts := client.StartWorkflowOptions{
		ID:        fmt.Sprintf("ingestion-%s-%s", connectorID, workspaceID),
		TaskQueue: "ingestion-workers",
	}

	params := map[string]interface{}{
		"connector_id": connectorID,
		"workspace_id": workspaceID,
		"contains_pii": containsPII,
		"sync_mode":    "full",
	}

	we, err := tc.client.ExecuteWorkflow(ctx, opts, "IngestionWorkflow", params)
	if err != nil {
		return "", fmt.Errorf("unable to execute workflow: %w", err)
	}

	return we.GetRunID(), nil
}

// SignalWorkflow sends a signal to a running workflow.
func (tc *TemporalClient) SignalWorkflow(
	ctx context.Context,
	workflowID string,
	runID string,
	signalName string,
	payload interface{},
) error {
	return tc.client.SignalWorkflow(ctx, workflowID, runID, signalName, payload)
}

// Close closes the Temporal client connection.
func (tc *TemporalClient) Close() {
	tc.client.Close()
}
