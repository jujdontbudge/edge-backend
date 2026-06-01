from fastapi import APIRouter, Depends

from ..core.auth import get_current_user, get_user_entitlement
from ..core.supabase import get_supabase
from ..models.schemas import UserProfile, OnboardingRequest

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=UserProfile)
async def get_profile(
    user: dict = Depends(get_current_user),
    entitlement: str = Depends(get_user_entitlement),
):
    db = get_supabase()
    profile = (
        db.table("profiles")
        .select("*")
        .eq("id", user["id"])
        .maybe_single()
        .execute()
    )

    if not profile.data:
        return UserProfile(
            id=user["id"],
            email=user.get("email"),
            entitlement=entitlement,
            created_at="",
        )

    p = profile.data
    return UserProfile(
        id=p["id"],
        email=p.get("email"),
        display_name=p.get("display_name"),
        daily_goal=p.get("daily_goal", 7),
        attempt_limit=p.get("attempt_limit", 3),
        target_firms=p.get("target_firms", []),
        interview_timeline=p.get("interview_timeline"),
        entitlement=entitlement,
        created_at=p.get("created_at", ""),
    )


@router.post("/onboarding")
async def complete_onboarding(
    body: OnboardingRequest,
    user: dict = Depends(get_current_user),
):
    db = get_supabase()
    db.table("profiles").upsert({
        "id": user["id"],
        "daily_goal": body.daily_goal,
        "attempt_limit": body.attempt_limit,
        "target_firms": body.target_firms,
        "interview_timeline": body.interview_timeline,
        "onboarding_complete": True,
    }).execute()

    return {"status": "ok"}
