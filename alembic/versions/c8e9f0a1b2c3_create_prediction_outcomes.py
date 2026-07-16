"""create prediction_outcomes table

Revision ID: c8e9f0a1b2c3
Revises: b7d8e9f0a1b2
Create Date: 2026-07-14

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "c8e9f0a1b2c3"
down_revision: Union[str, None] = "b7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prediction_outcomes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("predicted_at", sa.Date(), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("close_at_prediction", sa.Float(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("actual_close_at_target", sa.Float(), nullable=True),
        sa.Column("actual_return_pct", sa.Float(), nullable=True),
        sa.Column("was_correct", sa.Boolean(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "predicted_at", name="uq_prediction_ticker_date"),
    )
    op.create_index(op.f("ix_prediction_outcomes_id"), "prediction_outcomes", ["id"], unique=False)
    op.create_index(op.f("ix_prediction_outcomes_ticker"), "prediction_outcomes", ["ticker"], unique=False)
    op.create_index(op.f("ix_prediction_outcomes_predicted_at"), "prediction_outcomes", ["predicted_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_prediction_outcomes_predicted_at"), table_name="prediction_outcomes")
    op.drop_index(op.f("ix_prediction_outcomes_ticker"), table_name="prediction_outcomes")
    op.drop_index(op.f("ix_prediction_outcomes_id"), table_name="prediction_outcomes")
    op.drop_table("prediction_outcomes")
