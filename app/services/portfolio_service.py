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
from app.models.prediction import PredictionOutcome
from app.models.stock import StockOHLCV

DEFAULT_PORTFOLIO_NAME = "main"
DEFAULT_INITIAL_CAPITAL = 10_000.0

# Guardrails on user-configurable capital
MIN_INITIAL_CAPITAL = 100.0
MAX_INITIAL_CAPITAL = 100_000.0


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


def reset_portfolio(
    db: Session,
    name: str = DEFAULT_PORTFOLIO_NAME,
    initial_capital: float | None = None,
) -> Portfolio:
    """Wipe positions/trades/snapshots and reset cash.

    If `initial_capital` is provided, the portfolio is re-initialized at that
    amount (clamped to [MIN, MAX]). Otherwise the existing initial_capital is
    kept.
    """
    if initial_capital is not None:
        initial_capital = max(
            MIN_INITIAL_CAPITAL, min(MAX_INITIAL_CAPITAL, float(initial_capital))
        )

    p = db.query(Portfolio).filter(Portfolio.name == name).first()
    if p:
        from app.models.portfolio import PortfolioSnapshot
        db.query(Trade).filter(Trade.portfolio_id == p.id).delete()
        db.query(Position).filter(Position.portfolio_id == p.id).delete()
        db.query(PortfolioSnapshot).filter(PortfolioSnapshot.portfolio_id == p.id).delete()
        if initial_capital is not None:
            p.initial_capital = initial_capital
        p.cash_balance = p.initial_capital
        db.commit()
        db.refresh(p)
        return p

    # Portfolio didn't exist — create with requested or default capital
    capital = initial_capital if initial_capital is not None else DEFAULT_INITIAL_CAPITAL
    p = Portfolio(name=name, initial_capital=capital, cash_balance=capital)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


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


def _fresh_prediction_for(db: Session, ticker: str) -> dict | None:
    """Best-effort: today's model prediction for a ticker, or None if unavailable.

    Failure to load a model / predict is silent — enriched position display
    should degrade to just the historical fields when predictions can't be
    generated for that ticker.
    """
    try:
        from app.ml.predict import predict_next_day  # local import to avoid cycles
        return predict_next_day(ticker, db)
    except Exception:  # noqa: BLE001
        return None


def _rewards_earned_for(db: Session, ticker: str, since) -> int:
    """Sum of reward points from PredictionOutcome for this ticker since `since`.

    10 points per correct hit + 5 bonus if the correct hit had confidence >= 70%.
    Returns 0 on any query failure so unknown-ticker positions still render.
    """
    try:
        rows = (
            db.query(PredictionOutcome)
            .filter(
                PredictionOutcome.ticker == ticker.upper(),
                PredictionOutcome.was_correct.is_(True),
                PredictionOutcome.predicted_at >= since,
            )
            .all()
        )
    except Exception:  # noqa: BLE001
        db.rollback()
        return 0
    return sum(10 + (5 if o.confidence >= 0.70 else 0) for o in rows)


def build_summary(db: Session, portfolio: Portfolio) -> dict:
    """Mark-to-market portfolio value.

    total_value = cash + sum(LONG_market_value) - sum(SHORT_liability)

    For LONGs the equity contribution is +shares × current_price (what selling
    would yield). For SHORTs the contribution is -shares × current_price (the
    cost to buy back and close). Cash already reflects the proceeds/cost from
    opening the position, so the mark-to-market delta on the position offsets
    against cash to give the correct running total.

    Each position is enriched with:
      - `predicted_price_tomorrow` — model's 1-day-ish projection
      - `expected_gain_tomorrow_usd` — signed dollar move if prediction hits
      - `rewards_earned` — points accumulated from correct predictions since open
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

        # Enrich with today's fresh model view + accumulated rewards
        pred = _fresh_prediction_for(db, pos.ticker)
        predicted_price_tomorrow: float | None = None
        expected_gain_tomorrow_usd: float | None = None
        if pred is not None:
            # 1-day estimate ≈ (confidence edge × 3% baseline) / sqrt(5)
            conf_edge = (float(pred["confidence"]) - 0.5) * 2
            signed_edge = conf_edge if pred["direction"] == "UP" else -conf_edge
            one_day_move_pct = signed_edge * 3.0 / (5 ** 0.5)
            base_price = current if current is not None else pos.avg_entry_price
            predicted_price_tomorrow = round(base_price * (1 + one_day_move_pct / 100), 2)
            if current is not None:
                move = predicted_price_tomorrow - current
                if pos.side == "SHORT":
                    move = -move
                expected_gain_tomorrow_usd = round(move * pos.shares, 2)

        rewards_earned = _rewards_earned_for(db, pos.ticker, pos.opened_at.date() if hasattr(pos.opened_at, "date") else pos.opened_at)

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
                "predicted_price_tomorrow": predicted_price_tomorrow,
                "expected_gain_tomorrow_usd": expected_gain_tomorrow_usd,
                "rewards_earned": rewards_earned,
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


def enforce_stops(db: Session, portfolio: Portfolio) -> list[dict]:
    """Scan open positions and close any where price crossed stop_loss or take_profit.

    LONG:
        current <= stop_loss   → SELL (loss capped)
        current >= take_profit → SELL (profit taken)
    SHORT:
        current >= stop_loss   → COVER (loss capped)
        current <= take_profit → COVER (profit taken)

    Returns list of action dicts describing each enforcement event. Positions
    without both stop_loss and take_profit set are skipped (no reference for
    enforcement).
    """
    actions: list[dict] = []

    # Materialize positions list because we may delete during iteration
    positions_snapshot = list(portfolio.positions)

    for pos in positions_snapshot:
        current = _latest_close(db, pos.ticker)
        if current is None:
            continue

        trigger: str | None = None  # "stop_loss" | "take_profit"
        action: str | None = None

        if pos.side == "LONG":
            if pos.stop_loss is not None and current <= pos.stop_loss:
                trigger, action = "stop_loss", "SELL"
            elif pos.take_profit is not None and current >= pos.take_profit:
                trigger, action = "take_profit", "SELL"
        elif pos.side == "SHORT":
            if pos.stop_loss is not None and current >= pos.stop_loss:
                trigger, action = "stop_loss", "COVER"
            elif pos.take_profit is not None and current <= pos.take_profit:
                trigger, action = "take_profit", "COVER"

        if trigger is None:
            continue

        try:
            trade = execute_trade(
                db,
                portfolio_id=portfolio.id,
                ticker=pos.ticker,
                action=action,
                shares=pos.shares,
                price=current,
                source=trigger,
            )
            actions.append(
                {
                    "ticker": pos.ticker,
                    "side_closed": pos.side,
                    "action": action,
                    "trigger": trigger,
                    "shares": trade.shares,
                    "price": trade.price,
                    "realized_pnl": trade.realized_pnl,
                }
            )
        except PortfolioError as exc:
            actions.append(
                {
                    "ticker": pos.ticker,
                    "side_closed": pos.side,
                    "action": action,
                    "trigger": trigger,
                    "error": str(exc),
                }
            )

    return actions


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
