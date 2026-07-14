"""Diagnostic for Gemini API access.

There is no public API to query remaining quota / balance for a Gemini free-tier
key — Google only exposes that in the AI Studio dashboard. This script does what
we CAN do:

    1. Confirms the key loads from .env
    2. Lists which models the key can call (proves it's active)
    3. Makes one small test generation on gemini-2.5-flash to prove it isn't
       rate-limited or expired right now
    4. Prints dashboard links you have to open manually for actual usage numbers

Run:
    python scripts/check_gemini_quota.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load .env from repo root regardless of where the script is invoked from
REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def _mask(key: str) -> str:
    if not key or len(key) < 10:
        return "(missing)"
    return key[:6] + "..." + key[-4:]


def list_models(client: httpx.Client, key: str) -> list[str]:
    r = client.get(f"{BASE_URL}/models", params={"key": key})
    r.raise_for_status()
    models = r.json().get("models", [])
    names = [m["name"].replace("models/", "") for m in models]
    return names


def test_generate(client: httpx.Client, key: str, model: str = "gemini-2.5-flash") -> dict:
    body = {
        "contents": [{"parts": [{"text": "Reply with the single word: pong"}]}],
        "generationConfig": {"maxOutputTokens": 5, "temperature": 0.0},
    }
    start = time.perf_counter()
    r = client.post(
        f"{BASE_URL}/models/{model}:generateContent",
        params={"key": key},
        json=body,
    )
    elapsed = time.perf_counter() - start

    out = {"status_code": r.status_code, "elapsed_s": round(elapsed, 2)}
    if r.status_code == 200:
        data = r.json()
        text = ""
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                text += part.get("text", "")
        out["text"] = text.strip()
        usage = data.get("usageMetadata") or {}
        out["prompt_tokens"] = usage.get("promptTokenCount")
        out["output_tokens"] = usage.get("candidatesTokenCount")
        out["total_tokens"] = usage.get("totalTokenCount")
    else:
        out["error"] = r.text[:400]
    return out


def main() -> None:
    key = os.getenv("GEMINI_API_KEY", "")
    print(f"GEMINI_API_KEY: {_mask(key)}")
    if not key:
        print("ERROR: GEMINI_API_KEY not set in .env")
        sys.exit(1)

    print()

    with httpx.Client(timeout=30.0) as client:
        # 1. List models
        try:
            names = list_models(client, key)
            print(f"Accessible models: {len(names)}")
            interesting = [n for n in names if "2.5" in n or "2.0" in n]
            for n in sorted(interesting):
                print(f"  - {n}")
        except httpx.HTTPStatusError as exc:
            print(f"ERROR listing models: {exc.response.status_code} — {exc.response.text[:200]}")
            sys.exit(1)

        print()

        # 2. Test generate
        print("Test call on gemini-2.5-flash ...")
        result = test_generate(client, key)
        print(f"  status:        {result['status_code']}")
        print(f"  elapsed:       {result['elapsed_s']}s")
        if result["status_code"] == 200:
            print(f"  response text: {result['text']!r}")
            print(f"  prompt tokens: {result.get('prompt_tokens')}")
            print(f"  output tokens: {result.get('output_tokens')}")
            print(f"  total tokens:  {result.get('total_tokens')}")
            print()
            print("Key is ACTIVE and not rate-limited right now.")
        elif result["status_code"] == 429:
            print("  RATE-LIMITED. Free tier: 15 req/min, 1500 req/day (varies by model).")
            print(f"  detail: {result.get('error')}")
        else:
            print(f"  ERROR: {result.get('error')}")

    print()
    print("For actual usage / remaining quota, open these dashboards manually:")
    print("  AI Studio:      https://aistudio.google.com/app/apikey")
    print("  Cloud Console:  https://console.cloud.google.com/apis/dashboard")
    print("  Quotas page:    https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas")


if __name__ == "__main__":
    main()
