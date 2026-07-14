from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)
    initial_capital = Column(Float, nullable=False)
    cash_balance = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    positions = relationship("Position", back_populates="portfolio", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="portfolio", cascade="all, delete-orphan")
    snapshots = relationship(
        "PortfolioSnapshot", back_populates="portfolio", cascade="all, delete-orphan"
    )


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    side = Column(String(5), nullable=False)  # "LONG" | "SHORT"
    shares = Column(Integer, nullable=False)
    avg_entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    opened_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    portfolio = relationship("Portfolio", back_populates="positions")

    __table_args__ = (
        UniqueConstraint("portfolio_id", "ticker", "side", name="uq_portfolio_ticker_side"),
    )


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    action = Column(String(6), nullable=False)  # BUY | SELL | SHORT | COVER
    shares = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    notional = Column(Float, nullable=False)
    realized_pnl = Column(Float, nullable=True)  # populated on SELL / COVER
    source = Column(String(32), nullable=False, default="manual")  # manual|agent|stop|take
    executed_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, index=True)

    portfolio = relationship("Portfolio", back_populates="trades")


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id"), nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    cash_balance = Column(Float, nullable=False)
    positions_market_value = Column(Float, nullable=False)
    total_value = Column(Float, nullable=False)
    total_return_usd = Column(Float, nullable=False)
    total_return_pct = Column(Float, nullable=False)
    open_positions_count = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    portfolio = relationship("Portfolio", back_populates="snapshots")

    __table_args__ = (
        UniqueConstraint(
            "portfolio_id", "snapshot_date", name="uq_portfolio_snapshot_date"
        ),
    )
