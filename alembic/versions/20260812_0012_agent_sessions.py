"""agent role credentials and sessions

Revision ID: 20260812_0012
Revises: 20260812_0011
Create Date: 2026-08-12 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260812_0012"
down_revision: str | None = "20260812_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("document_id", sa.String(length=64), nullable=True))
    op.add_column("agent", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "agent",
        sa.Column("role", sa.String(length=16), server_default="AGENT", nullable=False),
    )
    op.create_unique_constraint(op.f("uq_agent_document_id"), "agent", ["document_id"])
    op.create_check_constraint("ck_agent_role", "agent", "role IN ('ADMIN', 'AGENT')")
    op.drop_constraint("agent_token_hash_key", "agent", type_="unique")
    op.drop_column("agent", "token_hash")
    op.alter_column("agent", "role", server_default=None)

    op.create_table(
        "agent_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_agent_session_agent_id", "agent_session", ["agent_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_session_agent_id", table_name="agent_session")
    op.drop_table("agent_session")
    op.add_column("agent", sa.Column("token_hash", sa.String(length=64), nullable=True))
    op.execute("UPDATE agent SET token_hash = lpad(id::text, 64, '0')")
    op.alter_column("agent", "token_hash", nullable=False)
    op.create_unique_constraint("agent_token_hash_key", "agent", ["token_hash"])
    op.drop_constraint("ck_agent_role", "agent", type_="check")
    op.drop_constraint(op.f("uq_agent_document_id"), "agent", type_="unique")
    op.drop_column("agent", "role")
    op.drop_column("agent", "password_hash")
    op.drop_column("agent", "document_id")
