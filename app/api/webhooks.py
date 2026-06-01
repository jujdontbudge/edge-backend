from fastapi import APIRouter, Request, HTTPException, Header
from typing import Optional
import httpx
import os

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

REVENUECAT_WEBHOOK_SECRET = os.getenv("REVENUECAT_WEBHOOK_SECRET", "")
REVENUECAT_API_KEY = os.getenv("REVENUECAT_SECRET_KEY", "")


@router.post("/revenuecat")
async def revenuecat_webhook(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    if not REVENUECAT_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook not configured")

    if authorization != REVENUECAT_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    payload = await request.json()
    event = payload.get("event", {})
    app_user_id = event.get("app_user_id")

    if not app_user_id:
        return {"status": "no_user"}

    if not REVENUECAT_API_KEY:
        return {"status": "api_key_not_configured"}

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.revenuecat.com/v1/subscribers/{app_user_id}",
            headers={"Authorization": f"Bearer {REVENUECAT_API_KEY}"},
        )
        if resp.status_code == 200:
            subscriber = resp.json().get("subscriber", {})
            entitlements = subscriber.get("entitlements", {})
            pro = entitlements.get("pro", {})
            is_active = pro.get("expires_date") is not None

            # TODO: update user entitlement in Supabase
            # db = get_supabase()
            # db.table("profiles").update(
            #     {"entitlement": "pro" if is_active else "free"}
            # ).eq("id", app_user_id).execute()

    return {"status": "ok"}
