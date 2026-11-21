"""Register human-confirmed reservation payments without a media attachment."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20261121_0041"
down_revision = "20261120_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reservation_manual_payment",
        sa.Column("payment_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reservation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("reservation.reservation_id"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agent.id"), nullable=False),
        sa.Column("recorded_by", sa.String(128), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("amount_cop", sa.Integer(), nullable=False),
        sa.Column("paid_before_cop", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(255)),
        sa.Column("result", sa.String(24), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "amount_cop > 0 AND paid_before_cop >= 0", name="ck_manual_payment_amount"
        ),
        sa.CheckConstraint(
            "method IN ('CASH','CARD','BANK_TRANSFER','NEQUI','DAVIPLATA','PAYMENT_LINK')",
            name="ck_manual_payment_method",
        ),
    )
    op.create_index(
        "ix_manual_payment_reservation", "reservation_manual_payment", ["reservation_id"]
    )


def downgrade() -> None:
    op.drop_table("reservation_manual_payment")
