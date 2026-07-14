"""create portfolio_snapshots table

Revision ID: b7d8e9f0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-14

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


revision: str = "b7d8e9f0a1b2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("cash_balance", sa.Float(), nullable=False),
        sa.Column("positions_market_value", sa.Float(), nullable=False),
        sa.Column("total_value", sa.Float(), nullable=False),
        sa.Column("total_return_usd", sa.Float(), nullable=False),
        sa.Column("total_return_pct", sa.Float(), nullable=False),
        sa.Column("open_positions_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "portfolio_id", "snapshot_date", name="uq_portfolio_snapshot_date"
        ),
    )
    op.create_index(
        op.f("ix_portfolio_snapshots_id"), "portfolio_snapshots", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_portfolio_snapshots_portfolio_id"),
        "portfolio_snapshots",
        ["portfolio_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_portfolio_snapshots_snapshot_date"),
        "portfolio_snapshots",
        ["snapshot_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_portfolio_snapshots_snapshot_date"), table_name="portfolio_snapshots"
    )
    op.drop_index(
        op.f("ix_portfolio_snapshots_portfolio_id"), table_name="portfolio_snapshots"
    )
    op.drop_index(op.f("ix_portfolio_snapshots_id"), table_name="portfolio_snapshots")
    op.drop_table("portfolio_snapshots")
