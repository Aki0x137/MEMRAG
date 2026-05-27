package api

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"memrag/connector-registry/internal/db"
)

type createGrantRequest struct {
	GranteeWorkspaceID string `json:"grantee_workspace_id"`
}

func CreateGrant(queries db.Queries) http.HandlerFunc {
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

		var req createGrantRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.GranteeWorkspaceID == "" {
			http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
			return
		}

		grant, err := queries.CreateGrant(r.Context(), connectorID, req.GranteeWorkspaceID)
		if err != nil {
			http.Error(w, `{"error":"failed to create grant"}`, http.StatusInternalServerError)
			return
		}
		if grant.ID == "" {
			grant.ID = uuid.NewString()
		}

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		json.NewEncoder(w).Encode(grant)
	}
}

func DeleteGrant(queries db.Queries) http.HandlerFunc {
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

		grantID := chi.URLParam(r, "grant_id")
		if grantID == "" {
			http.Error(w, `{"error":"grant not found"}`, http.StatusNotFound)
			return
		}

		if err := queries.RevokeGrant(r.Context(), connectorID, grantID); err != nil {
			http.Error(w, `{"error":"failed to revoke grant"}`, http.StatusInternalServerError)
			return
		}

		w.WriteHeader(http.StatusNoContent)
	}
}