from datetime import datetime, timedelta

import yfinance as yf
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.stock import StockOHLCV
from app.schemas.stock import OHLCVData, StockResponse


class DataFetchError(Exception):
    """Raised when market data cannot be fetched for a ticker."""


def fetch_stock_data(
    ticker: str,
    days: int,
    db: Session,
) -> StockResponse:
    """Fetch OHLCV data from Yahoo Finance and persist to Postgres.

    Uses ON CONFLICT DO NOTHING on (ticker, date) so repeated calls are idempotent.

    Raises:
        DataFetchError: If the ticker returns no data.
    """
    end = datetime.now()
    start = end - timedelta(days=days)

    stock = yf.Ticker(ticker)
    df = stock.history(start=start, end=end, interval="1d")

    if df.empty:
        raise DataFetchError(f"No data found for ticker: {ticker}")

    ticker_upper = ticker.upper()
    records = [
        {
            "ticker": ticker_upper,
            "date": idx.date(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": int(row["Volume"]),
        }
        for idx, row in df.iterrows()
    ]

    # Upsert: insert new rows, skip existing (ticker, date) pairs
    stmt = insert(StockOHLCV).values(records)
    stmt = stmt.on_conflict_do_nothing(index_elements=["ticker", "date"])
    db.execute(stmt)
    db.commit()

    ohlcv = [
        OHLCVData(
            date=r["date"],
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
        )
        for r in records
    ]

    return StockResponse(
        ticker=ticker_upper,
        days=days,
        count=len(ohlcv),
        data=ohlcv,
    )
