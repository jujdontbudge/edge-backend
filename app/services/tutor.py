from collections.abc import AsyncGenerator
from datetime import date

import litellm

from ..core.config import settings
from ..core.supabase import get_supabase

SYSTEM_PROMPT = """You are the Edge AI tutor — a sharp, concise math tutor for quant interview candidates.

You have the following context about the question the user just attempted:

QUESTION: {question_prompt}

CORRECT ANSWER: {correct_answer}

CANONICAL SOLUTION:
{solution_text}

USER'S ANSWER: {user_answer}
USER GOT IT: {is_correct}

Rules:
- Be Socratic first. Ask what they think before explaining.
- Use concrete examples (imagine 10,000 people, imagine 100 trials).
- Keep responses under 150 words unless the user asks for more detail.
- Use LaTeX notation for math: $inline$ and $$block$$.
- Never hallucinate math — the canonical solution above is the ground truth.
- If the user asks about something unrelated to the question, redirect gently."""

GENERIC_SYSTEM_PROMPT = """You are the Edge AI tutor — a sharp, concise math tutor for quant interview candidates.

Rules:
- Help with probability, expected value, combinatorics, statistics, game theory, discrete math, and quant interview prep.
- Be Socratic first when the user is solving a problem.
- Use concrete examples and short explanations.
- Keep responses under 150 words unless the user asks for more detail.
- Use LaTeX notation for math: $inline$ and $$block$$.
- If the user asks for a direct answer, explain the reasoning, not just the result."""


async def check_tutor_limit(user_id: str, entitlement: str) -> dict:
    limit = settings.tutor_daily_limit_pro if entitlement == "pro" else settings.tutor_daily_limit_free
    db = get_supabase()
    today = date.today().isoformat()

    resp = (
        db.table("tutor_messages")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .gte("created_at", f"{today}T00:00:00")
        .eq("role", "user")
        .execute()
    )

    used = resp.count or 0
    return {"used_today": used, "limit": limit, "remaining": max(0, limit - used)}


async def stream_tutor_response(
    user_id: str,
    question: dict | None,
    user_message: str,
    conversation_id: str,
    entitlement: str,
) -> AsyncGenerator[str, None]:
    model = settings.tutor_model_pro if entitlement == "pro" else settings.tutor_model_free

    db = get_supabase()

    history_resp = (
        db.table("tutor_messages")
        .select("role, content")
        .eq("conversation_id", conversation_id)
        .eq("user_id", user_id)
        .order("created_at")
        .limit(20)
        .execute()
    )

    if question:
        solution_text = "\n".join(
            f"{s['id']}. {s['title']}: {s['math']}" for s in question.get("solution_steps", [])
        )

        system = SYSTEM_PROMPT.format(
            question_prompt=question.get("prompt", ""),
            correct_answer=question.get("numeric_answer", "N/A"),
            solution_text=solution_text,
            user_answer="N/A",
            is_correct="Unknown",
        )
    else:
        system = GENERIC_SYSTEM_PROMPT

    messages = [{"role": "system", "content": system}]
    if history_resp.data:
        messages.extend(history_resp.data)
    if not history_resp.data or history_resp.data[-1].get("content") != user_message:
        messages.append({"role": "user", "content": user_message})

    full_response = ""

    response = await litellm.acompletion(
        model=model,
        messages=messages,
        stream=True,
        temperature=0.7,
        max_tokens=500,
    )

    async for chunk in response:
        delta = chunk.choices[0].delta.content
        if delta:
            full_response += delta
            yield f"data: {delta}\n\n"

    db.table("tutor_messages").insert({
        "user_id": user_id,
        "conversation_id": conversation_id,
        "role": "assistant",
        "content": full_response,
    }).execute()

    yield "data: [DONE]\n\n"
