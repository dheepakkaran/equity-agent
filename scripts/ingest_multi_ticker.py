"""Ingest 10 years of OHLCV for all tracked tickers.

Idempotent — calling twice does not create duplicates (thanks to ON CONFLICT
DO NOTHING on the DB side). Prints how many rows exist per ticker after.

Run:
    python scripts/ingest_multi_ticker.py
"""
from __future__ import annotations

import sys

import httpx

BASE_URL = "http://localhost:8000"
TICKERS = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA",
    "GOOGL", "META", "TSLA", "AMZN", "AMD",
]
DAYS = 3650  # ~10 years

TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def main() -> None:
    with httpx.Client(timeout=TIMEOUT) as client:
        try:
            client.get(f"{BASE_URL}/health").raise_for_status()
        except Exception as exc:
            print(f"ERROR: cannot reach {BASE_URL} — is uvicorn running?\n{exc}")
            sys.exit(1)

        print(f"Ingesting {DAYS} days of OHLCV for {len(TICKERS)} tickers...\n")
        for i, ticker in enumerate(TICKERS, 1):
            r = client.get(f"{BASE_URL}/stocks/{ticker}", params={"days": DAYS})
            if r.status_code != 200:
                print(f"[{i}/{len(TICKERS)}] {ticker}: FAIL {r.status_code} {r.text[:150]}")
                continue
            body = r.json()
            print(f"[{i}/{len(TICKERS)}] {ticker}: {body.get('count', 0)} rows returned")

        print("\nAll ingest complete. Run scripts/retrain_all_tickers.py next.")


if __name__ == "__main__":
    main()
