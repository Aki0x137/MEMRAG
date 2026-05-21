package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"os"
	"path/filepath"

	_ "github.com/lib/pq"
	"github.com/pressly/goose/v3"

	internalaws "memrag/connector-registry/internal/aws"
)

func main() {
	ctx := context.Background()
	if _, err := internalaws.LoadConfig(ctx); err != nil {
		log.Fatalf("load aws config: %v", err)
	}

	databaseURL := os.Getenv("DATABASE_URL")
	if databaseURL == "" {
		log.Fatal("DATABASE_URL is required")
	}

	db, err := sql.Open("postgres", databaseURL)
	if err != nil {
		log.Fatalf("open database: %v", err)
	}
	defer db.Close()

	if err := db.PingContext(ctx); err != nil {
		log.Fatalf("ping database: %v", err)
	}

	if err := goose.SetDialect("postgres"); err != nil {
		log.Fatalf("set goose dialect: %v", err)
	}

	migrationsDir := filepath.Join("migrations")
	if err := goose.Up(db, migrationsDir); err != nil {
		log.Fatalf("run migrations: %v", err)
	}

	fmt.Println("connector-registry migrations applied")
}
