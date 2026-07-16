"""End-of-day autonomous run: ingest → enforce stops → snapshot.

Meant for a scheduled runner (GitHub Actions cron, Windows Task Scheduler,
Linux cron). Talks directly to the DB — does not require the uvicorn HTTP
server to be running.

Env: DATABASE_URL must be set (from .env locally, or GitHub Secret in CI).

Run:
    python scripts/daily_close.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

# Ensure the project root is on the path so `app` is importable when this
# script is executed directly (e.g. by GitHub Actions).
sys.path.insert(0, str(REPO_ROOT))

from app.database import SessionLocal  # noqa: E402
from app.services.data_service import fetch_stock_data  # noqa: E402
from app.services.portfolio_service import (  # noqa: E402
    build_summary,
    enforce_stops,
    get_or_create_portfolio,
    take_snapshot,
)
from app.services.prediction_tracking import (  # noqa: E402
    evaluate_pending_predictions,
    record_prediction,
)
from app.tickers import TOP_TICKERS  # noqa: E402

TICKERS = TOP_TICKERS


def main() -> None:
    if not os.getenv("DATABASE_URL"):
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    started = datetime.now(timezone.utc)
    print(f"=== daily_close start {started.isoformat()} ===\n")

    db = SessionLocal()
    try:
        # 1. Ingest fresh OHLCV — one week is enough since ingest is idempotent
        print("Step 1: Ingesting fresh OHLCV for all tickers")
        for ticker in TICKERS:
            try:
                result = fetch_stock_data(ticker, days=7, db=db)
                print(f"  {ticker}: {result.count} rows fetched")
            except Exception as exc:  # noqa: BLE001
                print(f"  {ticker}: FAIL {exc}")

        # 2. Evaluate old predictions (5+ days ago) against actual closes
        print("\nStep 2a: Evaluating pending predictions")
        evaluated = evaluate_pending_predictions(db)
        print(f"  {evaluated} prediction(s) evaluated")

        # 2b. Record today's predictions for all tickers
        print("\nStep 2b: Recording today's predictions")
        recorded = 0
        for ticker in TICKERS:
            row = record_prediction(db, ticker)
            if row is not None:
                recorded += 1
        print(f"  {recorded}/{len(TICKERS)} predictions stored")

        # 3. Enforce stops
        print("\nStep 3: Enforcing stop-loss / take-profit")
        portfolio = get_or_create_portfolio(db)
        actions = enforce_stops(db, portfolio)
        if not actions:
            print("  No positions crossed thresholds.")
        else:
            for a in actions:
                if a.get("error"):
                    print(f"  {a['ticker']} {a['action']} FAIL: {a['error']}")
                else:
                    print(
                        f"  {a['ticker']} closed {a['side_closed']} via {a['trigger']}: "
                        f"{a['action']} {a['shares']} @ ${a['price']:.2f} "
                        f"(realized P&L ${a['realized_pnl']:.2f})"
                    )

        # 4. Snapshot
        print("\nStep 4: Taking end-of-day snapshot")
        db.refresh(portfolio)
        snap = take_snapshot(db, portfolio)
        summary = build_summary(db, portfolio)
        print(f"  Date:                 {snap.snapshot_date}")
        print(f"  Cash balance:         ${summary['cash_balance']:,.2f}")
        print(f"  Positions net value:  ${summary['positions_market_value']:,.2f}")
        print(f"  Total value:          ${summary['total_value']:,.2f}")
        print(f"  Total return:         ${summary['total_return_usd']:,.2f} "
              f"({summary['total_return_pct']:.4f}%)")
        print(f"  Open positions:       {len(summary['positions'])}")

    finally:
        db.close()

    ended = datetime.now(timezone.utc)
    elapsed = (ended - started).total_seconds()
    print(f"\n=== daily_close done in {elapsed:.1f}s ===")


if __name__ == "__main__":
    main()
