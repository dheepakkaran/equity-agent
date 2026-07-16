"""Universe of tickers the system tracks.

~120 US stocks and ETFs curated for price diversity so a small ($500) budget
still has meaningful candidates. Groups: mega-cap tech, financials, energy,
healthcare, consumer, industrials, popular growth / meme, and broad ETFs.

No dotted tickers (e.g. BRK.B) since yfinance handles them inconsistently.
"""

TOP_TICKERS: list[str] = [
    # === Mega-cap tech ===
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "ORCL",
    "CRM", "ADBE", "AMD", "NFLX", "INTC", "CSCO", "QCOM", "TXN", "IBM",

    # === Financials ===
    "JPM", "V", "MA", "BAC", "WFC", "C", "GS", "MS", "USB", "PNC", "TFC",
    "SCHW", "AXP", "COF", "BX", "KKR",

    # === Energy ===
    "XOM", "CVX", "COP", "SLB", "OXY", "HAL", "DVN", "PSX", "MRO", "APA",

    # === Healthcare ===
    "JNJ", "LLY", "MRK", "ABBV", "PFE", "TMO", "ABT", "DHR", "BMY", "GILD",
    "CVS", "WBA", "MRNA", "AMGN", "REGN", "VRTX",

    # === Consumer ===
    "WMT", "COST", "HD", "PG", "KO", "PEP", "MCD", "NKE", "DIS", "SBUX",
    "TGT", "LOW", "TJX", "F", "GM", "DPZ", "CMG", "YUM",

    # === Industrials / Aero ===
    "GE", "MMM", "HON", "CAT", "DE", "BA", "LMT", "RTX", "UPS", "FDX",
    "DAL", "UAL", "LUV",

    # === Telecom / Media ===
    "T", "VZ", "TMUS", "CMCSA", "PARA", "WBD",

    # === Materials / Utilities ===
    "LIN", "FCX", "NUE", "NEE", "DUK",

    # === Growth / meme / recent-IPO ===
    "PLTR", "SOFI", "RIVN", "LCID", "NIO", "XPEV", "SNAP", "PINS", "DKNG",
    "HOOD", "SHOP", "SQ", "PYPL", "COIN", "ZM", "DOCU", "SNOW", "DDOG",
    "NET", "CRWD", "MDB", "PATH",

    # === Popular ETFs (broad + sector) ===
    "SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "ARKK",
    "XLF", "XLE", "XLK", "XLV", "XLY", "XLI",
]
