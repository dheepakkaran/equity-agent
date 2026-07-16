from typing import Any

from pydantic import BaseModel, Field


class RiskAssessment(BaseModel):
    portfolio_usd_assumed: float
    risk_per_trade_pct: float
    daily_vol_estimate: float
    stop_loss: float | None
    take_profit: float | None
    risk_reward_ratio: float
    suggested_shares: int
    notional_usd: float
    max_potential_gain_usd: float = 0.0
    max_potential_loss_usd: float = 0.0
    expected_return_pct: float = 0.0
    max_loss_pct: float = 0.0
    unaffordable_capped: bool = False
    skip_reason: str = ""
    notes: str


class Headline(BaseModel):
    title: str
    publisher: str | None = None
    published_at: str | None = None
    url: str | None = None
    summary: str | None = None


class AnalysisResponse(BaseModel):
    ticker: str
    as_of_date: str | None
    close: float | None
    features: dict[str, float | None]
    prediction: dict[str, Any] | None = Field(
        None, description="XGBoost next-day direction prediction, if model trained"
    )
    news_headlines: list[Headline] = Field(default_factory=list)
    news_summary: str = ""
    technical_analysis: str
    risk_assessment: RiskAssessment | None
    final_recommendation: str
    errors: list[str] = Field(default_factory=list)
