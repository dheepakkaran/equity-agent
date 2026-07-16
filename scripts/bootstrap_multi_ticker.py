"""Bootstrap the paper trading portfolio across all tracked tickers.

For each ticker, in order:
    1. Ingest 10 years of OHLCV
    2. Train an XGBoost 5-day-direction model
    3. Run /portfolio/execute — full multi-agent analysis + auto-trade

Requires uvicorn running locally on :8000. Reset the portfolio first if you
have stale positions:
    POST http://localhost:8000/portfolio/reset

Run:
    python scripts/bootstrap_multi_ticker.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.tickers import TOP_TICKERS

BASE_URL = "http://localhost:8000"
TICKERS = TOP_TICKERS
DAYS = 3650

TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def _pretty_usd(x: float) -> str:
    return f"${x:,.2f}"


def _step(client: httpx.Client, ticker: str) -> dict:
    summary: dict = {"ticker": ticker}

    r = client.get(f"{BASE_URL}/stocks/{ticker}", params={"days": DAYS})
    if r.status_code != 200:
        summary["error"] = f"ingest_{r.status_code}: {r.text[:200]}"
        return summary
    ingested = r.json()
    summary["rows_ingested"] = ingested.get("count", 0)

    r = client.post(f"{BASE_URL}/predict/{ticker}/train")
    if r.status_code != 200:
        summary["error"] = f"train_{r.status_code}: {r.text[:200]}"
        return summary
    train = r.json()
    summary["accuracy"] = train.get("metrics", {}).get("accuracy")

    r = client.post(f"{BASE_URL}/portfolio/execute/{ticker}")
    if r.status_code != 200:
        summary["error"] = f"execute_{r.status_code}: {r.text[:200]}"
        return summary
    execution = r.json()
    summary["executed"] = execution.get("executed", False)
    summary["direction"] = execution.get("recommendation_direction")
    summary["reason"] = execution.get("reason")
    if execution.get("trade"):
        t = execution["trade"]
        summary["action"] = t["action"]
        summary["shares"] = t["shares"]
        summary["price"] = t["price"]
        summary["notional"] = t["notional"]

    return summary


def main() -> None:
    print(f"Bootstrapping portfolio across {len(TICKERS)} tickers ({DAYS} days of history)...\n")

    with httpx.Client(timeout=TIMEOUT) as client:
        try:
            r = client.get(f"{BASE_URL}/health")
            r.raise_for_status()
        except Exception as exc:
            print(f"ERROR: cannot reach {BASE_URL} — is uvicorn running?\n{exc}")
            sys.exit(1)

        results: list[dict] = []
        for i, ticker in enumerate(TICKERS, 1):
            print(f"[{i}/{len(TICKERS)}] {ticker} ...", flush=True)
            start = time.perf_counter()
            summary = _step(client, ticker)
            elapsed = time.perf_counter() - start
            summary["elapsed_s"] = round(elapsed, 1)
            results.append(summary)

            if "error" in summary:
                print(f"    FAIL ({elapsed:.1f}s): {summary['error']}")
            else:
                acc = summary.get("accuracy")
                acc_str = f"{acc:.2%}" if acc is not None else "n/a"
                if summary["executed"]:
                    print(
                        f"    OK ({elapsed:.1f}s): acc={acc_str}, "
                        f"{summary['action']} {summary['shares']} @ ${summary['price']:.2f}"
                    )
                else:
                    print(f"    SKIP ({elapsed:.1f}s): acc={acc_str}, {summary['reason']}")

        print("\nFinal portfolio state:")
        r = client.get(f"{BASE_URL}/portfolio")
        r.raise_for_status()
        p = r.json()

        print(f"  Initial capital:      {_pretty_usd(p['initial_capital'])}")
        print(f"  Cash balance:         {_pretty_usd(p['cash_balance'])}")
        print(f"  Positions net value:  {_pretty_usd(p['positions_market_value'])}")
        print(f"  Total value:          {_pretty_usd(p['total_value'])}")
        print(f"  Total return:         {_pretty_usd(p['total_return_usd'])} ({p['total_return_pct']:.4f}%)")
        print(f"  Open positions:       {len(p['positions'])}")


if __name__ == "__main__":
    main()
