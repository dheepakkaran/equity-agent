"""Technical indicator computations from OHLCV data.

Pure pandas functions — no DB, no I/O. Reusable by ML pipeline and agent layer.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "macd_signal": signal_line, "macd_hist": hist})


def bollinger_bands(
    series: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> pd.DataFrame:
    mid = sma(series, window)
    std = series.rolling(window=window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return pd.DataFrame({"bb_upper": upper, "bb_mid": mid, "bb_lower": lower})


def returns(series: pd.Series, periods: tuple[int, ...] = (1, 5, 20)) -> pd.DataFrame:
    return pd.DataFrame({f"ret_{p}d": series.pct_change(periods=p) for p in periods})


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 14,
) -> pd.Series:
    """Average True Range (Wilder smoothing).

    TR = max(H - L, |H - C_prev|, |L - C_prev|).
    A real volatility measure — captures gaps, unlike return-based proxies.
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()


def compute_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the full feature set from an OHLCV DataFrame.

    Expects columns: date, open, high, low, close, volume — sorted ascending by date.
    Returns df with feature columns appended. Rows with insufficient history contain NaN.
    """
    out = df.copy()
    close = out["close"]

    out["sma_20"] = sma(close, 20)
    out["sma_50"] = sma(close, 50)
    out["ema_12"] = ema(close, 12)
    out["ema_26"] = ema(close, 26)
    out["rsi_14"] = rsi(close, 14)
    out = pd.concat([out, macd(close)], axis=1)
    out = pd.concat([out, bollinger_bands(close)], axis=1)
    out = pd.concat([out, returns(close)], axis=1)

    out["atr_14"] = atr(out["high"], out["low"], close, 14)
    out["volume_sma_20"] = sma(out["volume"].astype(float), 20)

    return out
