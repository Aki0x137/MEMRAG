"""RDS/PostgreSQL schema connector for fetching database structure."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import psycopg2

from connectors import BaseConnector, Resource


class RDSSchemaConnector(BaseConnector):
    """Connector for PostgreSQL/RDS schema inspection."""

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 5432)
        self.database = config.get("database", "")
        self.username = config.get("username", "")
        self.password = config.get("password", os.getenv("RDS_PASSWORD", ""))
        self.schema_filters = config.get("schema_filters", ["public"])
        self.use_iam_auth = config.get("use_iam_auth", False)
        self.conn: psycopg2.extensions.connection | None = None

    async def authenticate(self) -> None:
        """Connect to the database."""
        try:
            self.conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.username,
                password=self.password,
            )
        except psycopg2.Error as e:
            raise RuntimeError(f"Database connection failed: {e}")

    async def list_resources(self) -> list[Resource]:
        """List all tables in the configured schemas."""
        if not self.conn:
            raise RuntimeError("Not authenticated")

        resources: list[Resource] = []
        schema_list = ",".join(f"'{s}'" for s in self.schema_filters)

        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT table_schema, table_name, 
                       EXTRACT(EPOCH FROM NOW())::int AS last_modified_ts
                FROM information_schema.tables
                WHERE table_schema IN ({schema_list})
                  AND table_type = 'BASE TABLE'
                ORDER BY table_schema, table_name
                """
            )
            for schema, table, ts in cur.fetchall():
                resources.append(
                    Resource(
                        id=f"{schema}.{table}",
                        url=None,
                        title=f"{schema}.{table}",
                        last_modified=datetime.fromtimestamp(ts, tz=timezone.utc),
                    )
                )
        return resources

    async def fetch_resource(self, resource_id: str) -> bytes:
        """Fetch schema definition for a single table (no row data)."""
        if not self.conn:
            raise RuntimeError("Not authenticated")

        schema, table = resource_id.split(".", 1)

        with self.conn.cursor() as cur:
            # Fetch columns
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default, col_description('"' || $1 || '"'::regclass::oid, ordinal_position) AS column_comment
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (schema, table),
            )
            columns = cur.fetchall()

            # Fetch foreign keys
            cur.execute(
                """
                SELECT constraint_name, column_name, referenced_table_schema, referenced_table_name, referenced_column_name
                FROM information_schema.referential_constraints rc
                JOIN information_schema.key_column_usage kcu
                  ON rc.constraint_name = kcu.constraint_name
                WHERE rc.constraint_schema = %s AND kcu.table_name = %s
                """,
                (schema, table),
            )
            fks = cur.fetchall()

        # Build schema template
        lines = [f"-- Schema: {schema}.{table}"]
        lines.append(f"CREATE TABLE {schema}.{table} (")
        
        for col_name, col_type, is_nullable, col_default, col_comment in columns:
            nullable = "NOT NULL" if is_nullable == "NO" else "NULL"
            default = f"DEFAULT {col_default}" if col_default else ""
            comment = f"-- {col_comment}" if col_comment else ""
            lines.append(f"  {col_name} {col_type} {nullable} {default} {comment}".strip())
        
        if fks:
            lines.append("  -- Foreign Keys:")
            for fk_name, col, ref_schema, ref_table, ref_col in fks:
                lines.append(f"  -- CONSTRAINT {fk_name}: {col} -> {ref_schema}.{ref_table}({ref_col})")
        
        lines.append(");")
        content = "\n".join(lines)
        return content.encode("utf-8")

    def __del__(self) -> None:
        """Close connection on cleanup."""
        if self.conn:
            self.conn.close()
