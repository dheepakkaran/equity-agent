from sqlalchemy import BigInteger, Column, Date, Float, Integer, String, UniqueConstraint

from app.database import Base


class StockOHLCV(Base):
    __tablename__ = "stocks_ohlcv"

    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(BigInteger, nullable=False)

    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_ticker_date"),
    )

    def __repr__(self) -> str:
        return f"<StockOHLCV {self.ticker} {self.date} close={self.close}>"
