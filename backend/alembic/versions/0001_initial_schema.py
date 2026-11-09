"""Create initial investigation, evidence, RCA and CAPA tables."""

import sqlalchemy as sa

from alembic import op

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "investigations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deviation_id", sa.String(100), nullable=False, unique=True),
        sa.Column("incident_title", sa.String(255), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("batch_number", sa.String(120), nullable=False, server_default=""),
        sa.Column("department", sa.String(120), nullable=False, server_default=""),
        sa.Column("manufacturing_stage", sa.String(160), nullable=False, server_default=""),
        sa.Column("incident_date", sa.Date(), nullable=True),
        sa.Column("expected_condition", sa.Text(), nullable=False, server_default=""),
        sa.Column("actual_condition", sa.Text(), nullable=False, server_default=""),
        sa.Column("incident_description", sa.Text(), nullable=False, server_default=""),
        sa.Column("immediate_actions", sa.Text(), nullable=False, server_default=""),
        sa.Column("potential_quality_impact", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(40), nullable=False, server_default="Open"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "investigation_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.Integer(),
            sa.ForeignKey("investigations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_reference", sa.String(500), nullable=True),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "root_cause_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.Integer(),
            sa.ForeignKey("investigations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("five_whys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("fishbone", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("suggestions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "capa_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "investigation_id",
            sa.Integer(),
            sa.ForeignKey("investigations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("action_type", sa.String(30), nullable=False),
        sa.Column("action_description", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("responsible_person", sa.String(160), nullable=False, server_default=""),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="Open"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("capa_actions")
    op.drop_table("root_cause_analyses")
    op.drop_table("investigation_evidence")
    op.drop_table("investigations")
