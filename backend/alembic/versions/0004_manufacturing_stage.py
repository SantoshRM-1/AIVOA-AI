"""Add manufacturing stage to investigations."""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0004_manufacturing_stage"
down_revision = "0003_capa_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("investigations")}
    if "manufacturing_stage" not in columns:
        op.add_column(
            "investigations",
            sa.Column("manufacturing_stage", sa.String(160), nullable=False, server_default=""),
        )


def downgrade() -> None:
    columns = {column["name"] for column in inspect(op.get_bind()).get_columns("investigations")}
    if "manufacturing_stage" in columns:
        op.drop_column("investigations", "manufacturing_stage")
