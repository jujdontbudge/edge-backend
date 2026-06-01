import hashlib
import json
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

import litellm

from ..core.config import settings


# --- Question registry (loaded once from questions.json) ---

_QUESTIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "questions.json"
_question_registry: dict[str, dict] = {}


def _load_question_registry() -> dict[str, dict]:
    """Load questions from JSON file into a dict keyed by question ID."""
    global _question_registry
    if _question_registry:
        return _question_registry
    with open(_QUESTIONS_FILE, "r") as f:
        questions = json.load(f)
    _question_registry = {q["id"]: q for q in questions}
    return _question_registry


def get_question_by_id(question_id: str) -> dict | None:
    """Look up a question by its ID. Returns None if not found."""
    registry = _load_question_registry()
    return registry.get(question_id)

EVAL_SYSTEM = """You evaluate student answers to quantitative finance interview questions. Be strict but fair.

Rules:
- Numeric equivalence: accept fractions, decimals, percentages, expressions. "1/3" = "0.333" = "33.3%". Require at least 2 significant figures for decimals.
- Mathematical expressions: "e^(-1)" ≈ 0.368, "√2" ≈ 1.414, "ln(2)" ≈ 0.693 are all valid.
- Conceptual answers: the student must capture the essential insight. Vague or partial is INCORRECT.
- If the student's value is mathematically equivalent to the expected answer, mark CORRECT.
- Minor rounding (e.g., 0.667 vs 2/3) is acceptable. Major rounding (e.g., 0.7 vs 2/3) is NOT.

Respond with ONLY this JSON, no markdown fences:
{"correct": true, "feedback": "one sentence"}
or
{"correct": false, "feedback": "one sentence explaining what's wrong"}"""


# --- Per-user daily rate limiting (in-memory, resets on restart) ---

_daily_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_last_reset_date: str = ""


def _maybe_reset_counts():
    global _daily_counts, _last_reset_date
    today = date.today().isoformat()
    if today != _last_reset_date:
        _daily_counts.clear()
        _last_reset_date = today


def check_eval_limit(user_id: str, entitlement: str) -> dict:
    _maybe_reset_counts()
    today = date.today().isoformat()
    limit = settings.eval_daily_limit_pro if entitlement == "pro" else settings.eval_daily_limit_free
    used = _daily_counts[today][user_id]
    return {"used_today": used, "limit": limit, "remaining": max(0, limit - used)}


def increment_eval_count(user_id: str):
    _maybe_reset_counts()
    today = date.today().isoformat()
    _daily_counts[today][user_id] += 1


# --- Response cache (bounded, keyed on question+answer) ---

_eval_cache: dict[str, tuple[dict, float]] = {}
_CACHE_MAX_SIZE = 10_000
_CACHE_TTL_SECONDS = 86400  # 24 hours


def _cache_key(question_prompt: str, user_answer: str) -> str:
    normalized = f"{question_prompt.strip()}|||{user_answer.strip().lower()}"
    return hashlib.sha256(normalized.encode()).hexdigest()


def _cache_get(key: str) -> dict | None:
    entry = _eval_cache.get(key)
    if entry is None:
        return None
    result, timestamp = entry
    if time.time() - timestamp > _CACHE_TTL_SECONDS:
        del _eval_cache[key]
        return None
    return result


def _cache_set(key: str, result: dict):
    if len(_eval_cache) >= _CACHE_MAX_SIZE:
        oldest_key = min(_eval_cache, key=lambda k: _eval_cache[k][1])
        del _eval_cache[oldest_key]
    _eval_cache[key] = (result, time.time())


# --- Core evaluation ---

def build_eval_prompt(
    question_prompt: str,
    correct_answer: str,
    solution_text: str,
    user_answer: str,
    find_expression: str = "",
) -> str:
    parts = [f"QUESTION: {question_prompt}"]
    if find_expression:
        parts.append(f"FIND: {find_expression}")
    parts.append(f"EXPECTED ANSWER: {correct_answer}")
    parts.append(f"SOLUTION:\n{solution_text}")
    parts.append(f'STUDENT WROTE: "{user_answer}"')
    return "\n\n".join(parts)


async def evaluate_answer(
    question_id: str,
    user_answer: str,
) -> dict:
    """Evaluate a user's answer by looking up the canonical question data server-side."""
    question = get_question_by_id(question_id)
    if question is None:
        return {"correct": False, "feedback": f"Unknown question ID: {question_id}"}

    # Build canonical answer and solution from the server-side registry
    solution_text = "\n".join(
        f"{step['id']}. {step['title']}: {step['math']}"
        for step in question.get("solution_steps", [])
    )

    numeric_answer = question.get("numeric_answer")
    if numeric_answer is not None:
        correct_answer = str(numeric_answer)
    else:
        correct_answer = solution_text

    find_expression = question.get("find_expression") or ""
    question_prompt = question["prompt"]

    key = _cache_key(question_prompt, user_answer)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    prompt = build_eval_prompt(
        question_prompt=question_prompt,
        correct_answer=correct_answer,
        solution_text=solution_text,
        user_answer=user_answer,
        find_expression=find_expression,
    )

    try:
        response = await litellm.acompletion(
            model=settings.eval_model,
            messages=[
                {"role": "system", "content": EVAL_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=150,
        )

        text = response.choices[0].message.content.strip()
        text = text.removeprefix("```json").removesuffix("```").strip()
        parsed = json.loads(text)
        result = {
            "correct": bool(parsed.get("correct", False)),
            "feedback": str(parsed.get("feedback", "")),
        }
        _cache_set(key, result)
        return result
    except (json.JSONDecodeError, KeyError, IndexError):
        return {"correct": False, "feedback": "Evaluation failed. Please try again."}
    except Exception:
        return {"correct": False, "feedback": "Evaluation service unavailable."}
