from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


TradeAction = Literal["BUY", "SELL", "SHORT", "COVER"]
PositionSide = Literal["LONG", "SHORT"]


class TradeRequest(BaseModel):
    ticker: str
    action: TradeAction
    shares: int = Field(..., gt=0)
    stop_loss: float | None = None
    take_profit: float | None = None


class ResetRequest(BaseModel):
    initial_capital: float | None = Field(
        None, ge=100, le=100_000,
        description="Optional new starting capital between $100 and $100k. If omitted, keeps existing initial_capital.",
    )


class TradeOut(BaseModel):
    id: int
    ticker: str
    action: str
    shares: int
    price: float
    notional: float
    realized_pnl: float | None
    source: str
    executed_at: datetime

    class Config:
        from_attributes = True


class PositionOut(BaseModel):
    id: int
    ticker: str
    side: str
    shares: int
    avg_entry_price: float
    stop_loss: float | None
    take_profit: float | None
    current_price: float | None
    market_value: float | None
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    predicted_price_tomorrow: float | None = None
    expected_gain_tomorrow_usd: float | None = None
    rewards_earned: int = 0
    opened_at: datetime


class PortfolioSummary(BaseModel):
    id: int
    name: str
    initial_capital: float
    cash_balance: float
    positions_market_value: float
    total_value: float
    total_return_usd: float
    total_return_pct: float
    positions: list[PositionOut]


class ExecutionResult(BaseModel):
    executed: bool
    reason: str
    trade: TradeOut | None = None
    recommendation_direction: str | None = None
    portfolio_after: PortfolioSummary | None = None


class SnapshotOut(BaseModel):
    id: int
    snapshot_date: date
    cash_balance: float
    positions_market_value: float
    total_value: float
    total_return_usd: float
    total_return_pct: float
    open_positions_count: int

    class Config:
        from_attributes = True


class HistoryResponse(BaseModel):
    portfolio_id: int
    days: int
    count: int
    snapshots: list[SnapshotOut]
    first_value: float | None = None
    last_value: float | None = None
    period_return_usd: float | None = None
    period_return_pct: float | None = None


class EnforcementAction(BaseModel):
    ticker: str
    side_closed: str
    action: str
    trigger: str
    shares: int | None = None
    price: float | None = None
    realized_pnl: float | None = None
    error: str | None = None


class EnforcementResult(BaseModel):
    triggered: int
    actions: list[EnforcementAction]
    portfolio_after: PortfolioSummary
