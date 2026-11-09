"""Add CAPA action review and verification details."""
import sqlalchemy as sa

from alembic import op

revision = "0003_capa_details"
down_revision = "0002_ai_analysis"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("capa_actions", sa.Column("related_root_cause", sa.Text(), nullable=False, server_default=""))
    op.add_column("capa_actions", sa.Column("verification_method", sa.Text(), nullable=False, server_default=""))
    op.add_column("capa_actions", sa.Column("effectiveness_criteria", sa.Text(), nullable=False, server_default=""))
    op.add_column("capa_actions", sa.Column("expected_outcome", sa.Text(), nullable=False, server_default=""))
    op.add_column("capa_actions", sa.Column("supporting_evidence", sa.JSON(), nullable=False, server_default="[]"))
    op.alter_column("capa_actions", "status", server_default="Proposed")

def downgrade() -> None:
    op.drop_column("capa_actions", "supporting_evidence")
    op.drop_column("capa_actions", "expected_outcome")
    op.drop_column("capa_actions", "effectiveness_criteria")
    op.drop_column("capa_actions", "verification_method")
    op.drop_column("capa_actions", "related_root_cause")
