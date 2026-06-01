from fastapi import APIRouter, Depends, HTTPException

from ..core.auth import get_current_user
from ..core.supabase import get_supabase

router = APIRouter(tags=["legal"])

PRIVACY_POLICY = {
    "title": "Edge Privacy Policy",
    "effective_date": "2026-05-01",
    "sections": [
        {
            "heading": "Data We Collect",
            "body": (
                "We collect information you provide directly: email address, display name, "
                "and interview preparation preferences. We also collect usage data such as "
                "question attempts, tutor chat messages, and daily study progress."
            ),
        },
        {
            "heading": "How We Use Your Data",
            "body": (
                "Your data is used to personalize your study experience, track your progress, "
                "power the AI tutor, and improve our question bank. We do not sell your "
                "personal information to third parties."
            ),
        },
        {
            "heading": "Third-Party Services",
            "body": (
                "We use Supabase for authentication and data storage, RevenueCat for "
                "subscription management, and OpenAI for AI tutor responses. Each service "
                "has its own privacy policy governing data they process on our behalf."
            ),
        },
        {
            "heading": "Data Retention",
            "body": (
                "We retain your data for as long as your account is active. You may request "
                "deletion of your account and all associated data at any time via the "
                "DELETE /api/account endpoint or through the app settings."
            ),
        },
        {
            "heading": "Contact",
            "body": "For privacy-related questions, contact us at privacy@edgeapp.io.",
        },
    ],
}

TERMS_OF_SERVICE = {
    "title": "Edge Terms of Service",
    "effective_date": "2026-05-01",
    "sections": [
        {
            "heading": "Acceptance of Terms",
            "body": (
                "By using Edge, you agree to these Terms of Service. If you do not agree, "
                "do not use the app."
            ),
        },
        {
            "heading": "Description of Service",
            "body": (
                "Edge is a quantitative interview preparation app that provides practice "
                "questions, spaced repetition drills, and an AI-powered tutor. Features "
                "may change without notice."
            ),
        },
        {
            "heading": "User Accounts",
            "body": (
                "You are responsible for maintaining the security of your account. You must "
                "not share your credentials or use another person's account."
            ),
        },
        {
            "heading": "Subscriptions and Payments",
            "body": (
                "Some features require a paid subscription managed through Apple's App Store. "
                "Refunds are handled according to Apple's refund policy."
            ),
        },
        {
            "heading": "Intellectual Property",
            "body": (
                "All questions, explanations, and content in Edge are proprietary. You may "
                "not reproduce, distribute, or create derivative works without permission."
            ),
        },
        {
            "heading": "Limitation of Liability",
            "body": (
                "Edge is provided 'as is' without warranty. We are not liable for any "
                "damages arising from use of the service, including but not limited to "
                "interview outcomes."
            ),
        },
        {
            "heading": "Contact",
            "body": "For questions about these terms, contact us at legal@edgeapp.io.",
        },
    ],
}


@router.get("/privacy-policy")
async def privacy_policy():
    return PRIVACY_POLICY


@router.get("/terms")
async def terms_of_service():
    return TERMS_OF_SERVICE


@router.delete("/api/account")
async def delete_account(user: dict = Depends(get_current_user)):
    db = get_supabase()
    user_id = user["id"]

    tables = ["tutor_messages", "attempts", "daily_sets", "profiles"]
    errors = []

    for table in tables:
        try:
            db.table(table).delete().eq("user_id" if table != "profiles" else "id", user_id).execute()
        except Exception as e:
            errors.append({"table": table, "error": str(e)})

    if errors:
        raise HTTPException(
            status_code=500,
            detail={"message": "Some data could not be deleted", "errors": errors},
        )

    return {"status": "deleted", "message": "All user data has been removed."}
