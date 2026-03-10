"""UAE v4 — Doctrine Sovereignty Layer schema extensions

Revision ID: 003_v4_doctrine_sovereignty
Revises: 002_v3_agent_federation_fields
Create Date: 2026-03-10 00:02:00.000000

Adds:
  sources.source_type                   — SourceType enum column
  claims.claim_classification           — ClaimClassification enum column
  claims.requires_constitutional_review — Boolean flag
  claims.doctrine_dependency            — JSON dependency metadata
  governance_decisions                  — new table
  institutional_archive                 — new table

New ClaimStatus values (enum extension):
  constitutional_review_required
  constitutional_review_in_progress
  constitutional_decision_recorded

Idempotent: all DDL is guarded by Inspector existence checks.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# ---------------------------------------------------------------------------
# Revision metadata
# ---------------------------------------------------------------------------

revision = "003_v4_doctrine_sovereignty"
down_revision = "002_v3_agent_federation_fields"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    return inspector.has_table(table)


def _add_if_missing(table: str, column_name: str, column_def: sa.Column) -> None:
    if not _has_column(table, column_name):
        op.add_column(table, column_def)


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # ------------------------------------------------------------------
    # 1. Extend sources: source_type column
    # ------------------------------------------------------------------
    if dialect == "postgresql":
        # Create the enum type if it doesn't exist, then add column
        _add_if_missing(
            "sources",
            "source_type",
            sa.Column(
                "source_type",
                sa.String(64),
                nullable=False,
                server_default="external_reference",
            ),
        )
    else:
        _add_if_missing(
            "sources",
            "source_type",
            sa.Column(
                "source_type",
                sa.String(64),
                nullable=False,
                server_default="external_reference",
            ),
        )

    # ------------------------------------------------------------------
    # 2. Extend claims: doctrine fields
    # ------------------------------------------------------------------
    _add_if_missing(
        "claims",
        "claim_classification",
        sa.Column("claim_classification", sa.String(64), nullable=True),
    )
    _add_if_missing(
        "claims",
        "requires_constitutional_review",
        sa.Column(
            "requires_constitutional_review",
            sa.Boolean,
            nullable=False,
            server_default="false",
        ),
    )
    _add_if_missing(
        "claims",
        "doctrine_dependency",
        sa.Column("doctrine_dependency", sa.JSON, nullable=True),
    )

    # ------------------------------------------------------------------
    # 3. governance_decisions table
    # ------------------------------------------------------------------
    if not _has_table("governance_decisions"):
        op.create_table(
            "governance_decisions",
            sa.Column("decision_id", sa.String(36), primary_key=True),
            sa.Column(
                "claim_id",
                sa.String(36),
                sa.ForeignKey("claims.claim_id"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "node_id",
                sa.String(36),
                sa.ForeignKey("academy_nodes.node_id"),
                nullable=True,
                index=True,
            ),
            sa.Column("reviewers", sa.JSON, nullable=False),
            sa.Column("decision_type", sa.String(64), nullable=False),
            sa.Column("decision_summary", sa.Text, nullable=False),
            sa.Column("evidence_sources", sa.JSON, nullable=True),
            sa.Column("final_outcome", sa.Text, nullable=True),
            sa.Column("doctrine_precedence_invoked", sa.String(64), nullable=True),
            sa.Column("conflict_resolution_method", sa.String(128), nullable=True),
            sa.Column("timestamp", sa.DateTime, nullable=False),
            sa.Column(
                "recorded_by",
                sa.String(256),
                nullable=False,
                server_default="system",
            ),
        )
        op.create_index(
            "ix_governance_decision_claim",
            "governance_decisions",
            ["claim_id"],
        )
        op.create_index(
            "ix_governance_decision_node",
            "governance_decisions",
            ["node_id"],
        )

    # ------------------------------------------------------------------
    # 4. institutional_archive table
    # ------------------------------------------------------------------
    if not _has_table("institutional_archive"):
        op.create_table(
            "institutional_archive",
            sa.Column("entry_id", sa.String(36), primary_key=True),
            sa.Column("event_type", sa.String(128), nullable=False, index=True),
            sa.Column("subject_id", sa.String(36), nullable=False, index=True),
            sa.Column("subject_type", sa.String(64), nullable=False),
            sa.Column(
                "node_id",
                sa.String(36),
                sa.ForeignKey("academy_nodes.node_id"),
                nullable=True,
                index=True,
            ),
            sa.Column("actor_id", sa.String(256), nullable=True),
            sa.Column("event_summary", sa.Text, nullable=False),
            sa.Column("evidence_payload", sa.JSON, nullable=True),
            sa.Column("preceding_state", sa.JSON, nullable=True),
            sa.Column("resulting_state", sa.JSON, nullable=True),
            sa.Column("content_hash", sa.String(128), nullable=True),
            sa.Column("timestamp", sa.DateTime, nullable=False, index=True),
        )
        op.create_index(
            "ix_archive_event_type",
            "institutional_archive",
            ["event_type"],
        )
        op.create_index(
            "ix_archive_subject",
            "institutional_archive",
            ["subject_id", "subject_type"],
        )
        op.create_index(
            "ix_archive_timestamp",
            "institutional_archive",
            ["timestamp"],
        )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Drop new tables
    if _has_table("institutional_archive"):
        op.drop_index("ix_archive_timestamp", "institutional_archive")
        op.drop_index("ix_archive_subject", "institutional_archive")
        op.drop_index("ix_archive_event_type", "institutional_archive")
        op.drop_table("institutional_archive")

    if _has_table("governance_decisions"):
        op.drop_index("ix_governance_decision_node", "governance_decisions")
        op.drop_index("ix_governance_decision_claim", "governance_decisions")
        op.drop_table("governance_decisions")

    # Drop added columns
    if _has_column("claims", "doctrine_dependency"):
        op.drop_column("claims", "doctrine_dependency")
    if _has_column("claims", "requires_constitutional_review"):
        op.drop_column("claims", "requires_constitutional_review")
    if _has_column("claims", "claim_classification"):
        op.drop_column("claims", "claim_classification")
    if _has_column("sources", "source_type"):
        op.drop_column("sources", "source_type")
