from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agents.coordinator import run_analysis
from app.database import get_db
from app.models.portfolio import Trade
from app.services.scan_service import scan_universe
from app.schemas.portfolio import (
    EnforcementAction,
    EnforcementResult,
    ExecutionResult,
    HistoryResponse,
    PortfolioSummary,
    ResetRequest,
    SnapshotOut,
    TradeOut,
    TradeRequest,
)
from app.services.portfolio_service import (
    PortfolioError,
    build_summary,
    enforce_stops,
    execute_trade,
    get_history,
    get_or_create_portfolio,
    reset_portfolio,
    take_snapshot,
)
from app.services.prediction_tracking import accuracy_summary

router = APIRouter()


@router.get("", response_model=PortfolioSummary)
async def get_portfolio(db: Session = Depends(get_db)):
    """Get current portfolio state: cash, open positions with unrealized P&L, total return."""
    portfolio = get_or_create_portfolio(db)
    return PortfolioSummary(**build_summary(db, portfolio))


@router.post("/reset", response_model=PortfolioSummary)
async def reset(payload: ResetRequest | None = None, db: Session = Depends(get_db)):
    """Wipe all positions + trades + snapshots. Optionally set a new initial capital.

    Body (optional): `{"initial_capital": 500}` — new starting cash in $100–$100k range.
    """
    initial_capital = payload.initial_capital if payload else None
    portfolio = reset_portfolio(db, initial_capital=initial_capital)
    return PortfolioSummary(**build_summary(db, portfolio))


@router.post("/trade", response_model=TradeOut)
async def manual_trade(payload: TradeRequest, db: Session = Depends(get_db)):
    """Execute a manual trade at the latest close price stored for the ticker.

    Actions: BUY / SELL / SHORT / COVER.
    """
    portfolio = get_or_create_portfolio(db)

    from app.services.portfolio_service import _latest_close
    price = _latest_close(db, payload.ticker)
    if price is None:
        raise HTTPException(
            status_code=404,
            detail=f"No price data for {payload.ticker.upper()}. Fetch via /stocks/{payload.ticker.upper()} first.",
        )

    try:
        trade = execute_trade(
            db,
            portfolio_id=portfolio.id,
            ticker=payload.ticker,
            action=payload.action,
            shares=payload.shares,
            price=price,
            stop_loss=payload.stop_loss,
            take_profit=payload.take_profit,
            source="manual",
        )
    except PortfolioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return TradeOut.model_validate(trade)


@router.post("/execute/{ticker}", response_model=ExecutionResult)
async def execute_recommendation(ticker: str, db: Session = Depends(get_db)):
    """Run the multi-agent /analyze pipeline, then execute the resulting trade plan.

    Rules:
    - Prediction UP + not-already-LONG → BUY suggested_shares
    - Prediction DOWN + not-already-SHORT → SHORT suggested_shares
    - suggested_shares == 0 → skip (confidence too low)
    - Already have same-side position → skip (avoid pyramiding for now)
    """
    portfolio = get_or_create_portfolio(db)
    state = run_analysis(ticker, db)

    prediction = state.get("prediction") or {}
    direction = prediction.get("direction")
    risk = state.get("risk_assessment") or {}
    shares = int(risk.get("suggested_shares") or 0)
    close = state.get("close")

    if not direction or direction == "UNKNOWN":
        return ExecutionResult(
            executed=False,
            reason="No ML direction signal (model not trained for this ticker).",
            recommendation_direction=direction,
        )
    if shares <= 0:
        # Prefer risk agent's contextual reason (unaffordable / low confidence)
        skip = risk.get("skip_reason") or "Risk agent suggested 0 shares."
        return ExecutionResult(
            executed=False,
            reason=skip,
            recommendation_direction=direction,
        )
    if close is None:
        raise HTTPException(status_code=500, detail="Analysis produced no close price.")

    if direction == "UP":
        action = "BUY"
        conflict_side = "LONG"
    else:
        action = "SHORT"
        conflict_side = "SHORT"

    from app.services.portfolio_service import _get_position

    existing = _get_position(db, portfolio.id, ticker, conflict_side)
    if existing:
        return ExecutionResult(
            executed=False,
            reason=f"Already have open {conflict_side} position in {ticker.upper()} ({existing.shares} shares). Skipping to avoid pyramiding.",
            recommendation_direction=direction,
        )

    try:
        trade = execute_trade(
            db,
            portfolio_id=portfolio.id,
            ticker=ticker,
            action=action,
            shares=shares,
            price=close,
            stop_loss=risk.get("stop_loss"),
            take_profit=risk.get("take_profit"),
            source="agent_recommendation",
        )
    except PortfolioError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.refresh(portfolio)
    return ExecutionResult(
        executed=True,
        reason=f"Executed {action} {shares} {ticker.upper()} @ {close:.2f} per agent recommendation.",
        trade=TradeOut.model_validate(trade),
        recommendation_direction=direction,
        portfolio_after=PortfolioSummary(**build_summary(db, portfolio)),
    )


@router.post("/auto-build")
async def auto_build_portfolio(
    budget: float = Query(500, ge=100, le=100_000, description="Total capital to invest"),
    max_positions: int = Query(5, ge=1, le=15, description="How many stocks to spread across"),
    min_confidence: float = Query(0.55, ge=0.5, le=0.95, description="Minimum model confidence"),
    db: Session = Depends(get_db),
):
    """Reset portfolio to `budget`, scan universe, and BUY the top `max_positions`
    high-confidence UP signals — confidence-weighted allocation across them.
    Each position gets a 3% stop-loss and 5% take-profit derived from entry.
    """
    portfolio = reset_portfolio(db, initial_capital=budget)

    scan = scan_universe(db, budget=budget, include_weak=False, limit=50)
    picks = [
        r for r in scan["results"]
        if r["direction"] == "UP" and r["confidence"] >= min_confidence
    ][:max_positions]

    if not picks:
        return {
            "executed": [],
            "skipped_reason": (
                f"No UP-direction picks with confidence >= {min_confidence*100:.0f}% "
                f"within a ${budget:,.0f} budget."
            ),
            "portfolio_after": PortfolioSummary(**build_summary(db, portfolio)),
        }

    total_conf = sum(p["confidence"] for p in picks) or 1.0
    executed: list[dict] = []
    skipped: list[dict] = []

    for pick in picks:
        allocation = budget * (pick["confidence"] / total_conf)
        price = pick["current_price"]
        shares = int(allocation / price) if price > 0 else 0
        if shares < 1:
            skipped.append({"ticker": pick["ticker"], "reason": "allocation < 1 share"})
            continue

        stop_loss = round(price * 0.97, 2)
        take_profit = round(price * 1.05, 2)

        try:
            trade = execute_trade(
                db,
                portfolio_id=portfolio.id,
                ticker=pick["ticker"],
                action="BUY",
                shares=shares,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                source="auto_build",
            )
        except PortfolioError as exc:
            skipped.append({"ticker": pick["ticker"], "reason": str(exc)})
            continue

        executed.append(
            {
                "ticker": pick["ticker"],
                "shares": trade.shares,
                "price": trade.price,
                "notional": trade.notional,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "confidence": pick["confidence"],
                "trust_score": pick["trust_score"],
                "predicted_price_target": pick["predicted_price_target"],
                "expected_gain_usd": pick["expected_gain_usd"],
                "signal": pick["signal"],
            }
        )

    db.refresh(portfolio)
    return {
        "budget": budget,
        "max_positions": max_positions,
        "min_confidence": min_confidence,
        "executed": executed,
        "skipped": skipped,
        "total_notional_deployed": round(sum(t["notional"] for t in executed), 2),
        "portfolio_after": PortfolioSummary(**build_summary(db, portfolio)),
    }


@router.post("/enforce-stops", response_model=EnforcementResult)
async def enforce(db: Session = Depends(get_db)):
    """Scan open positions, close any where price crossed stop_loss or take_profit.

    Idempotent: positions already closed on a previous call are skipped.
    Call daily (via cron) after market close, or on-demand from Swagger.
    """
    portfolio = get_or_create_portfolio(db)
    actions = enforce_stops(db, portfolio)
    db.refresh(portfolio)
    return EnforcementResult(
        triggered=sum(1 for a in actions if not a.get("error")),
        actions=[EnforcementAction(**a) for a in actions],
        portfolio_after=PortfolioSummary(**build_summary(db, portfolio)),
    )


@router.post("/snapshot", response_model=SnapshotOut)
async def snapshot(db: Session = Depends(get_db)):
    """Capture today's portfolio state as a snapshot.

    Idempotent per day — calling twice on the same day updates the existing row.
    Call this once a day (via cron / GitHub Action) to build the equity curve.
    """
    portfolio = get_or_create_portfolio(db)
    snap = take_snapshot(db, portfolio)
    return SnapshotOut.model_validate(snap)


@router.get("/history", response_model=HistoryResponse)
async def history(days: int = 30, db: Session = Depends(get_db)):
    """Return the last N days of portfolio snapshots (oldest first) for charting."""
    portfolio = get_or_create_portfolio(db)
    snaps = get_history(db, portfolio.id, days=days)
    snapshots = [SnapshotOut.model_validate(s) for s in snaps]

    first_value = snapshots[0].total_value if snapshots else None
    last_value = snapshots[-1].total_value if snapshots else None
    period_return_usd = (
        (last_value - first_value) if (first_value is not None and last_value is not None) else None
    )
    period_return_pct = (
        (period_return_usd / first_value * 100)
        if (first_value and first_value != 0 and period_return_usd is not None)
        else None
    )

    return HistoryResponse(
        portfolio_id=portfolio.id,
        days=days,
        count=len(snapshots),
        snapshots=snapshots,
        first_value=first_value,
        last_value=last_value,
        period_return_usd=period_return_usd,
        period_return_pct=period_return_pct,
    )


@router.get("/accuracy")
async def accuracy(db: Session = Depends(get_db)):
    """Model track record: overall + per-ticker accuracy from evaluated predictions."""
    return accuracy_summary(db)


@router.get("/trades", response_model=list[TradeOut])
async def get_trades(
    limit: int = 50,
    ticker: str | None = None,
    db: Session = Depends(get_db),
):
    """Get trade history (newest first)."""
    portfolio = get_or_create_portfolio(db)
    query = db.query(Trade).filter(Trade.portfolio_id == portfolio.id)
    if ticker:
        query = query.filter(Trade.ticker == ticker.upper())
    trades = query.order_by(Trade.executed_at.desc()).limit(limit).all()
    return [TradeOut.model_validate(t) for t in trades]
