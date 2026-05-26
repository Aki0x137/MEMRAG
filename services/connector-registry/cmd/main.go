package main

import (
	"fmt"
	"net/http"

	"memrag/connector-registry/internal/api"
	"memrag/connector-registry/internal/db"
	"memrag/connector-registry/internal/temporal"
)

func main() {
	// Initialize Temporal client
	tc, err := temporal.NewTemporalClient()
	if err != nil {
		fmt.Printf("Failed to initialize Temporal client: %v\n", err)
		tc = nil
	}
	defer func() {
		if tc != nil {
			tc.Close()
		}
	}()

	// Initialize mock queries for now (will be replaced with real DB in production)
	queries := db.NewMockQueries()

	// Create router
	router := api.NewRouter(tc, queries)

	fmt.Println("Connector Registry starting on :8082")
	if err := http.ListenAndServe(":8082", router); err != nil {
		fmt.Printf("Server error: %v\n", err)
	}
}
