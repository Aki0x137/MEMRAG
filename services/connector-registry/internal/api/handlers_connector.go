package api

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"memrag/connector-registry/internal/db"
	"memrag/connector-registry/internal/temporal"
)

// CreateConnectorRequest matches the connector management API contract.
type CreateConnectorRequest struct {
	SourceType      string                 `json:"source_type"`
	DisplayName     string                 `json:"display_name"`
	CredentialRef   string                 `json:"credential_ref"`
	Config          map[string]interface{} `json:"config"`
	ContainsPII     bool                   `json:"contains_pii"`
	SharingScope    string                 `json:"sharing_scope"`
	AgentScope      string                 `json:"agent_scope"`
	AllowedAgentIDs []string               `json:"allowed_agent_ids"`
	AllowedAgentTags []string              `json:"allowed_agent_tags"`
	SyncSchedule    string                 `json:"sync_schedule"`
}

type ConnectorResponse struct {
	ID          string    `json:"id"`
	WorkspaceID string    `json:"workspace_id"`
	SourceType  string    `json:"source_type"`
	DisplayName string    `json:"display_name"`
	ContainsPII bool      `json:"contains_pii"`
	SharingScope string   `json:"sharing_scope"`
	SyncStatus  string    `json:"sync_status"`
	CreatedAt   time.Time `json:"created_at"`
}

type ErrorResponse struct {
	Error string `json:"error"`
}

// CreateConnector handles POST /v1/connectors
func CreateConnector(tc *temporal.TemporalClient, queries db.Queries) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		workspaceID := r.Header.Get("X-Workspace-ID")
		if workspaceID == "" {
			http.Error(w, `{"error":"missing X-Workspace-ID header"}`, http.StatusBadRequest)
			return
		}

		var req CreateConnectorRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
			return
		}

		// Validate required fields
		if req.SourceType == "" || req.DisplayName == "" || req.CredentialRef == "" {
			http.Error(w, `{"error":"missing required fields: source_type, display_name, credential_ref"}`, http.StatusBadRequest)
			return
		}

		connectorID := uuid.New().String()
		now := time.Now()

		// Convert map to json.RawMessage
		configBytes, err := json.Marshal(req.Config)
		if err != nil {
			http.Error(w, `{"error":"invalid config format"}`, http.StatusBadRequest)
			return
		}

		// Insert connector into DB (sync_status = "pending")
		err = queries.InsertConnector(r.Context(), &db.Connector{
			ID:            connectorID,
			WorkspaceID:   workspaceID,
			SourceType:    req.SourceType,
			DisplayName:   req.DisplayName,
			CredentialRef: req.CredentialRef,
			Config:        json.RawMessage(configBytes),
			ContainsPII:   req.ContainsPII,
			SharingScope:  req.SharingScope,
			AgentScope:    req.AgentScope,
			SyncStatus:    "pending",
			CreatedAt:     now,
		})
		if err != nil {
			http.Error(w, `{"error":"failed to create connector"}`, http.StatusInternalServerError)
			return
		}

		// Enqueue IngestionWorkflow
		_, err = tc.StartIngestionWorkflow(r.Context(), connectorID, workspaceID, req.ContainsPII)
		if err != nil {
			// Log error but still return success to client
			fmt.Printf("Failed to enqueue IngestionWorkflow: %v\n", err)
		}

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		json.NewEncoder(w).Encode(ConnectorResponse{
			ID:          connectorID,
			WorkspaceID: workspaceID,
			SourceType:  req.SourceType,
			DisplayName: req.DisplayName,
			ContainsPII: req.ContainsPII,
			SharingScope: req.SharingScope,
			SyncStatus:  "pending",
			CreatedAt:   now,
		})
	}
}

// GetConnectors handles GET /v1/connectors
func GetConnectors(queries db.Queries) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		workspaceID := r.Header.Get("X-Workspace-ID")
		if workspaceID == "" {
			http.Error(w, `{"error":"missing X-Workspace-ID header"}`, http.StatusBadRequest)
			return
		}

		connectors, err := queries.GetConnectorsByWorkspace(r.Context(), workspaceID)
		if err != nil {
			http.Error(w, `{"error":"failed to fetch connectors"}`, http.StatusInternalServerError)
			return
		}

		responses := make([]ConnectorResponse, len(connectors))
		for i, c := range connectors {
			responses[i] = ConnectorResponse{
				ID:          c.ID,
				WorkspaceID: c.WorkspaceID,
				SourceType:  c.SourceType,
				DisplayName: c.DisplayName,
				ContainsPII: c.ContainsPII,
				SharingScope: c.SharingScope,
				SyncStatus:  c.SyncStatus,
				CreatedAt:   c.CreatedAt,
			}
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{"connectors": responses})
	}
}

// GetConnector handles GET /v1/connectors/{id}
func GetConnector(queries db.Queries) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		workspaceID := r.Header.Get("X-Workspace-ID")
		if workspaceID == "" {
			http.Error(w, `{"error":"missing X-Workspace-ID header"}`, http.StatusBadRequest)
			return
		}

		connectorID := chi.URLParam(r, "id")
		connector, err := queries.GetConnectorByID(r.Context(), connectorID)
		if err != nil {
			http.Error(w, `{"error":"connector not found"}`, http.StatusNotFound)
			return
		}

		if connector.WorkspaceID != workspaceID {
			http.Error(w, `{"error":"unauthorized"}`, http.StatusForbidden)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(ConnectorResponse{
			ID:          connector.ID,
			WorkspaceID: connector.WorkspaceID,
			SourceType:  connector.SourceType,
			DisplayName: connector.DisplayName,
			ContainsPII: connector.ContainsPII,
			SharingScope: connector.SharingScope,
			SyncStatus:  connector.SyncStatus,
			CreatedAt:   connector.CreatedAt,
		})
	}
}

// PatchConnector handles PATCH /v1/connectors/{id}
func PatchConnector(queries db.Queries) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		workspaceID := r.Header.Get("X-Workspace-ID")
		if workspaceID == "" {
			http.Error(w, `{"error":"missing X-Workspace-ID header"}`, http.StatusBadRequest)
			return
		}

		connectorID := chi.URLParam(r, "id")
		connector, err := queries.GetConnectorByID(r.Context(), connectorID)
		if err != nil {
			http.Error(w, `{"error":"connector not found"}`, http.StatusNotFound)
			return
		}

		if connector.WorkspaceID != workspaceID {
			http.Error(w, `{"error":"unauthorized"}`, http.StatusForbidden)
			return
		}

		var updates map[string]interface{}
		if err := json.NewDecoder(r.Body).Decode(&updates); err != nil {
			http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
			return
		}

		// Update fields as needed
		if displayName, ok := updates["display_name"].(string); ok {
			connector.DisplayName = displayName
		}
		if config, ok := updates["config"].(map[string]interface{}); ok {
			configBytes, err := json.Marshal(config)
			if err == nil {
				connector.Config = json.RawMessage(configBytes)
			}
		}

		err = queries.UpdateConnector(r.Context(), connector)
		if err != nil {
			http.Error(w, `{"error":"failed to update connector"}`, http.StatusInternalServerError)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(ConnectorResponse{
			ID:          connector.ID,
			WorkspaceID: connector.WorkspaceID,
			SourceType:  connector.SourceType,
			DisplayName: connector.DisplayName,
			ContainsPII: connector.ContainsPII,
			SharingScope: connector.SharingScope,
			SyncStatus:  connector.SyncStatus,
			CreatedAt:   connector.CreatedAt,
		})
	}
}

// DeleteConnector handles DELETE /v1/connectors/{id}
func DeleteConnector(queries db.Queries) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		workspaceID := r.Header.Get("X-Workspace-ID")
		if workspaceID == "" {
			http.Error(w, `{"error":"missing X-Workspace-ID header"}`, http.StatusBadRequest)
			return
		}

		connectorID := chi.URLParam(r, "id")
		connector, err := queries.GetConnectorByID(r.Context(), connectorID)
		if err != nil {
			http.Error(w, `{"error":"connector not found"}`, http.StatusNotFound)
			return
		}

		if connector.WorkspaceID != workspaceID {
			http.Error(w, `{"error":"unauthorized"}`, http.StatusForbidden)
			return
		}

		// Delete connector (Qdrant cleanup is background async)
		err = queries.DeleteConnector(r.Context(), connectorID)
		if err != nil {
			http.Error(w, `{"error":"failed to delete connector"}`, http.StatusInternalServerError)
			return
		}

		w.WriteHeader(http.StatusNoContent)
	}
}

// GetConnectorStatus handles GET /v1/connectors/{id}/status
func GetConnectorStatus(queries db.Queries) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		workspaceID := r.Header.Get("X-Workspace-ID")
		if workspaceID == "" {
			http.Error(w, `{"error":"missing X-Workspace-ID header"}`, http.StatusBadRequest)
			return
		}

		connectorID := chi.URLParam(r, "id")
		connector, err := queries.GetConnectorByID(r.Context(), connectorID)
		if err != nil {
			http.Error(w, `{"error":"connector not found"}`, http.StatusNotFound)
			return
		}

		if connector.WorkspaceID != workspaceID {
			http.Error(w, `{"error":"unauthorized"}`, http.StatusForbidden)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"sync_status": connector.SyncStatus,
		})
	}
}
