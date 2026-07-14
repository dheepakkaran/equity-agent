from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.coordinator import run_analysis
from app.database import get_db
from app.models.portfolio import Trade
from app.schemas.portfolio import (
    ExecutionResult,
    PortfolioSummary,
    TradeOut,
    TradeRequest,
)
from app.services.portfolio_service import (
    PortfolioError,
    build_summary,
    execute_trade,
    get_or_create_portfolio,
    reset_portfolio,
)

router = APIRouter()


@router.get("", response_model=PortfolioSummary)
async def get_portfolio(db: Session = Depends(get_db)):
    """Get current portfolio state: cash, open positions with unrealized P&L, total return."""
    portfolio = get_or_create_portfolio(db)
    return PortfolioSummary(**build_summary(db, portfolio))


@router.post("/reset", response_model=PortfolioSummary)
async def reset(db: Session = Depends(get_db)):
    """Wipe all positions + trades, restore cash to initial capital."""
    portfolio = reset_portfolio(db)
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
        return ExecutionResult(
            executed=False,
            reason="Risk agent suggested 0 shares (confidence too low).",
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
