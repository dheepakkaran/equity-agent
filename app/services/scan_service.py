"""Scan universe for ranked, affordable trade candidates.

Extracted from the /scan endpoint so both HTTP and internal callers (e.g.
POST /portfolio/auto-build) share the same ranking logic.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.ml.predict import ModelNotTrainedError, predict_next_day
from app.services.prediction_tracking import trust_score
from app.tickers import TOP_TICKERS


def _classify(confidence: float, adjusted_conf: float, direction: str) -> str:
    if confidence >= 0.65 and adjusted_conf >= 0.35:
        return f"STRONG_{'BUY' if direction == 'UP' else 'AVOID'}"
    if confidence >= 0.55:
        return f"MODERATE_{'BUY' if direction == 'UP' else 'AVOID'}"
    return "WEAK"


def scan_universe(
    db: Session,
    budget: float,
    include_weak: bool = False,
    limit: int = 50,
) -> dict:
    """Predict on every tracked ticker, filter to what fits the budget, rank by expected gain."""
    results: list[dict] = []
    errors_count = 0

    for ticker in TOP_TICKERS:
        try:
            pred = predict_next_day(ticker, db)
        except ModelNotTrainedError:
            errors_count += 1
            continue
        except Exception:
            errors_count += 1
            continue

        current_price = float(pred["close"])
        max_shares = int(budget / current_price) if current_price > 0 else 0
        if max_shares < 1:
            continue

        trust = trust_score(db, ticker)
        adjusted_conf = pred["confidence"] * (0.5 + trust)

        conf_edge = (pred["confidence"] - 0.5) * 2
        signed_edge = conf_edge if pred["direction"] == "UP" else -conf_edge
        expected_5d_return_pct = signed_edge * 3.0
        # A concrete predicted price gives the user a "if the model is right,
        # this ticker moves to $X in ~5 days" number.
        predicted_price_target = current_price * (1 + expected_5d_return_pct / 100)
        expected_gain_usd = current_price * (expected_5d_return_pct / 100) * max_shares
        notional_at_max = current_price * max_shares

        signal = _classify(pred["confidence"], adjusted_conf, pred["direction"])
        if not include_weak and signal == "WEAK":
            continue

        results.append(
            {
                "ticker": ticker,
                "current_price": round(current_price, 2),
                "predicted_price_target": round(predicted_price_target, 2),
                "direction": pred["direction"],
                "confidence": round(pred["confidence"], 4),
                "trust_score": round(trust, 4),
                "adjusted_confidence": round(adjusted_conf, 4),
                "max_shares_affordable": max_shares,
                "notional_at_max_shares": round(notional_at_max, 2),
                "expected_5d_return_pct": round(expected_5d_return_pct, 2),
                "expected_gain_usd": round(expected_gain_usd, 2),
                "signal": signal,
            }
        )

    signal_order = {
        "STRONG_BUY": 0, "STRONG_AVOID": 1,
        "MODERATE_BUY": 2, "MODERATE_AVOID": 3,
        "WEAK": 4,
    }
    results.sort(
        key=lambda r: (
            signal_order.get(r["signal"], 9),
            -abs(r["expected_gain_usd"]),
            -r["adjusted_confidence"],
        )
    )

    return {
        "budget": budget,
        "total_scanned": len(TOP_TICKERS),
        "affordable_count": len(results),
        "results": results[:limit],
        "errors_count": errors_count,
    }
