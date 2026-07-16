"""Risk agent — rule-based position sizing and stop-loss using recent volatility.

Purely deterministic. Uses the 20-day return magnitude as a rough volatility proxy
(no ATR yet — that comes in a later feature engineering pass).
"""
from __future__ import annotations

from app.agents.base import AgentState

DEFAULT_PORTFOLIO_USD = 10_000.0

# Risk-per-trade % scales with portfolio size. Small demo portfolios need
# a higher % or the risk budget becomes too small to size any trade at all.
def _risk_pct_for(portfolio_usd: float) -> float:
    if portfolio_usd <= 1_000:
        return 0.15  # $150 max risk on a $1000 portfolio
    if portfolio_usd <= 5_000:
        return 0.08
    if portfolio_usd <= 20_000:
        return 0.05
    return 0.02  # institutional-style at $20k+


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
    portfolio_usd = float(state.get("portfolio_capital") or DEFAULT_PORTFOLIO_USD)

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

    # Kelly-lite: scale nominal risk by (confidence - 0.5), floor at 0.
    # For demo-friendliness a softer curve is used (0.45 baseline instead of 0.50)
    # so a ~55% confidence signal still produces a small position.
    conf_edge = max(0.0, confidence - 0.45) * 2.0  # maps 0.45→0, 0.95→1
    risk_pct = _risk_pct_for(portfolio_usd)
    risk_budget_usd = portfolio_usd * risk_pct * conf_edge

    if stop_loss is not None and stop_distance > 0:
        suggested_shares = int(risk_budget_usd / stop_distance) if risk_budget_usd > 0 else 0
    else:
        suggested_shares = 0

    # AFFORDABILITY CAP: the notional value of the position must never exceed
    # the user's total portfolio capital. Without this, SHORT trades could
    # be sized larger than the budget (cash grows from short proceeds, hiding
    # the true exposure). This makes the sizing match user intuition:
    # "$500 budget = at most $500 of exposure".
    max_affordable = int(portfolio_usd / close) if close > 0 else 0
    unaffordable = suggested_shares > max_affordable
    suggested_shares = min(suggested_shares, max_affordable)

    # Demo floor: if the model is at all confident and we can afford one share,
    # guarantee at least one share so the pipeline can exercise the whole
    # trade → snapshot → outcome loop.
    if suggested_shares == 0 and confidence >= 0.55 and max_affordable >= 1:
        suggested_shares = 1

    notional = suggested_shares * close
    # Expected P&L if the take_profit or stop_loss levels hit
    if take_profit is not None and direction == "UP":
        max_gain_usd = (take_profit - close) * suggested_shares
    elif take_profit is not None and direction == "DOWN":
        max_gain_usd = (close - take_profit) * suggested_shares
    else:
        max_gain_usd = 0.0

    if stop_loss is not None and direction == "UP":
        max_loss_usd = (close - stop_loss) * suggested_shares  # positive number
    elif stop_loss is not None and direction == "DOWN":
        max_loss_usd = (stop_loss - close) * suggested_shares  # positive number
    else:
        max_loss_usd = 0.0

    expected_return_pct = (max_gain_usd / notional * 100) if notional > 0 else 0.0
    max_loss_pct = (max_loss_usd / notional * 100) if notional > 0 else 0.0

    if suggested_shares == 0:
        if close > portfolio_usd:
            zero_reason = f"{state.get('ticker', 'ticker')} at ${close:.2f} exceeds your ${portfolio_usd:,.0f} budget."
        elif confidence < 0.55:
            zero_reason = f"Confidence {confidence*100:.1f}% below demo threshold (55%)."
        else:
            zero_reason = "Signal too weak or no direction."
    else:
        zero_reason = ""

    return {
        "risk_assessment": {
            "portfolio_usd_assumed": portfolio_usd,
            "risk_per_trade_pct": round(risk_pct * 100, 2),
            "daily_vol_estimate": round(vol, 4),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_reward_ratio": 1.5,
            "suggested_shares": suggested_shares,
            "notional_usd": round(notional, 2),
            "max_potential_gain_usd": round(max_gain_usd, 2),
            "max_potential_loss_usd": round(max_loss_usd, 2),
            "expected_return_pct": round(expected_return_pct, 2),
            "max_loss_pct": round(max_loss_pct, 2),
            "unaffordable_capped": bool(unaffordable and max_affordable > 0),
            "skip_reason": zero_reason,
            "notes": (
                f"Notional capped to fit ${portfolio_usd:,.0f} budget. "
                f"Risk-per-trade auto-scaled to {risk_pct*100:.0f}%. "
                f"If prediction hits take-profit → +${max_gain_usd:.2f} ({expected_return_pct:+.2f}%). "
                f"If stopped out → -${max_loss_usd:.2f} ({max_loss_pct:.2f}%)."
            ),
        }
    }
