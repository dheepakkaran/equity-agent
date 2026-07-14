"""Paper trading business logic.

Semantics:
- BUY: open or add to a LONG position. Weighted-avg entry. Cash decreases.
- SELL: close (partial or full) LONG. Cash increases. Realized P&L booked.
- SHORT: open or add to SHORT. Proceeds credit cash.
- COVER: close (partial or full) SHORT. Cash decreases (buy back). Realized P&L booked.

Cross-side flips (e.g. BUY when SHORT is open) are rejected — user must
COVER first, then BUY. Simpler than auto-flipping.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.portfolio import Portfolio, PortfolioSnapshot, Position, Trade
from app.models.stock import StockOHLCV

DEFAULT_PORTFOLIO_NAME = "main"
DEFAULT_INITIAL_CAPITAL = 1_000_000.0


class PortfolioError(Exception):
    """Raised when a trade violates portfolio rules (insufficient cash / shares / flip)."""


def get_or_create_portfolio(db: Session, name: str = DEFAULT_PORTFOLIO_NAME) -> Portfolio:
    p = db.query(Portfolio).filter(Portfolio.name == name).first()
    if p:
        return p
    p = Portfolio(
        name=name,
        initial_capital=DEFAULT_INITIAL_CAPITAL,
        cash_balance=DEFAULT_INITIAL_CAPITAL,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def reset_portfolio(db: Session, name: str = DEFAULT_PORTFOLIO_NAME) -> Portfolio:
    """Wipe positions/trades and reset cash to initial capital."""
    p = db.query(Portfolio).filter(Portfolio.name == name).first()
    if p:
        db.query(Trade).filter(Trade.portfolio_id == p.id).delete()
        db.query(Position).filter(Position.portfolio_id == p.id).delete()
        p.cash_balance = p.initial_capital
        db.commit()
        db.refresh(p)
        return p
    return get_or_create_portfolio(db, name)


def _latest_close(db: Session, ticker: str) -> float | None:
    row = (
        db.query(StockOHLCV)
        .filter(StockOHLCV.ticker == ticker.upper())
        .order_by(StockOHLCV.date.desc())
        .first()
    )
    return float(row.close) if row else None


def _get_position(db: Session, portfolio_id: int, ticker: str, side: str) -> Position | None:
    return (
        db.query(Position)
        .filter(
            Position.portfolio_id == portfolio_id,
            Position.ticker == ticker.upper(),
            Position.side == side,
        )
        .first()
    )


def _opposite_side(action: str) -> str | None:
    return {"BUY": "SHORT", "SHORT": "LONG"}.get(action)


def execute_trade(
    db: Session,
    portfolio_id: int,
    ticker: str,
    action: str,
    shares: int,
    price: float,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    source: str = "manual",
) -> Trade:
    """Execute a trade against a portfolio. Persists Trade + updates Position + cash."""
    if action not in {"BUY", "SELL", "SHORT", "COVER"}:
        raise PortfolioError(f"Unknown action: {action}")
    if shares <= 0:
        raise PortfolioError("shares must be > 0")
    if price <= 0:
        raise PortfolioError("price must be > 0")

    ticker = ticker.upper()
    portfolio = db.query(Portfolio).filter(Portfolio.id == portfolio_id).first()
    if not portfolio:
        raise PortfolioError(f"Portfolio {portfolio_id} not found")

    notional = shares * price

    # Reject cross-side flips
    opp = _opposite_side(action)
    if opp:
        conflicting = _get_position(db, portfolio_id, ticker, opp)
        if conflicting:
            raise PortfolioError(
                f"Cannot {action} {ticker} — existing {opp} position of {conflicting.shares} shares. "
                f"Close it first ({'COVER' if opp == 'SHORT' else 'SELL'})."
            )

    realized_pnl: float | None = None

    if action == "BUY":
        if portfolio.cash_balance < notional:
            raise PortfolioError(
                f"Insufficient cash: need ${notional:.2f}, have ${portfolio.cash_balance:.2f}"
            )
        portfolio.cash_balance -= notional
        pos = _get_position(db, portfolio_id, ticker, "LONG")
        if pos:
            total_cost = pos.avg_entry_price * pos.shares + notional
            pos.shares += shares
            pos.avg_entry_price = total_cost / pos.shares
            if stop_loss is not None:
                pos.stop_loss = stop_loss
            if take_profit is not None:
                pos.take_profit = take_profit
        else:
            pos = Position(
                portfolio_id=portfolio_id,
                ticker=ticker,
                side="LONG",
                shares=shares,
                avg_entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
            db.add(pos)

    elif action == "SELL":
        pos = _get_position(db, portfolio_id, ticker, "LONG")
        if not pos or pos.shares < shares:
            have = pos.shares if pos else 0
            raise PortfolioError(f"Cannot SELL {shares} — only hold {have} LONG shares of {ticker}")
        realized_pnl = (price - pos.avg_entry_price) * shares
        portfolio.cash_balance += notional
        pos.shares -= shares
        if pos.shares == 0:
            db.delete(pos)

    elif action == "SHORT":
        portfolio.cash_balance += notional  # proceeds credited
        pos = _get_position(db, portfolio_id, ticker, "SHORT")
        if pos:
            total_cost = pos.avg_entry_price * pos.shares + notional
            pos.shares += shares
            pos.avg_entry_price = total_cost / pos.shares
            if stop_loss is not None:
                pos.stop_loss = stop_loss
            if take_profit is not None:
                pos.take_profit = take_profit
        else:
            pos = Position(
                portfolio_id=portfolio_id,
                ticker=ticker,
                side="SHORT",
                shares=shares,
                avg_entry_price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
            db.add(pos)

    elif action == "COVER":
        pos = _get_position(db, portfolio_id, ticker, "SHORT")
        if not pos or pos.shares < shares:
            have = pos.shares if pos else 0
            raise PortfolioError(f"Cannot COVER {shares} — only hold {have} SHORT shares of {ticker}")
        if portfolio.cash_balance < notional:
            raise PortfolioError(
                f"Insufficient cash to COVER: need ${notional:.2f}, have ${portfolio.cash_balance:.2f}"
            )
        realized_pnl = (pos.avg_entry_price - price) * shares
        portfolio.cash_balance -= notional
        pos.shares -= shares
        if pos.shares == 0:
            db.delete(pos)

    trade = Trade(
        portfolio_id=portfolio_id,
        ticker=ticker,
        action=action,
        shares=shares,
        price=price,
        notional=notional,
        realized_pnl=realized_pnl,
        source=source,
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def build_summary(db: Session, portfolio: Portfolio) -> dict:
    """Mark-to-market portfolio value.

    total_value = cash + sum(LONG_market_value) - sum(SHORT_liability)

    For LONGs the equity contribution is +shares × current_price (what selling
    would yield). For SHORTs the contribution is -shares × current_price (the
    cost to buy back and close). Cash already reflects the proceeds/cost from
    opening the position, so the mark-to-market delta on the position offsets
    against cash to give the correct running total.
    """
    positions_out = []
    net_position_value = 0.0
    for pos in portfolio.positions:
        current = _latest_close(db, pos.ticker)
        if current is None:
            market_value = None
            unrealized = None
            unrealized_pct = None
        else:
            if pos.side == "LONG":
                unrealized = (current - pos.avg_entry_price) * pos.shares
                market_value = current * pos.shares
                net_position_value += market_value
            else:  # SHORT
                unrealized = (pos.avg_entry_price - current) * pos.shares
                market_value = current * pos.shares  # buy-back cost (liability)
                net_position_value -= market_value
            unrealized_pct = (
                (unrealized / (pos.avg_entry_price * pos.shares)) * 100 if pos.shares > 0 else 0.0
            )

        positions_out.append(
            {
                "id": pos.id,
                "ticker": pos.ticker,
                "side": pos.side,
                "shares": pos.shares,
                "avg_entry_price": pos.avg_entry_price,
                "stop_loss": pos.stop_loss,
                "take_profit": pos.take_profit,
                "current_price": current,
                "market_value": market_value,
                "unrealized_pnl": unrealized,
                "unrealized_pnl_pct": unrealized_pct,
                "opened_at": pos.opened_at,
            }
        )

    total_value = portfolio.cash_balance + net_position_value
    total_return_usd = total_value - portfolio.initial_capital
    total_return_pct = (total_return_usd / portfolio.initial_capital) * 100

    return {
        "id": portfolio.id,
        "name": portfolio.name,
        "initial_capital": portfolio.initial_capital,
        "cash_balance": portfolio.cash_balance,
        "positions_market_value": net_position_value,
        "total_value": total_value,
        "total_return_usd": total_return_usd,
        "total_return_pct": total_return_pct,
        "positions": positions_out,
    }


def take_snapshot(db: Session, portfolio: Portfolio, on_date: date | None = None) -> PortfolioSnapshot:
    """Capture current portfolio state as a daily snapshot.

    Idempotent per (portfolio_id, snapshot_date): calling twice on the same
    day updates the existing row instead of inserting a duplicate.
    """
    if on_date is None:
        on_date = datetime.now(timezone.utc).date()

    summary = build_summary(db, portfolio)

    existing = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.portfolio_id == portfolio.id,
            PortfolioSnapshot.snapshot_date == on_date,
        )
        .first()
    )

    if existing:
        existing.cash_balance = summary["cash_balance"]
        existing.positions_market_value = summary["positions_market_value"]
        existing.total_value = summary["total_value"]
        existing.total_return_usd = summary["total_return_usd"]
        existing.total_return_pct = summary["total_return_pct"]
        existing.open_positions_count = len(summary["positions"])
        snapshot = existing
    else:
        snapshot = PortfolioSnapshot(
            portfolio_id=portfolio.id,
            snapshot_date=on_date,
            cash_balance=summary["cash_balance"],
            positions_market_value=summary["positions_market_value"],
            total_value=summary["total_value"],
            total_return_usd=summary["total_return_usd"],
            total_return_pct=summary["total_return_pct"],
            open_positions_count=len(summary["positions"]),
        )
        db.add(snapshot)

    db.commit()
    db.refresh(snapshot)
    return snapshot


def get_history(
    db: Session, portfolio_id: int, days: int = 30
) -> list[PortfolioSnapshot]:
    """Return snapshots from the last `days` days, oldest first (for chart display)."""
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    return (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.portfolio_id == portfolio_id,
            PortfolioSnapshot.snapshot_date >= cutoff,
        )
        .order_by(PortfolioSnapshot.snapshot_date.asc())
        .all()
    )
