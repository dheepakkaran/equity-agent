from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.auth import COOKIE_NAME, SESSION_MAX_AGE, _expected_cookie, verify_passcode

router = APIRouter()


class LoginRequest(BaseModel):
    passcode: str = Field(..., min_length=1, max_length=200)


@router.post("/login")
async def login(payload: LoginRequest, response: Response):
    if not verify_passcode(payload.passcode):
        raise HTTPException(status_code=401, detail="Wrong passcode")
    response.set_cookie(
        key=COOKIE_NAME,
        value=_expected_cookie(),
        httponly=True,
        secure=True,      # Render serves HTTPS; browser stays lenient over http://localhost
        samesite="lax",
        max_age=SESSION_MAX_AGE,
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}
