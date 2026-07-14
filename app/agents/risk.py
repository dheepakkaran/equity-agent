"""Risk agent — rule-based position sizing and stop-loss using recent volatility.

Purely deterministic. Uses the 20-day return magnitude as a rough volatility proxy
(no ATR yet — that comes in a later feature engineering pass).
"""
from __future__ import annotations

from app.agents.base import AgentState

DEFAULT_PORTFOLIO_USD = 10_000.0
RISK_PER_TRADE = 0.02  # never risk more than 2% of portfolio on one trade


def _volatility_proxy(features: dict[str, float | None]) -> float:
    """Estimate daily volatility as fraction of price. Falls back to 2% if unknown."""
    ret_20d = features.get("ret_20d")
    if ret_20d is None:
        return 0.02
    # Convert 20-day cumulative return magnitude to a per-day proxy
    daily = abs(ret_20d) / 20.0
    # Clamp to sensible bounds
    return max(0.005, min(0.10, daily if daily > 0 else 0.02))


def risk_node(state: AgentState) -> AgentState:
    features = state.get("features", {})
    close = state.get("close") or 0.0
    prediction = state.get("prediction") or {}
    direction = prediction.get("direction", "UNKNOWN")
    confidence = float(prediction.get("confidence", 0.5))

    vol = _volatility_proxy(features)
    # Stop-loss distance = 2x daily vol; take-profit = 3x daily vol (1.5 R:R)
    stop_distance = 2.0 * vol * close
    take_profit_distance = 3.0 * vol * close

    if direction == "UP":
        stop_loss = round(close - stop_distance, 4)
        take_profit = round(close + take_profit_distance, 4)
    elif direction == "DOWN":
        stop_loss = round(close + stop_distance, 4)
        take_profit = round(close - take_profit_distance, 4)
    else:
        stop_loss = None
        take_profit = None

    # Kelly-lite: scale nominal risk by (confidence - 0.5), floor at 0
    conf_edge = max(0.0, confidence - 0.5) * 2.0  # maps 0.5→0, 1.0→1
    risk_budget_usd = DEFAULT_PORTFOLIO_USD * RISK_PER_TRADE * conf_edge

    if stop_loss is not None and stop_distance > 0:
        suggested_shares = int(risk_budget_usd / stop_distance) if risk_budget_usd > 0 else 0
    else:
        suggested_shares = 0

    return {
        "risk_assessment": {
            "portfolio_usd_assumed": DEFAULT_PORTFOLIO_USD,
            "risk_per_trade_pct": RISK_PER_TRADE * 100,
            "daily_vol_estimate": round(vol, 4),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_reward_ratio": 1.5,
            "suggested_shares": suggested_shares,
            "notional_usd": round(suggested_shares * close, 2),
            "notes": (
                "Volatility proxied from |ret_20d|/20. "
                "Position sized so max loss ≈ 2% of $10k portfolio, "
                "scaled down by (confidence - 0.5). "
                "Zero shares means confidence too low or no direction."
            ),
        }
    }
