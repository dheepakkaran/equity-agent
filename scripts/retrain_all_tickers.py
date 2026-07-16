"""Retrain XGBoost models for all bootstrapped tickers with new settings.

Assumes:
    - uvicorn running on :8000
    - OHLCV already ingested for each ticker (from bootstrap_multi_ticker.py)

Prints per-ticker accuracy, confusion matrix, class balance, and the
predicted next-day direction so we can eyeball whether the DOWN bias is fixed.

Run:
    python scripts/retrain_all_tickers.py
"""
from __future__ import annotations

import sys

import httpx

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.tickers import TOP_TICKERS

BASE_URL = "http://localhost:8000"
TICKERS = TOP_TICKERS

TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def main() -> None:
    with httpx.Client(timeout=TIMEOUT) as client:
        try:
            client.get(f"{BASE_URL}/health").raise_for_status()
        except Exception as exc:
            print(f"ERROR: cannot reach {BASE_URL} — is uvicorn running?\n{exc}")
            sys.exit(1)

        print(
            f"{'Ticker':<8} {'Acc':>7} {'Prec':>7} {'Recall':>7} {'F1':>7} "
            f"{'Confusion':>18} {'Pred':>6} {'Conf':>7}"
        )
        print("-" * 90)

        results = []
        for ticker in TICKERS:
            try:
                r = client.post(f"{BASE_URL}/predict/{ticker}/train")
                r.raise_for_status()
                train = r.json()
            except Exception as exc:
                print(f"{ticker:<8}  TRAIN FAILED: {exc}")
                continue

            metrics = train.get("metrics", {})
            cm = train.get("confusion_matrix", [[0, 0], [0, 0]])
            cm_str = f"[[{cm[0][0]},{cm[0][1]}],[{cm[1][0]},{cm[1][1]}]]"

            try:
                r = client.get(f"{BASE_URL}/predict/{ticker}")
                r.raise_for_status()
                pred = r.json()
                direction = pred.get("direction", "?")
                confidence = pred.get("confidence", 0.0)
            except Exception:
                direction = "?"
                confidence = 0.0

            print(
                f"{ticker:<8} "
                f"{metrics.get('accuracy', 0):>7.2%} "
                f"{metrics.get('precision', 0):>7.2%} "
                f"{metrics.get('recall', 0):>7.2%} "
                f"{metrics.get('f1', 0):>7.2%} "
                f"{cm_str:>18} "
                f"{direction:>6} "
                f"{confidence:>7.2%}"
            )
            results.append({"ticker": ticker, "direction": direction, **metrics})

        if results:
            up_count = sum(1 for r in results if r["direction"] == "UP")
            down_count = sum(1 for r in results if r["direction"] == "DOWN")
            avg_acc = sum(r["accuracy"] for r in results) / len(results)
            print("-" * 90)
            print(
                f"Summary: {len(results)} models trained | "
                f"avg accuracy {avg_acc:.2%} | "
                f"predictions UP={up_count} DOWN={down_count}"
            )
            if down_count > 7 or up_count > 7:
                print("WARNING: predictions still heavily skewed — model may still be biased.")
            else:
                print("Direction split looks balanced — DOWN-bias appears fixed.")


if __name__ == "__main__":
    main()
