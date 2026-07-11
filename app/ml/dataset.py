"""Build ML datasets from persisted OHLCV.

Load ticker rows, compute features, build (X, y) where y is next-day
direction (1 if next close > today close, else 0). Drop rows with NaN
features so the earliest ~50 warm-up days aren't fed to the model.
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from app.models.stock import StockOHLCV
from app.services.features import compute_all_features

FEATURE_COLUMNS: list[str] = [
    "sma_20",
    "sma_50",
    "ema_12",
    "ema_26",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_hist",
    "bb_upper",
    "bb_mid",
    "bb_lower",
    "ret_1d",
    "ret_5d",
    "ret_20d",
    "volume_sma_20",
]


class InsufficientDataError(Exception):
    """Raised when not enough rows exist to build a training set."""


def load_ohlcv_frame(ticker: str, db: Session) -> pd.DataFrame:
    ticker_upper = ticker.upper()
    rows = (
        db.query(StockOHLCV)
        .filter(StockOHLCV.ticker == ticker_upper)
        .order_by(StockOHLCV.date.asc())
        .all()
    )
    if not rows:
        raise InsufficientDataError(f"No stored data for ticker: {ticker_upper}")
    return pd.DataFrame(
        [
            {
                "date": r.date,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ]
    )


def build_supervised_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return feature dataframe with next-day direction label attached.

    Adds `target` column: 1 if next-day close > today's close, else 0.
    Drops the final row (no next-day label) and any row with NaN features.
    """
    features_df = compute_all_features(df)
    features_df["target"] = (features_df["close"].shift(-1) > features_df["close"]).astype(int)
    features_df = features_df.iloc[:-1]  # drop last row (no label)
    features_df = features_df.dropna(subset=FEATURE_COLUMNS)
    return features_df.reset_index(drop=True)


def train_test_split_time(
    df: pd.DataFrame,
    test_size: float = 0.2,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological split — earliest rows train, latest rows test.

    No shuffle: leaking future info into the training set would inflate metrics.
    """
    if len(df) < 20:
        raise InsufficientDataError(
            f"Need at least 20 labeled rows for train/test split, got {len(df)}"
        )
    split_idx = int(len(df) * (1 - test_size))
    return df.iloc[:split_idx], df.iloc[split_idx:]
