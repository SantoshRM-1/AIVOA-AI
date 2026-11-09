"""Add source extraction and stored PDF content for AI-assisted investigations."""

import sqlalchemy as sa

from alembic import op

revision = "0002_ai_analysis"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "investigations",
        sa.Column("deviation_category", sa.String(160), nullable=False, server_default=""),
    )
    op.add_column(
        "investigations",
        sa.Column("equipment_involved", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column("investigation_evidence", sa.Column("file_name", sa.String(255), nullable=True))
    op.add_column("investigation_evidence", sa.Column("mime_type", sa.String(100), nullable=True))
    op.add_column(
        "investigation_evidence", sa.Column("file_content", sa.LargeBinary(), nullable=True)
    )
    op.add_column(
        "root_cause_analyses",
        sa.Column("extraction_data", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("root_cause_analyses", "extraction_data")
    op.drop_column("investigation_evidence", "file_content")
    op.drop_column("investigation_evidence", "mime_type")
    op.drop_column("investigation_evidence", "file_name")
    op.drop_column("investigations", "equipment_involved")
    op.drop_column("investigations", "deviation_category")
