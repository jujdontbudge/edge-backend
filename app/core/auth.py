from fastapi import Depends, HTTPException, Request
from jose import jwt, JWTError
import httpx

from .config import settings


async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = auth[7:]
    try:
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        async with httpx.AsyncClient() as client:
            resp = await client.get(jwks_url)
            jwks = resp.json()

        payload = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience="authenticated",
        )
        return {
            "id": payload["sub"],
            "email": payload.get("email"),
            "role": payload.get("role", "authenticated"),
        }
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_user_entitlement(user: dict = Depends(get_current_user)) -> str:
    # TODO: check RevenueCat entitlement via webhook-synced column
    # For now, return "free" — will be "pro" when subscription active
    return "free"
