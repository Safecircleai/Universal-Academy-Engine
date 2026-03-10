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
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "002_v3_agent_federation_fields"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # agent_runs v3 audit fields
    op.add_column("agent_runs", sa.Column("model_id", sa.String(128), nullable=True))
    op.add_column("agent_runs", sa.Column("prompt_type", sa.String(64), nullable=True))
    op.add_column("agent_runs", sa.Column("input_source_ids", sa.JSON(), nullable=True))
    op.add_column("agent_runs", sa.Column("output_hash", sa.String(64), nullable=True))
    op.add_column("agent_runs", sa.Column("requires_review", sa.Boolean(),
                                          nullable=False, server_default="1"))

    # federated_claim_records transport signature
    op.add_column("federated_claim_records",
                  sa.Column("message_signature", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "model_id")
    op.drop_column("agent_runs", "prompt_type")
    op.drop_column("agent_runs", "input_source_ids")
    op.drop_column("agent_runs", "output_hash")
    op.drop_column("agent_runs", "requires_review")
    op.drop_column("federated_claim_records", "message_signature")
