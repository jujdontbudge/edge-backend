from fastapi import APIRouter, Depends, HTTPException

from ..core.auth import get_current_user, get_user_entitlement
from ..models.schemas import EvaluateRequest, EvaluateResponse
from ..services.evaluation import (
    check_eval_limit,
    evaluate_answer,
    increment_eval_count,
)

router = APIRouter(prefix="/api", tags=["evaluate"])


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate(
    body: EvaluateRequest,
    user: dict = Depends(get_current_user),
    entitlement: str = Depends(get_user_entitlement),
):
    usage = check_eval_limit(user["id"], entitlement)
    if usage["remaining"] <= 0:
        raise HTTPException(
            status_code=429,
            detail=f"Daily evaluation limit reached ({usage['limit']}). Upgrade to Pro for more.",
        )

    increment_eval_count(user["id"])

    result = await evaluate_answer(
        question_id=body.question_id,
        user_answer=body.user_answer,
    )
    return result


@router.get("/evaluate/usage")
async def eval_usage(
    user: dict = Depends(get_current_user),
    entitlement: str = Depends(get_user_entitlement),
):
    return check_eval_limit(user["id"], entitlement)
