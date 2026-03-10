"""Add v3 fields: agent_runs audit columns + federation message_signature

Revision ID: 002_v3_agent_federation_fields
Revises: 001_initial_schema
Create Date: 2026-03-10 00:01:00.000000

Adds:
  - agent_runs.model_id
  - agent_runs.prompt_type
  - agent_runs.input_source_ids
  - agent_runs.output_hash
  - agent_runs.requires_review
  - federated_claim_records.message_signature

Idempotent: each column is only added if it does not already exist.
This handles databases that had v3 columns added via create_all before
this migration was formally introduced.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "002_v3_agent_federation_fields"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """Return True if the column already exists in the table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def _add_if_missing(table: str, column_name: str, column_def: sa.Column) -> None:
    """Add a column only if it does not already exist."""
    if not _has_column(table, column_name):
        op.add_column(table, column_def)


def upgrade() -> None:
    # agent_runs v3 audit fields
    _add_if_missing("agent_runs", "model_id",
                    sa.Column("model_id", sa.String(128), nullable=True))
    _add_if_missing("agent_runs", "prompt_type",
                    sa.Column("prompt_type", sa.String(64), nullable=True))
    _add_if_missing("agent_runs", "input_source_ids",
                    sa.Column("input_source_ids", sa.JSON(), nullable=True))
    _add_if_missing("agent_runs", "output_hash",
                    sa.Column("output_hash", sa.String(64), nullable=True))
    _add_if_missing("agent_runs", "requires_review",
                    sa.Column("requires_review", sa.Boolean(),
                              nullable=False, server_default="true"))

    # federated_claim_records transport signature
    _add_if_missing("federated_claim_records", "message_signature",
                    sa.Column("message_signature", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "model_id")
    op.drop_column("agent_runs", "prompt_type")
    op.drop_column("agent_runs", "input_source_ids")
    op.drop_column("agent_runs", "output_hash")
    op.drop_column("agent_runs", "requires_review")
    op.drop_column("federated_claim_records", "message_signature")
