from datetime import date

from pydantic import BaseModel, Field


class FeatureRow(BaseModel):
    date: date
    close: float
    sma_20: float | None = None
    sma_50: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_hist: float | None = None
    bb_upper: float | None = None
    bb_mid: float | None = None
    bb_lower: float | None = None
    ret_1d: float | None = None
    ret_5d: float | None = None
    ret_20d: float | None = None
    volume_sma_20: float | None = None


class FeatureResponse(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol")
    count: int = Field(..., description="Number of rows returned")
    features: list[FeatureRow]
