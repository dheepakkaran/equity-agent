"""Train XGBoost classifier for next-day direction prediction.

Logs params, metrics, and model artifact to MLflow. Also saves the model
locally so predict.py can load without an MLflow tracking server.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import joblib
import mlflow
import mlflow.xgboost
import xgboost as xgb
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sqlalchemy.orm import Session

from app.ml.dataset import (
    FEATURE_COLUMNS,
    InsufficientDataError,
    build_supervised_frame,
    load_ohlcv_frame,
    train_test_split_time,
)

MODEL_DIR = Path("models")
MODEL_DIR.mkdir(exist_ok=True)


def _model_path(ticker: str) -> Path:
    return MODEL_DIR / f"{ticker.upper()}_xgb.joblib"


def train_ticker(
    ticker: str,
    db: Session,
    n_estimators: int = 200,
    max_depth: int = 4,
    learning_rate: float = 0.05,
    test_size: float = 0.2,
) -> dict:
    """Train XGBoost on stored OHLCV and log to MLflow.

    Returns a summary dict with metrics + model path.
    Raises InsufficientDataError if too few rows.
    """
    ticker_upper = ticker.upper()

    raw = load_ohlcv_frame(ticker_upper, db)
    supervised = build_supervised_frame(raw)

    if len(supervised) < 30:
        raise InsufficientDataError(
            f"Only {len(supervised)} usable rows for {ticker_upper} after feature warmup. "
            f"Fetch more history via GET /stocks/{ticker_upper}?days=365"
        )

    train_df, test_df = train_test_split_time(supervised, test_size=test_size)

    X_train = train_df[FEATURE_COLUMNS]
    y_train = train_df["target"]
    X_test = test_df[FEATURE_COLUMNS]
    y_test = test_df["target"]

    # Compute class balance to counteract label skew.
    # scale_pos_weight upweights the minority class. Only apply when positives
    # (UP labels) are actually the minority — over 10 years of daily data the
    # market usually trends up, so positives are majority and naively applying
    # neg/pos would *downweight* UP and cause a systemic DOWN-bias.
    pos_count = int((y_train == 1).sum())
    neg_count = int((y_train == 0).sum())
    if pos_count == 0:
        scale_pos_weight = 1.0
    elif pos_count < neg_count:
        scale_pos_weight = neg_count / pos_count  # upweight rare UP class
    else:
        scale_pos_weight = 1.0  # positives already majority, leave alone

    mlflow.set_experiment("equity-agent-direction")

    with mlflow.start_run(run_name=f"{ticker_upper}_{datetime.utcnow():%Y%m%d_%H%M%S}"):
        mlflow.log_params(
            {
                "ticker": ticker_upper,
                "n_estimators": n_estimators,
                "max_depth": max_depth,
                "learning_rate": learning_rate,
                "test_size": test_size,
                "train_rows": len(X_train),
                "test_rows": len(X_test),
                "train_pos_count": pos_count,
                "train_neg_count": neg_count,
                "scale_pos_weight": round(scale_pos_weight, 3),
                "features": ",".join(FEATURE_COLUMNS),
            }
        )

        model = xgb.XGBClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            objective="binary:logistic",
            eval_metric="logloss",
            use_label_encoder=False,
            random_state=42,
            scale_pos_weight=scale_pos_weight,
        )
        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)

        metrics = {
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "precision": float(precision_score(y_test, y_pred, zero_division=0)),
            "recall": float(recall_score(y_test, y_pred, zero_division=0)),
            "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        }
        mlflow.log_metrics(metrics)
        mlflow.xgboost.log_model(model, artifact_path="model")

        model_path = _model_path(ticker_upper)
        joblib.dump(model, model_path)

    return {
        "ticker": ticker_upper,
        "train_rows": len(X_train),
        "test_rows": len(X_test),
        "metrics": metrics,
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
        "classification_report": classification_report(
            y_test, y_pred, zero_division=0, output_dict=True
        ),
        "model_path": str(model_path),
        "feature_importances": dict(
            zip(FEATURE_COLUMNS, [float(x) for x in model.feature_importances_])
        ),
    }
