from datetime import date

from pydantic import BaseModel, Field


class OHLCVData(BaseModel):
    date: date
    open: float = Field(..., description="Opening price")
    high: float = Field(..., description="Highest price of the day")
    low: float = Field(..., description="Lowest price of the day")
    close: float = Field(..., description="Closing price")
    volume: int = Field(..., description="Traded volume")


class StockResponse(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol (e.g., AAPL)")
    days: int = Field(..., description="Number of days of data returned")
    count: int = Field(..., description="Total records in response")
    data: list[OHLCVData]
