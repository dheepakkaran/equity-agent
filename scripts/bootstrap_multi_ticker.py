"""Bootstrap the paper trading portfolio across multiple tickers.

For each ticker, in order:
    1. Ingest 730 days of OHLCV
    2. Train an XGBoost next-day-direction model
    3. Run /portfolio/execute — analyze via multi-agent, auto-execute the trade

Requires uvicorn running locally on :8000 with a fresh $1M portfolio.
Reset the portfolio first if you have stale positions:
    POST http://localhost:8000/portfolio/reset

Run:
    python scripts/bootstrap_multi_ticker.py
"""
from __future__ import annotations

import sys
import time

import httpx

BASE_URL = "http://localhost:8000"
TICKERS = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA",
    "GOOGL", "META", "TSLA", "AMZN", "AMD",
]

TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def _pretty_usd(x: float) -> str:
    return f"${x:,.2f}"


def _step(client: httpx.Client, ticker: str) -> dict:
    """Run the 3 steps for one ticker and return a summary dict."""
    summary: dict = {"ticker": ticker}

    # 1. Ingest
    r = client.get(f"{BASE_URL}/stocks/{ticker}", params={"days": 730})
    if r.status_code != 200:
        summary["error"] = f"ingest_{r.status_code}: {r.text[:200]}"
        return summary
    ingested = r.json()
    summary["rows_ingested"] = ingested.get("count", 0)

    # 2. Train
    r = client.post(f"{BASE_URL}/predict/{ticker}/train")
    if r.status_code != 200:
        summary["error"] = f"train_{r.status_code}: {r.text[:200]}"
        return summary
    train = r.json()
    summary["accuracy"] = train.get("metrics", {}).get("accuracy")

    # 3. Analyze + execute
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
    print(f"Bootstrapping portfolio across {len(TICKERS)} tickers...\n")

    with httpx.Client(timeout=TIMEOUT) as client:
        # Health check first
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

        # Final portfolio snapshot
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
        if p["positions"]:
            print()
            print(f"  {'Ticker':<8} {'Side':<6} {'Shares':>8} {'Entry':>10} {'Current':>10} {'PnL %':>8}")
            print(f"  {'-'*8} {'-'*6} {'-'*8} {'-'*10} {'-'*10} {'-'*8}")
            for pos in p["positions"]:
                pnl = pos.get("unrealized_pnl_pct") or 0.0
                cur = pos.get("current_price") or 0.0
                print(
                    f"  {pos['ticker']:<8} {pos['side']:<6} {pos['shares']:>8} "
                    f"{pos['avg_entry_price']:>10.2f} {cur:>10.2f} {pnl:>7.2f}%"
                )


if __name__ == "__main__":
    main()
