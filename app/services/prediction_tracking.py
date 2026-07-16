"""Record daily model predictions and evaluate them once the target date passes.

Enables:
- "Was yesterday's forecast right?" — evaluate_pending_predictions()
- Per-ticker trust score (rolling accuracy) — trust_score()
- Overall model track record — accuracy_summary()
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.ml.predict import ModelNotTrainedError, predict_next_day
from app.models.prediction import PredictionOutcome
from app.models.stock import StockOHLCV

TARGET_HORIZON_DAYS = 7  # ~5 trading days + weekend padding


def record_prediction(db: Session, ticker: str) -> PredictionOutcome | None:
    """Predict today for a ticker and store the outcome-in-waiting.

    Returns the row (existing or new). Silently returns None if the model
    isn't trained or the ticker has no data.
    """
    try:
        pred = predict_next_day(ticker, db)
    except (ModelNotTrainedError, Exception):
        return None

    today = datetime.now(timezone.utc).date()
    existing = (
        db.query(PredictionOutcome)
        .filter(PredictionOutcome.ticker == ticker.upper(), PredictionOutcome.predicted_at == today)
        .first()
    )
    if existing:
        return existing

    row = PredictionOutcome(
        ticker=ticker.upper(),
        predicted_at=today,
        direction=pred["direction"],
        confidence=float(pred["confidence"]),
        close_at_prediction=float(pred["close"]),
        target_date=today + timedelta(days=TARGET_HORIZON_DAYS),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def evaluate_pending_predictions(db: Session) -> int:
    """Score any un-evaluated predictions whose target_date is past.

    Returns count evaluated.
    """
    today = datetime.now(timezone.utc).date()
    pending = (
        db.query(PredictionOutcome)
        .filter(
            PredictionOutcome.was_correct.is_(None),
            PredictionOutcome.target_date <= today,
        )
        .all()
    )

    evaluated = 0
    for p in pending:
        actual = (
            db.query(StockOHLCV)
            .filter(
                StockOHLCV.ticker == p.ticker,
                StockOHLCV.date >= p.target_date,
            )
            .order_by(StockOHLCV.date.asc())
            .first()
        )
        if not actual:
            continue
        actual_close = float(actual.close)
        p.actual_close_at_target = actual_close
        p.actual_return_pct = ((actual_close - p.close_at_prediction) / p.close_at_prediction) * 100
        actual_direction = "UP" if actual_close > p.close_at_prediction else "DOWN"
        p.was_correct = (actual_direction == p.direction)
        p.evaluated_at = datetime.now(timezone.utc)
        evaluated += 1

    if evaluated:
        db.commit()
    return evaluated


def trust_score(db: Session, ticker: str, lookback_days: int = 90) -> float:
    """Rolling accuracy score in [-0.5, +0.5]. 0 = coin flip, +0.5 = perfect.

    Returns 0.0 (neutral) if the table doesn't exist yet or if the query fails
    for any reason — trust score is best-effort, never a hard blocker.
    """
    try:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=lookback_days)
        outcomes = (
            db.query(PredictionOutcome)
            .filter(
                PredictionOutcome.ticker == ticker.upper(),
                PredictionOutcome.was_correct.isnot(None),
                PredictionOutcome.predicted_at >= cutoff,
            )
            .all()
        )
    except Exception:  # noqa: BLE001 — table missing / connection issue → neutral trust
        db.rollback()
        return 0.0
    if not outcomes:
        return 0.0
    accuracy = sum(1 for o in outcomes if o.was_correct) / len(outcomes)
    return accuracy - 0.5


def accuracy_summary(db: Session) -> dict:
    """Return overall + per-ticker accuracy from all evaluated predictions.

    Degrades gracefully to empty summary if the table doesn't exist yet.
    """
    try:
        outcomes = (
            db.query(PredictionOutcome)
            .filter(PredictionOutcome.was_correct.isnot(None))
            .all()
        )
    except Exception:  # noqa: BLE001 — table missing
        db.rollback()
        outcomes = []

    if not outcomes:
        return {
            "total_evaluated": 0,
            "correct": 0,
            "overall_accuracy_pct": None,
            "reward_points": 0,
            "per_ticker": [],
        }

    correct = sum(1 for o in outcomes if o.was_correct)
    # Simple gamification: 10 points for each correct prediction, +5 bonus for
    # any high-confidence (>= 70%) correct call, so the model is rewarded for
    # committing hard to bets that pay off.
    reward_points = sum(
        10 + (5 if o.confidence >= 0.70 else 0)
        for o in outcomes if o.was_correct
    )
    by_ticker = defaultdict(list)
    for o in outcomes:
        by_ticker[o.ticker].append(o)

    per_ticker = []
    for t, outs in by_ticker.items():
        n_correct = sum(1 for o in outs if o.was_correct)
        per_ticker.append(
            {
                "ticker": t,
                "predictions": len(outs),
                "correct": n_correct,
                "accuracy_pct": round(n_correct / len(outs) * 100, 2),
            }
        )
    per_ticker.sort(key=lambda x: (-x["accuracy_pct"], -x["predictions"]))

    return {
        "total_evaluated": len(outcomes),
        "correct": correct,
        "overall_accuracy_pct": round(correct / len(outcomes) * 100, 2),
        "reward_points": reward_points,
        "per_ticker": per_ticker,
    }
