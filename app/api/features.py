import math

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.stock import StockOHLCV
from app.schemas.features import FeatureResponse, FeatureRow
from app.services.features import compute_all_features

router = APIRouter()


def _nan_to_none(value):
    if value is None:
        return None
    try:
        if math.isnan(value):
            return None
    except TypeError:
        pass
    return value


@router.get("/{ticker}/features", response_model=FeatureResponse)
async def get_stock_features(
    ticker: str,
    days: int = Query(90, ge=20, le=1000, description="Trailing days of OHLCV to load"),
    db: Session = Depends(get_db),
):
    """Compute technical indicators from persisted OHLCV.

    Loads the most recent `days` rows for the ticker from Postgres, computes
    SMA/EMA/RSI/MACD/Bollinger/Returns, and returns them ordered oldest to newest.
    """
    ticker_upper = ticker.upper()
    rows = (
        db.query(StockOHLCV)
        .filter(StockOHLCV.ticker == ticker_upper)
        .order_by(StockOHLCV.date.desc())
        .limit(days)
        .all()
    )

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No stored data for ticker: {ticker_upper}. "
            f"Fetch via GET /stocks/{ticker_upper} first.",
        )

    df = pd.DataFrame(
        [
            {
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in reversed(rows)
        ]
    )

    features_df = compute_all_features(df)

    feature_rows = [
        FeatureRow(
            date=row["date"],
            close=row["close"],
            sma_20=_nan_to_none(row.get("sma_20")),
            sma_50=_nan_to_none(row.get("sma_50")),
            ema_12=_nan_to_none(row.get("ema_12")),
            ema_26=_nan_to_none(row.get("ema_26")),
            rsi_14=_nan_to_none(row.get("rsi_14")),
            macd=_nan_to_none(row.get("macd")),
            macd_signal=_nan_to_none(row.get("macd_signal")),
            macd_hist=_nan_to_none(row.get("macd_hist")),
            bb_upper=_nan_to_none(row.get("bb_upper")),
            bb_mid=_nan_to_none(row.get("bb_mid")),
            bb_lower=_nan_to_none(row.get("bb_lower")),
            ret_1d=_nan_to_none(row.get("ret_1d")),
            ret_5d=_nan_to_none(row.get("ret_5d")),
            ret_20d=_nan_to_none(row.get("ret_20d")),
            atr_14=_nan_to_none(row.get("atr_14")),
            volume_sma_20=_nan_to_none(row.get("volume_sma_20")),
        )
        for _, row in features_df.iterrows()
    ]

    return FeatureResponse(
        ticker=ticker_upper,
        count=len(feature_rows),
        features=feature_rows,
    )
