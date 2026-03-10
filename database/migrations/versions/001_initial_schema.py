"""Initial schema — UAE v1/v2 full model

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-03-10 00:00:00.000000

This migration creates the canonical UAE schema from models.py.
Safe to run on a fresh PostgreSQL or SQLite database.

If the tables were already created by SQLAlchemy create_all (pre-Alembic
deployments), this migration detects that and skips creation — treating
the existing schema as equivalent to this revision.

To stamp an existing database without re-running DDL:
    alembic stamp 001_initial_schema
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def _tables_exist() -> bool:
    """Return True if the schema was already created (pre-Alembic create_all)."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return inspector.has_table("academy_nodes")


def upgrade() -> None:
    if _tables_exist():
        # Tables were created by SQLAlchemy create_all before Alembic was
        # introduced. Skip all DDL — the schema is already equivalent to this
        # revision. Use `alembic stamp 001_initial_schema` to record this.
        return

    # ------------------------------------------------------------------ #
    # academy_nodes                                                        #
    # ------------------------------------------------------------------ #
    op.create_table(
        "academy_nodes",
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("node_name", sa.String(), nullable=False),
        sa.Column("node_type", sa.String(), nullable=False),
        sa.Column("institution_name", sa.String(), nullable=True),
        sa.Column("jurisdiction", sa.String(), nullable=True),
        sa.Column("public_key_pem", sa.Text(), nullable=True),
        sa.Column("contact_email", sa.String(), nullable=True),
        sa.Column("node_url", sa.String(), nullable=True),
        sa.Column("is_federation_member", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("joined_federation_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("node_id"),
        sa.UniqueConstraint("node_name"),
    )

    # ------------------------------------------------------------------ #
    # node_governance_policies                                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        "node_governance_policies",
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("minimum_trust_tier", sa.String(), nullable=False, server_default="TIER2"),
        sa.Column("required_reviewers", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("verification_threshold", sa.Float(), nullable=False, server_default="0.75"),
        sa.Column("require_human_approval", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("allow_imported_claims", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("allow_claim_publication", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("auto_deprecate_days", sa.Integer(), nullable=False, server_default="730"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["node_id"], ["academy_nodes.node_id"]),
        sa.PrimaryKeyConstraint("policy_id"),
        sa.UniqueConstraint("node_id"),
    )

    # ------------------------------------------------------------------ #
    # sources                                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        "sources",
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("origin_node_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("publisher", sa.String(), nullable=True),
        sa.Column("edition", sa.String(), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("document_hash", sa.String(), nullable=False),
        sa.Column("document_fingerprint", sa.String(), nullable=True),
        sa.Column("content_address", sa.String(), nullable=True),
        sa.Column("storage_backend", sa.String(), nullable=False, server_default="LOCAL"),
        sa.Column("trust_tier", sa.String(), nullable=False),
        sa.Column("license", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(), nullable=False, server_default="en"),
        sa.Column("ingest_timestamp", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["origin_node_id"], ["academy_nodes.node_id"]),
        sa.PrimaryKeyConstraint("source_id"),
        sa.UniqueConstraint("document_hash"),
    )

    # ------------------------------------------------------------------ #
    # extracted_texts                                                      #
    # ------------------------------------------------------------------ #
    op.create_table(
        "extracted_texts",
        sa.Column("text_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("extraction_method", sa.String(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["source_id"], ["sources.source_id"]),
        sa.PrimaryKeyConstraint("text_id"),
    )

    # ------------------------------------------------------------------ #
    # concepts                                                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        "concepts",
        sa.Column("concept_id", sa.String(), nullable=False),
        sa.Column("origin_node_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("is_canonical", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["origin_node_id"], ["academy_nodes.node_id"]),
        sa.PrimaryKeyConstraint("concept_id"),
    )

    # ------------------------------------------------------------------ #
    # standards                                                            #
    # ------------------------------------------------------------------ #
    op.create_table(
        "standards",
        sa.Column("standard_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("issuing_body", sa.String(), nullable=True),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("standard_id"),
    )

    # ------------------------------------------------------------------ #
    # competencies                                                         #
    # ------------------------------------------------------------------ #
    op.create_table(
        "competencies",
        sa.Column("competency_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("skill_level", sa.String(), nullable=True),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("industry_standard_reference", sa.String(), nullable=True),
        sa.Column("standard_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["standard_id"], ["standards.standard_id"]),
        sa.PrimaryKeyConstraint("competency_id"),
    )

    # ------------------------------------------------------------------ #
    # claims                                                               #
    # ------------------------------------------------------------------ #
    op.create_table(
        "claims",
        sa.Column("claim_id", sa.String(), nullable=False),
        sa.Column("claim_number", sa.String(), nullable=False),
        sa.Column("origin_node_id", sa.String(), nullable=True),
        sa.Column("publishing_node_id", sa.String(), nullable=True),
        sa.Column("claim_category", sa.String(), nullable=True),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("concept_id", sa.String(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="DRAFT"),
        sa.Column("claim_hash", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("superseded_by_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.concept_id"]),
        sa.ForeignKeyConstraint(["origin_node_id"], ["academy_nodes.node_id"]),
        sa.ForeignKeyConstraint(["publishing_node_id"], ["academy_nodes.node_id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.source_id"]),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["claims.claim_id"]),
        sa.PrimaryKeyConstraint("claim_id"),
        sa.UniqueConstraint("claim_number"),
    )

    # ------------------------------------------------------------------ #
    # claim_revisions                                                      #
    # ------------------------------------------------------------------ #
    op.create_table(
        "claim_revisions",
        sa.Column("revision_id", sa.String(), nullable=False),
        sa.Column("claim_id", sa.String(), nullable=False),
        sa.Column("previous_version", sa.Integer(), nullable=True),
        sa.Column("updated_version", sa.Integer(), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(), nullable=True),
        sa.Column("node_id", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.claim_id"]),
        sa.PrimaryKeyConstraint("revision_id"),
    )

    # ------------------------------------------------------------------ #
    # claim_evidence                                                       #
    # ------------------------------------------------------------------ #
    op.create_table(
        "claim_evidence",
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("claim_id", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("page_range", sa.String(), nullable=True),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column("paragraph", sa.Integer(), nullable=True),
        sa.Column("figure_reference", sa.String(), nullable=True),
        sa.Column("timecode", sa.String(), nullable=True),
        sa.Column("exact_quote", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("evidence_text_hash", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.claim_id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.source_id"]),
        sa.PrimaryKeyConstraint("evidence_id"),
    )

    # ------------------------------------------------------------------ #
    # concept_relationships                                                #
    # ------------------------------------------------------------------ #
    op.create_table(
        "concept_relationships",
        sa.Column("relationship_id", sa.String(), nullable=False),
        sa.Column("parent_concept_id", sa.String(), nullable=False),
        sa.Column("child_concept_id", sa.String(), nullable=False),
        sa.Column("relationship_type", sa.String(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("source_claim_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["child_concept_id"], ["concepts.concept_id"]),
        sa.ForeignKeyConstraint(["parent_concept_id"], ["concepts.concept_id"]),
        sa.ForeignKeyConstraint(["source_claim_id"], ["claims.claim_id"]),
        sa.PrimaryKeyConstraint("relationship_id"),
    )

    # ------------------------------------------------------------------ #
    # reviewer_keys                                                        #
    # ------------------------------------------------------------------ #
    op.create_table(
        "reviewer_keys",
        sa.Column("key_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=True),
        sa.Column("reviewer_id", sa.String(), nullable=False),
        sa.Column("reviewer_name", sa.String(), nullable=True),
        sa.Column("reviewer_role", sa.String(), nullable=True),
        sa.Column("reviewer_credentials", sa.JSON(), nullable=True),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column("key_fingerprint", sa.String(), nullable=False),
        sa.Column("signature_algorithm", sa.String(), nullable=False, server_default="RSA-SHA256"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("valid_from", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["node_id"], ["academy_nodes.node_id"]),
        sa.PrimaryKeyConstraint("key_id"),
        sa.UniqueConstraint("key_fingerprint"),
    )

    # ------------------------------------------------------------------ #
    # verification_logs                                                    #
    # ------------------------------------------------------------------ #
    op.create_table(
        "verification_logs",
        sa.Column("log_id", sa.String(), nullable=False),
        sa.Column("claim_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=True),
        sa.Column("verification_result", sa.String(), nullable=True),
        sa.Column("reviewer", sa.String(), nullable=True),
        sa.Column("is_ai_review", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("review_status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.claim_id"]),
        sa.ForeignKeyConstraint(["node_id"], ["academy_nodes.node_id"]),
        sa.PrimaryKeyConstraint("log_id"),
    )

    # ------------------------------------------------------------------ #
    # verification_attestations                                            #
    # ------------------------------------------------------------------ #
    op.create_table(
        "verification_attestations",
        sa.Column("attestation_id", sa.String(), nullable=False),
        sa.Column("claim_id", sa.String(), nullable=False),
        sa.Column("log_id", sa.String(), nullable=True),
        sa.Column("reviewer_key_id", sa.String(), nullable=False),
        sa.Column("claim_hash", sa.String(), nullable=False),
        sa.Column("reviewer_signature", sa.Text(), nullable=False),
        sa.Column("signature_algorithm", sa.String(), nullable=False),
        sa.Column("signed_payload", sa.Text(), nullable=True),
        sa.Column("reviewer_id", sa.String(), nullable=True),
        sa.Column("reviewer_role", sa.String(), nullable=True),
        sa.Column("verification_reason", sa.Text(), nullable=True),
        sa.Column("signature_verified", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("verification_timestamp", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.claim_id"]),
        sa.ForeignKeyConstraint(["log_id"], ["verification_logs.log_id"]),
        sa.ForeignKeyConstraint(["reviewer_key_id"], ["reviewer_keys.key_id"]),
        sa.PrimaryKeyConstraint("attestation_id"),
    )

    # ------------------------------------------------------------------ #
    # courses                                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        "courses",
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("origin_node_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("version", sa.String(), nullable=False, server_default="1.0"),
        sa.Column("publishing_state", sa.String(), nullable=False, server_default="DRAFT"),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("superseded_by_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["origin_node_id"], ["academy_nodes.node_id"]),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["courses.course_id"]),
        sa.PrimaryKeyConstraint("course_id"),
    )

    # ------------------------------------------------------------------ #
    # modules                                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        "modules",
        sa.Column("module_id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["course_id"], ["courses.course_id"]),
        sa.PrimaryKeyConstraint("module_id"),
    )

    # ------------------------------------------------------------------ #
    # lessons                                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        "lessons",
        sa.Column("lesson_id", sa.String(), nullable=False),
        sa.Column("module_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("publishing_state", sa.String(), nullable=False, server_default="DRAFT"),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("superseded_by_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["module_id"], ["modules.module_id"]),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["lessons.lesson_id"]),
        sa.PrimaryKeyConstraint("lesson_id"),
    )

    # ------------------------------------------------------------------ #
    # lesson_claims (association)                                          #
    # ------------------------------------------------------------------ #
    op.create_table(
        "lesson_claims",
        sa.Column("lesson_id", sa.String(), nullable=False),
        sa.Column("claim_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.claim_id"]),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.lesson_id"]),
        sa.PrimaryKeyConstraint("lesson_id", "claim_id"),
    )

    # ------------------------------------------------------------------ #
    # quiz_questions                                                       #
    # ------------------------------------------------------------------ #
    op.create_table(
        "quiz_questions",
        sa.Column("question_id", sa.String(), nullable=False),
        sa.Column("lesson_id", sa.String(), nullable=False),
        sa.Column("claim_id", sa.String(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer_options", sa.JSON(), nullable=True),
        sa.Column("correct_answer", sa.String(), nullable=True),
        sa.Column("difficulty", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.claim_id"]),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.lesson_id"]),
        sa.PrimaryKeyConstraint("question_id"),
    )

    # ------------------------------------------------------------------ #
    # competency_mappings                                                  #
    # ------------------------------------------------------------------ #
    op.create_table(
        "competency_mappings",
        sa.Column("mapping_id", sa.String(), nullable=False),
        sa.Column("competency_id", sa.String(), nullable=False),
        sa.Column("claim_id", sa.String(), nullable=True),
        sa.Column("lesson_id", sa.String(), nullable=True),
        sa.Column("course_id", sa.String(), nullable=True),
        sa.Column("concept_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.claim_id"]),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.competency_id"]),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.concept_id"]),
        sa.ForeignKeyConstraint(["course_id"], ["courses.course_id"]),
        sa.ForeignKeyConstraint(["lesson_id"], ["lessons.lesson_id"]),
        sa.PrimaryKeyConstraint("mapping_id"),
    )

    # ------------------------------------------------------------------ #
    # credentials                                                          #
    # ------------------------------------------------------------------ #
    op.create_table(
        "credentials",
        sa.Column("credential_id", sa.String(), nullable=False),
        sa.Column("student_id", sa.String(), nullable=False),
        sa.Column("student_name", sa.String(), nullable=True),
        sa.Column("student_email", sa.String(), nullable=True),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("issuing_node_id", sa.String(), nullable=True),
        sa.Column("issued_by", sa.String(), nullable=True),
        sa.Column("credential_type", sa.String(), nullable=False),
        sa.Column("verification_signature", sa.Text(), nullable=True),
        sa.Column("credential_hash", sa.String(), nullable=True),
        sa.Column("issue_date", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expiry_date", sa.DateTime(), nullable=True),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revocation_reason", sa.String(), nullable=True),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("credential_subject", sa.JSON(), nullable=True),
        sa.Column("proof", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.course_id"]),
        sa.ForeignKeyConstraint(["issuing_node_id"], ["academy_nodes.node_id"]),
        sa.PrimaryKeyConstraint("credential_id"),
    )

    # ------------------------------------------------------------------ #
    # credential_competencies                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        "credential_competencies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("credential_id", sa.String(), nullable=False),
        sa.Column("competency_id", sa.String(), nullable=False),
        sa.Column("mastery_score", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.competency_id"]),
        sa.ForeignKeyConstraint(["credential_id"], ["credentials.credential_id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------ #
    # federated_claim_records                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        "federated_claim_records",
        sa.Column("record_id", sa.String(), nullable=False),
        sa.Column("claim_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("source_node_id", sa.String(), nullable=True),
        sa.Column("target_node_id", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("message_signature", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.claim_id"]),
        sa.PrimaryKeyConstraint("record_id"),
    )

    # ------------------------------------------------------------------ #
    # conflict_flags                                                       #
    # ------------------------------------------------------------------ #
    op.create_table(
        "conflict_flags",
        sa.Column("flag_id", sa.String(), nullable=False),
        sa.Column("claim_a_id", sa.String(), nullable=False),
        sa.Column("claim_b_id", sa.String(), nullable=False),
        sa.Column("conflict_description", sa.Text(), nullable=True),
        sa.Column("resolution_status", sa.String(), nullable=False, server_default="open"),
        sa.Column("resolved_by", sa.String(), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["claim_a_id"], ["claims.claim_id"]),
        sa.ForeignKeyConstraint(["claim_b_id"], ["claims.claim_id"]),
        sa.PrimaryKeyConstraint("flag_id"),
    )

    # ------------------------------------------------------------------ #
    # integrity_reports                                                    #
    # ------------------------------------------------------------------ #
    op.create_table(
        "integrity_reports",
        sa.Column("report_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=True),
        sa.Column("run_by", sa.String(), nullable=False, server_default="integrity_auditor_agent"),
        sa.Column("total_claims_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflicts_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("outdated_claims", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("flagged_for_review", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["node_id"], ["academy_nodes.node_id"]),
        sa.PrimaryKeyConstraint("report_id"),
    )

    # ------------------------------------------------------------------ #
    # audit_reports                                                        #
    # ------------------------------------------------------------------ #
    op.create_table(
        "audit_reports",
        sa.Column("audit_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=True),
        sa.Column("report_type", sa.String(), nullable=False),
        sa.Column("subject_id", sa.String(), nullable=True),
        sa.Column("generated_by", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("findings", sa.JSON(), nullable=True),
        sa.Column("recommendations", sa.JSON(), nullable=True),
        sa.Column("is_exportable", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("export_format", sa.String(), nullable=False, server_default="json"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["node_id"], ["academy_nodes.node_id"]),
        sa.PrimaryKeyConstraint("audit_id"),
    )

    # ------------------------------------------------------------------ #
    # agent_runs                                                           #
    # ------------------------------------------------------------------ #
    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=True),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="QUEUED"),
        sa.Column("input_payload", sa.JSON(), nullable=True),
        sa.Column("output_summary", sa.JSON(), nullable=True),
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("prompt_type", sa.String(), nullable=True),
        sa.Column("input_source_ids", sa.JSON(), nullable=True),
        sa.Column("output_hash", sa.String(), nullable=True),
        sa.Column("requires_review", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["node_id"], ["academy_nodes.node_id"]),
        sa.PrimaryKeyConstraint("run_id"),
    )

    # ------------------------------------------------------------------ #
    # Indexes for performance                                              #
    # ------------------------------------------------------------------ #
    op.create_index("ix_claims_status", "claims", ["status"])
    op.create_index("ix_claims_origin_node", "claims", ["origin_node_id"])
    op.create_index("ix_claims_claim_category", "claims", ["claim_category"])
    op.create_index("ix_sources_trust_tier", "sources", ["trust_tier"])
    op.create_index("ix_federated_claim_records_action", "federated_claim_records", ["action"])
    op.create_index("ix_federated_claim_records_source_node", "federated_claim_records", ["source_node_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_index("ix_agent_runs_agent_name", "agent_runs", ["agent_name"])


def downgrade() -> None:
    # Drop in reverse dependency order
    op.drop_table("agent_runs")
    op.drop_table("audit_reports")
    op.drop_table("integrity_reports")
    op.drop_table("conflict_flags")
    op.drop_table("federated_claim_records")
    op.drop_table("credential_competencies")
    op.drop_table("credentials")
    op.drop_table("competency_mappings")
    op.drop_table("quiz_questions")
    op.drop_table("lesson_claims")
    op.drop_table("lessons")
    op.drop_table("modules")
    op.drop_table("courses")
    op.drop_table("verification_attestations")
    op.drop_table("verification_logs")
    op.drop_table("reviewer_keys")
    op.drop_table("concept_relationships")
    op.drop_table("claim_evidence")
    op.drop_table("claim_revisions")
    op.drop_table("claims")
    op.drop_table("competencies")
    op.drop_table("standards")
    op.drop_table("concepts")
    op.drop_table("extracted_texts")
    op.drop_table("sources")
    op.drop_table("node_governance_policies")
    op.drop_table("academy_nodes")
