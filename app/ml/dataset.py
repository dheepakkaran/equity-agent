"""Build ML datasets from persisted OHLCV.

Target: 5-day direction — 1 if close[t+5] > close[t], else 0. Using a
5-day horizon instead of 1-day dramatically reduces noise (daily direction
is close to random walk; multi-day trends carry real signal).

Feature set drops the redundant `bb_mid` (was collinear with sma_20 in
practice — zero XGBoost importance) and adds `atr_14` (real Wilder ATR,
captures volatility including gaps, unlike |ret_20d|/20 proxies).
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy.orm import Session

from app.models.stock import StockOHLCV
from app.services.features import compute_all_features

TARGET_HORIZON = 5

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
    "bb_lower",
    "ret_1d",
    "ret_5d",
    "ret_20d",
    "atr_14",
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


def build_supervised_frame(df: pd.DataFrame, horizon: int = TARGET_HORIZON) -> pd.DataFrame:
    """Return feature dataframe with N-day direction label attached.

    Adds `target` column: 1 if close[t+horizon] > close[t], else 0.
    Drops the final `horizon` rows (no label available) and rows with NaN features.
    """
    features_df = compute_all_features(df)
    features_df["target"] = (
        features_df["close"].shift(-horizon) > features_df["close"]
    ).astype(int)
    features_df = features_df.iloc[:-horizon]  # drop tail without labels
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
