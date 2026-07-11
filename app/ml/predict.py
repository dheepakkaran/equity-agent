"""Load trained XGBoost model and predict next-day direction for a ticker."""
from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from sqlalchemy.orm import Session

from app.ml.dataset import (
    FEATURE_COLUMNS,
    InsufficientDataError,
    load_ohlcv_frame,
)
from app.services.features import compute_all_features

MODEL_DIR = Path("models")


class ModelNotTrainedError(Exception):
    """Raised when no saved model exists for the ticker."""


def _model_path(ticker: str) -> Path:
    return MODEL_DIR / f"{ticker.upper()}_xgb.joblib"


def predict_next_day(ticker: str, db: Session) -> dict:
    """Predict next-day direction using the most recent row of features.

    Returns dict with prediction (0 or 1), probability, and the feature snapshot used.
    """
    ticker_upper = ticker.upper()
    path = _model_path(ticker_upper)
    if not path.exists():
        raise ModelNotTrainedError(
            f"No trained model for {ticker_upper}. "
            f"Train first via POST /predict/{ticker_upper}/train"
        )

    model = joblib.load(path)

    raw = load_ohlcv_frame(ticker_upper, db)
    features_df = compute_all_features(raw)
    features_df = features_df.dropna(subset=FEATURE_COLUMNS)

    if features_df.empty:
        raise InsufficientDataError(
            f"No rows with complete features for {ticker_upper}."
        )

    latest = features_df.iloc[-1]
    features_dict = {col: float(latest[col]) for col in FEATURE_COLUMNS}
    X = pd.DataFrame([features_dict])

    probs = model.predict_proba(X)[0]
    pred = int(probs.argmax())

    as_of = latest["date"]
    if hasattr(as_of, "isoformat"):
        as_of_str = as_of.isoformat()
    else:
        as_of_str = str(as_of)

    return {
        "ticker": ticker_upper,
        "as_of_date": as_of_str,
        "close": float(latest["close"]),
        "prediction": pred,
        "direction": "UP" if pred == 1 else "DOWN",
        "confidence": float(probs[pred]),
        "prob_up": float(probs[1]),
        "prob_down": float(probs[0]),
        "features_used": features_dict,
    }
