from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, String, UniqueConstraint

from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class PredictionOutcome(Base):
    __tablename__ = "prediction_outcomes"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    predicted_at = Column(Date, nullable=False, index=True)
    direction = Column(String(4), nullable=False)
    confidence = Column(Float, nullable=False)
    close_at_prediction = Column(Float, nullable=False)
    target_date = Column(Date, nullable=False)
    actual_close_at_target = Column(Float, nullable=True)
    actual_return_pct = Column(Float, nullable=True)
    was_correct = Column(Boolean, nullable=True)
    evaluated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("ticker", "predicted_at", name="uq_prediction_ticker_date"),
    )
