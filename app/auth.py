"""Passcode-only auth for a single-user hosted dashboard.

- Configure via `APP_PASSCODE` (required) and `APP_SECRET` (optional, used to
  sign the session cookie). If `APP_PASSCODE` is unset, auth is fully disabled
  (convenient for local dev).
- The session cookie stores an HMAC(passcode, secret) so it cannot be forged
  without knowing both. If either changes, all existing sessions invalidate
  automatically.
- 30-day sliding session, httpOnly + samesite=lax + secure over HTTPS.
"""
from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import Request

COOKIE_NAME = "equity_auth"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _secret() -> str:
    """Signing key for cookie. Falls back to a per-passcode-derived value so
    that even if APP_SECRET is unset the cookie still can't be forged without
    knowing the passcode."""
    return os.getenv("APP_SECRET") or f"__derived__:{os.getenv('APP_PASSCODE', '')}"


def _expected_cookie() -> str:
    passcode = os.getenv("APP_PASSCODE", "")
    if not passcode:
        return ""
    return hmac.new(_secret().encode(), passcode.encode(), hashlib.sha256).hexdigest()


def auth_enabled() -> bool:
    return bool(os.getenv("APP_PASSCODE"))


def verify_passcode(passcode: str) -> bool:
    expected = os.getenv("APP_PASSCODE", "")
    if not expected:
        return False
    return hmac.compare_digest(passcode, expected)


def is_authenticated(request: Request) -> bool:
    if not auth_enabled():
        return True  # local dev without APP_PASSCODE
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return False
    return hmac.compare_digest(cookie, _expected_cookie())
