"""PyIceberg catalog helpers for memory tombstone archival."""

from __future__ import annotations

import os
from functools import lru_cache

import boto3
from pyiceberg.catalog import load_catalog
from pyiceberg.exceptions import NoSuchNamespaceError, NoSuchTableError
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.transforms import DayTransform, IdentityTransform
from pyiceberg.types import FloatType, NestedField, StringType, TimestampType, TimestamptzType


def _catalog_properties() -> dict[str, str]:
    warehouse = f"s3://{os.getenv('AWS_S3_BUCKET', 'memrag-archive')}"
    props = {
        "type": "sql",
        "uri": os.getenv(
            "ICEBERG_CATALOG_URI",
            f"postgresql+psycopg2://{os.getenv('POSTGRES_USER', 'postgres')}:{os.getenv('POSTGRES_PASSWORD', 'postgres')}@{os.getenv('POSTGRES_HOST', 'postgres')}:5432/{os.getenv('POSTGRES_DB', 'memrag')}",
        ),
        "warehouse": warehouse,
        "s3.endpoint": os.getenv("AWS_S3_ENDPOINT_URL", "http://minio:9000"),
        "s3.access-key-id": os.getenv("AWS_ACCESS_KEY_ID", os.getenv("MINIO_ROOT_USER", "minioadmin")),
        "s3.secret-access-key": os.getenv("AWS_SECRET_ACCESS_KEY", os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")),
        "s3.region": os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
        "s3.path-style-access": os.getenv("AWS_S3_FORCE_PATH_STYLE", "true").lower(),
    }
    session_token = os.getenv("AWS_SESSION_TOKEN")
    if session_token:
        props["s3.session-token"] = session_token
    return props


def get_boto3_session() -> boto3.session.Session:
    """Return a boto3 session for the configured archive backend."""

    return boto3.session.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("MINIO_ROOT_USER", "minioadmin"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY") or os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN") or None,
        region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
    )


@lru_cache(maxsize=1)
def load_tombstone_catalog():
    """Load the Iceberg catalog configured for tombstone archival."""

    return load_catalog("memrag", **_catalog_properties())


def _tombstone_schema() -> Schema:
    return Schema(
        NestedField(1, "workspace_id", StringType(root=False), required=True),
        NestedField(2, "agent_id", StringType(root=False), required=True),
        NestedField(3, "memory_type", StringType(root=False), required=True),
        NestedField(4, "content", StringType(root=False), required=True),
        NestedField(5, "decay_score", FloatType(root=False), required=True),
        NestedField(6, "created_at", TimestamptzType(root=False), required=True),
        NestedField(7, "last_accessed_at", TimestamptzType(root=False), required=True),
        NestedField(8, "tombstoned_at", TimestamptzType(root=False), required=True),
        NestedField(9, "content_hash", StringType(root=False), required=True),
    )


def _tombstone_spec() -> PartitionSpec:
    return PartitionSpec(
        PartitionField(source_id=1, field_id=1001, transform=IdentityTransform(), name="workspace_id"),
        PartitionField(source_id=8, field_id=1002, transform=DayTransform(root=False), name="tombstoned_day"),
    )


def get_tombstone_table() -> Table:
    """Load the tombstone table, creating namespace/table on first use."""

    catalog = load_tombstone_catalog()
    namespace = ("memrag",)
    identifier = (*namespace, "memory_tombstones")
    try:
        return catalog.load_table(identifier)
    except NoSuchNamespaceError:
        catalog.create_namespace(namespace)
    except NoSuchTableError:
        pass

    try:
        return catalog.load_table(identifier)
    except NoSuchTableError:
        return catalog.create_table(identifier, schema=_tombstone_schema(), partition_spec=_tombstone_spec())
