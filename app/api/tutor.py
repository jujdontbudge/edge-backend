import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from ..core.auth import get_current_user, get_user_entitlement
from ..core.supabase import get_supabase
from ..models.schemas import (
    TutorConversationMessagesResponse,
    TutorConversationSummary,
    TutorConversationUpdate,
    TutorMessageRequest,
    TutorMessageResponse,
    TutorUsageResponse,
)
from ..services.tutor import check_tutor_limit, stream_tutor_response

router = APIRouter(prefix="/api/tutor", tags=["tutor"])


@router.get("/usage", response_model=TutorUsageResponse)
async def get_usage(
    user: dict = Depends(get_current_user),
    entitlement: str = Depends(get_user_entitlement),
):
    return await check_tutor_limit(user["id"], entitlement)


@router.get("/conversations", response_model=list[TutorConversationSummary])
async def list_conversations(user: dict = Depends(get_current_user)):
    db = get_supabase()
    metadata = _conversation_metadata(db, user["id"])
    resp = (
        db.table("tutor_messages")
        .select("conversation_id, role, content, created_at")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )

    conversations: dict[str, dict] = {}
    for row in resp.data or []:
        conversation_id = str(row["conversation_id"])
        meta = metadata.get(conversation_id, {})
        if conversation_id not in conversations:
            title = meta.get("title") or "Tutor chat"
            conversations[conversation_id] = {
                "conversation_id": conversation_id,
                "title": title,
                "title_source": meta.get("title_source"),
                "last_message": row.get("content", ""),
                "updated_at": meta.get("updated_at") or row.get("created_at", ""),
                "message_count": 0,
            }

        conversations[conversation_id]["message_count"] += 1
        if row.get("role") == "user" and _should_auto_title(conversations[conversation_id]):
            conversations[conversation_id]["title"] = _conversation_title(row.get("content", ""))

    for conversation in conversations.values():
        conversation.pop("title_source", None)

    return list(conversations.values())


@router.get("/conversations/{conversation_id}", response_model=TutorConversationMessagesResponse)
async def get_conversation(
    conversation_id: str,
    user: dict = Depends(get_current_user),
):
    db = get_supabase()
    metadata = _conversation_metadata(db, user["id"]).get(conversation_id, {})
    resp = (
        db.table("tutor_messages")
        .select("id, conversation_id, role, content, created_at")
        .eq("user_id", user["id"])
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
    )

    messages = [
        TutorMessageResponse(
            id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
        )
        for row in resp.data or []
    ]
    return TutorConversationMessagesResponse(
        conversation_id=conversation_id,
        title=metadata.get("title") or _title_from_messages(resp.data or []),
        messages=messages,
    )


@router.patch("/conversations/{conversation_id}", response_model=TutorConversationSummary)
async def rename_conversation(
    conversation_id: str,
    body: TutorConversationUpdate,
    user: dict = Depends(get_current_user),
):
    db = get_supabase()
    title = _clean_manual_title(body.title)
    messages_resp = (
        db.table("tutor_messages")
        .select("role, content, created_at")
        .eq("user_id", user["id"])
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    messages = messages_resp.data or []
    if not messages and conversation_id not in _conversation_metadata(db, user["id"]):
        raise HTTPException(status_code=404, detail="Conversation not found")

    _upsert_conversation_title(
        db=db,
        user_id=user["id"],
        conversation_id=conversation_id,
        title=title,
        source="manual",
    )

    last_message = messages[0].get("content", "") if messages else ""
    updated_at = _now_iso()
    return TutorConversationSummary(
        conversation_id=conversation_id,
        title=title,
        last_message=last_message,
        updated_at=updated_at,
        message_count=len(messages),
    )


@router.post("/stream")
async def stream_message(
    body: TutorMessageRequest,
    user: dict = Depends(get_current_user),
    entitlement: str = Depends(get_user_entitlement),
):
    db = get_supabase()
    conversation_id = body.conversation_id or str(uuid.uuid4())

    # Check limit BEFORE inserting the message
    usage = await check_tutor_limit(user["id"], entitlement)
    if usage["remaining"] <= 0:
        raise HTTPException(
            status_code=429,
            detail=f"Daily tutor limit reached ({usage['limit']} messages). Upgrade to Pro for more.",
        )

    # Insert message only after confirming limit hasn't been reached
    db.table("tutor_messages").insert({
        "user_id": user["id"],
        "conversation_id": conversation_id,
        "role": "user",
        "content": body.message,
    }).execute()

    question = None
    if body.question_id:
        question_resp = (
            db.table("questions")
            .select("*")
            .eq("id", body.question_id)
            .maybe_single()
            .execute()
        )

        if not question_resp.data:
            raise HTTPException(status_code=404, detail="Question not found")
        question = question_resp.data

    _ensure_conversation_metadata(
        db=db,
        user_id=user["id"],
        conversation_id=conversation_id,
        auto_title=_conversation_title(body.message, question),
    )

    return EventSourceResponse(
        stream_tutor_response(
            user_id=user["id"],
            question=question,
            user_message=body.message,
            conversation_id=conversation_id,
            entitlement=entitlement,
        )
    )


def _conversation_metadata(db, user_id: str) -> dict[str, dict]:
    try:
        resp = (
            db.table("tutor_conversations")
            .select("id, title, title_source, updated_at")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .limit(500)
            .execute()
        )
    except Exception:
        return {}
    return {str(row["id"]): row for row in resp.data or []}


def _ensure_conversation_metadata(db, user_id: str, conversation_id: str, auto_title: str) -> None:
    metadata = _conversation_metadata(db, user_id).get(conversation_id)
    if metadata and metadata.get("title_source") == "manual":
        _touch_conversation(db, user_id, conversation_id)
        return

    try:
        _upsert_conversation_title(
            db=db,
            user_id=user_id,
            conversation_id=conversation_id,
            title=auto_title,
            source="auto",
        )
    except Exception:
        pass


def _upsert_conversation_title(db, user_id: str, conversation_id: str, title: str, source: str) -> None:
    now = _now_iso()
    metadata = _conversation_metadata(db, user_id).get(conversation_id)
    if metadata:
        (
            db.table("tutor_conversations")
            .update({"title": title, "title_source": source, "updated_at": now})
            .eq("id", conversation_id)
            .eq("user_id", user_id)
            .execute()
        )
        return

    db.table("tutor_conversations").insert({
        "id": conversation_id,
        "user_id": user_id,
        "title": title,
        "title_source": source,
        "updated_at": now,
    }).execute()


def _touch_conversation(db, user_id: str, conversation_id: str) -> None:
    try:
        (
            db.table("tutor_conversations")
            .update({"updated_at": _now_iso()})
            .eq("id", conversation_id)
            .eq("user_id", user_id)
            .execute()
        )
    except Exception:
        pass


def _clean_manual_title(title: str) -> str:
    cleaned = " ".join(title.strip().split())
    if not cleaned:
        raise HTTPException(status_code=422, detail="Title cannot be empty")
    return cleaned[:80]


def _title_from_messages(messages: list[dict]) -> str:
    for row in messages:
        if row.get("role") == "user":
            return _conversation_title(row.get("content", ""))
    return "Tutor chat"


def _conversation_title(content: str, question: dict | None = None) -> str:
    source = question.get("prompt", "") if question else content
    cleaned = " ".join(source.strip().split())
    if not cleaned:
        return "Tutor chat"

    lowered = cleaned.lower()
    if _is_generic_title(lowered):
        return "Tutor Chat"
    if "monty hall" in lowered:
        return "Monty Hall Strategy"
    if "dice" in lowered or "die" in lowered:
        return "Dice Probability"
    if "coin" in lowered or "flip" in lowered or "heads" in lowered or "tails" in lowered:
        return "Coin Flip Probability"
    if "card" in lowered or "deck" in lowered:
        return "Card Probability"
    if "expected value" in lowered or lowered.startswith("ev ") or "e[" in lowered:
        return "Expected Value Setup"
    if "bayes" in lowered or "test positive" in lowered:
        return "Bayes Probability"
    if "missing number" in lowered:
        return "Missing Number Puzzle"
    if "semicircle" in lowered or "circle" in lowered:
        return "Circle Probability"

    topic_words = {
        "probability": "Probability",
        "combinatorics": "Combinatorics",
        "statistics": "Statistics",
        "discrete math": "Discrete Math",
        "market sizing": "Market Sizing",
        "game theory": "Game Theory",
    }
    for key, label in topic_words.items():
        if key in lowered:
            return f"{label} Help" if len(label.split()) == 1 else label

    without_starter = re.sub(
        r"^(can you|could you|please|help me|explain|show me|tell me|how do i|how can i|what is|what's|solve)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip(" :-?.")
    words = re.findall(r"[A-Za-z0-9]+", without_starter)
    stopwords = {
        "the", "a", "an", "and", "or", "to", "of", "for", "with", "in", "on", "at",
        "this", "that", "these", "those", "is", "are", "be", "about", "problem",
        "question", "answer", "help", "me", "my", "i", "outgoing", "incoming",
        "message", "chat",
    }
    keywords = [word for word in words if word.lower() not in stopwords]
    title_words = keywords[:5] if keywords else words[:5]
    title = " ".join(word.capitalize() for word in title_words)
    if not title:
        title = "Tutor Chat"
    return title if len(title) <= 58 else f"{title[:55]}..."


def _should_auto_title(conversation: dict) -> bool:
    if conversation.get("title_source") == "manual":
        return False
    return _is_generic_title(str(conversation.get("title", "")))


def _is_generic_title(title: str) -> bool:
    cleaned = title.strip().lower()
    if "outgoing" in cleaned or "incoming" in cleaned:
        return True
    return cleaned in {
        "",
        "outgoing",
        "incoming",
        "user",
        "assistant",
        "message",
        "new chat",
        "tutor chat",
        "chat",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
