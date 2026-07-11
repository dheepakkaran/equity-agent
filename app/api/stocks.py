from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock import StockOHLCV
from app.schemas.stock import OHLCVData, StockResponse
from app.services.data_service import DataFetchError, fetch_stock_data

router = APIRouter()


@router.get("/{ticker}", response_model=StockResponse)
async def get_stock(
    ticker: str,
    days: int = Query(30, ge=1, le=3650, description="Trailing days to fetch"),
    db: Session = Depends(get_db),
):
    """Fetch OHLCV data from Yahoo Finance and persist to Postgres."""
    try:
        return fetch_stock_data(ticker, days, db)
    except DataFetchError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{ticker}/history", response_model=StockResponse)
async def get_stock_history(
    ticker: str,
    limit: int = Query(30, ge=1, le=1000, description="Max records to return"),
    db: Session = Depends(get_db),
):
    """Return persisted OHLCV rows for a ticker (from Postgres, no external call)."""
    ticker_upper = ticker.upper()
    rows = (
        db.query(StockOHLCV)
        .filter(StockOHLCV.ticker == ticker_upper)
        .order_by(StockOHLCV.date.desc())
        .limit(limit)
        .all()
    )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No stored data for ticker: {ticker_upper}. "
            f"Fetch via GET /stocks/{ticker_upper} first.",
        )

    data = [
        OHLCVData(
            date=r.date,
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=r.volume,
        )
        for r in reversed(rows)
    ]

    return StockResponse(
        ticker=ticker_upper,
        days=len(data),
        count=len(data),
        data=data,
    )
