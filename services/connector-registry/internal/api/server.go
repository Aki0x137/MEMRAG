package api

import (
	"fmt"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/prometheus/client_golang/prometheus/promhttp"

	"memrag/connector-registry/internal/db"
	"memrag/connector-registry/internal/temporal"
)

func NewRouter(tc *temporal.TemporalClient, queries db.Queries) *chi.Mux {
	r := chi.NewRouter()

	// Middleware
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)

	// Health check
	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"status":"ok"}`)
	})
	r.Handle("/metrics", promhttp.Handler())

	// Connector management API v1
	r.Route("/v1/connectors", func(r chi.Router) {
		r.Post("/", CreateConnector(tc, queries))
		r.Get("/", GetConnectors(queries))
		r.Get("/{id}", GetConnector(queries))
		r.Patch("/{id}", PatchConnector(queries))
		r.Delete("/{id}", DeleteConnector(queries))
		r.Get("/{id}/status", GetConnectorStatus(queries))
		r.Post("/{id}/grants", CreateGrant(queries))
		r.Delete("/{id}/grants/{grant_id}", DeleteGrant(queries))
	})

	return r
}
