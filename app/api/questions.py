import uuid
from datetime import date
from math import ceil, exp
from random import random, shuffle

from fastapi import APIRouter, Depends, HTTPException

from ..core.auth import get_current_user
from ..core.supabase import get_supabase
from ..models.schemas import AttemptSubmit, AttemptResponse, DailySetResponse

router = APIRouter(prefix="/api/questions", tags=["questions"])


def _ratings_from_attempts(attempts: list[dict], questions_by_id: dict[str, dict]) -> dict[str, float]:
    ratings: dict[str, float] = {}
    uncertainty: dict[str, float] = {}
    consec_wrong: dict[str, int] = {}
    for attempt in sorted(attempts, key=lambda item: item.get("created_at") or ""):
        question = questions_by_id.get(attempt["question_id"])
        if not question:
            continue
        topic = question.get("topic") or "unknown"
        level = int(question.get("level") or 3)
        rating = ratings.get(topic, 2.5)
        current_uncertainty = uncertainty.get(topic, 1.0)
        expected = 1.0 / (1.0 + exp(-0.6 * (rating - level)))
        outcome = 1.0 if attempt.get("is_correct") else 0.0
        k_factor = min(0.8, max(0.2, 0.6 * current_uncertainty))
        rating = max(1.0, min(5.0, rating + k_factor * (outcome - expected)))
        if attempt.get("is_correct"):
            consec_wrong[topic] = 0
            if (attempt.get("solve_time_seconds") or 0) < 60:
                difficulty_scale = level / 5.0
                rating = min(5.0, rating + 0.01 + 0.015 * difficulty_scale)
            current_uncertainty = max(0.3, current_uncertainty * 0.95)
        else:
            consec_wrong[topic] = consec_wrong.get(topic, 0) + 1
            if (attempt.get("solve_time_seconds") or 0) > 120:
                rating = max(1.0, rating - 0.02)
            if consec_wrong[topic] >= 3:
                current_uncertainty = min(1.0, current_uncertainty + 0.1)
            else:
                current_uncertainty = max(0.3, current_uncertainty * 0.95)
        ratings[topic] = rating
        uncertainty[topic] = current_uncertainty
    return ratings


def _build_attempt_stats(attempts: list[dict], questions_by_id: dict[str, dict]) -> dict[str, dict]:
    """Build per-question attempt stats (accuracy, total attempts, last correct streak)."""
    stats: dict[str, dict] = {}
    for attempt in sorted(attempts, key=lambda a: a.get("created_at") or ""):
        qid = attempt["question_id"]
        if qid not in stats:
            stats[qid] = {"total": 0, "correct": 0, "streak": 0}
        s = stats[qid]
        s["total"] += 1
        if attempt.get("is_correct"):
            s["correct"] += 1
            s["streak"] += 1
        else:
            s["streak"] = 0
    return stats


def _compose_adaptive_daily_set(
    goal: int,
    questions: list[dict],
    attempts: list[dict],
    focus_topics: list[str] | None = None,
) -> list[dict]:
    if focus_topics:
        questions = [q for q in questions if q.get("topic") in focus_topics]
    if not questions:
        return []

    questions_by_id = {q["id"]: q for q in questions}
    ratings = _ratings_from_attempts(attempts, questions_by_id)
    attempted_ids = {a["question_id"] for a in attempts}
    attempt_stats = _build_attempt_stats(attempts, questions_by_id)

    topic_count = len({q.get("topic") or "unknown" for q in questions})
    max_per_topic = max(1, int(ceil(goal / max(topic_count, 2))) + 1)

    selected: list[dict] = []
    used_ids: set[str] = set()
    topic_counts: dict[str, int] = {}

    def try_add(candidates: list[dict], limit: int) -> None:
        for q in candidates:
            if len(selected) >= limit:
                break
            if q["id"] in used_ids:
                continue
            topic = q.get("topic") or "unknown"
            if topic_counts.get(topic, 0) >= max_per_topic:
                continue
            selected.append(q)
            used_ids.add(q["id"])
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

    # Phase 1: Weak spots (low accuracy questions) — 20% of goal
    weak_slots = int(ceil(goal * 0.2))
    weak_spots = [
        q for q in questions
        if q["id"] in attempt_stats
        and attempt_stats[q["id"]]["total"] >= 2
        and attempt_stats[q["id"]]["correct"] / attempt_stats[q["id"]]["total"] < 0.4
    ]
    shuffle(weak_spots)
    try_add(weak_spots, weak_slots)

    # Phase 2: Adaptive practice — fill remaining
    scored: list[tuple[float, dict]] = []
    for question in questions:
        if question["id"] in used_ids:
            continue
        topic = question.get("topic") or "unknown"
        rating = ratings.get(topic, 2.5)
        target_level = max(1, min(5, round(rating)))
        level = int(question.get("level") or 3)
        delta = level - target_level
        if delta == 0:
            level_score = 0.0
        elif delta == 1:
            level_score = 0.10
        elif delta == -1:
            level_score = 0.15
        elif delta == 2:
            level_score = 0.35
        elif delta == -2:
            level_score = 0.40
        elif delta > 2:
            level_score = 0.55 + (delta - 2) * 0.20
        else:
            level_score = 0.50 + (abs(delta) - 2) * 0.20

        unseen_bonus = -0.22 if question["id"] not in attempted_ids else 0.08
        s = attempt_stats.get(question["id"])
        fragile_bonus = -0.16 if s and s["total"] >= 2 and s["correct"] / s["total"] < 0.5 else 0
        weakness_bonus = (5.0 - rating) * -0.035
        scored.append((level_score + unseen_bonus + fragile_bonus + weakness_bonus + random() * 0.08, question))

    by_topic: dict[str, list[dict]] = {}
    for _, question in sorted(scored, key=lambda item: item[0]):
        by_topic.setdefault(question.get("topic") or "unknown", []).append(question)

    topic_order = sorted(
        by_topic.keys(),
        key=lambda topic: (ratings.get(topic, 2.5), topic),
    )
    positions = {topic: 0 for topic in topic_order}
    while len(selected) < goal:
        appended = False
        for topic in topic_order:
            index = positions[topic]
            bucket = by_topic.get(topic, [])
            if index >= len(bucket):
                continue
            candidate = bucket[index]
            positions[topic] += 1
            if candidate["id"] in used_ids:
                continue
            t = candidate.get("topic") or "unknown"
            if topic_counts.get(t, 0) >= max_per_topic:
                continue
            selected.append(candidate)
            used_ids.add(candidate["id"])
            topic_counts[t] = topic_counts.get(t, 0) + 1
            appended = True
            if len(selected) >= goal:
                break
        if not appended:
            break

    # Phase 3: Filler — unseen questions if still short
    if len(selected) < goal:
        filler = [q for q in questions if q["id"] not in used_ids and q["id"] not in attempted_ids]
        shuffle(filler)
        try_add(filler, goal)

    return selected[:goal]


@router.get("/daily", response_model=DailySetResponse)
async def get_daily_set(user: dict = Depends(get_current_user)):
    db = get_supabase()
    today = date.today().isoformat()

    existing = (
        db.table("daily_sets")
        .select("*")
        .eq("user_id", user["id"])
        .eq("date", today)
        .maybe_single()
        .execute()
    )

    if existing.data:
        question_ids = existing.data["question_ids"]
        questions = (
            db.table("questions")
            .select("*")
            .in_("id", question_ids)
            .execute()
        )
        return DailySetResponse(
            id=existing.data["id"],
            date=today,
            questions=questions.data,
        )

    profile = (
        db.table("profiles")
        .select("daily_goal, target_firms, focus_topics")
        .eq("id", user["id"])
        .maybe_single()
        .execute()
    )

    goal = profile.data["daily_goal"] if profile.data else 7
    focus_topics = profile.data.get("focus_topics") or [] if profile.data else []

    questions_response = (
        db.table("questions")
        .select("*")
        .execute()
    )
    all_questions = questions_response.data

    attempts = (
        db.table("attempts")
        .select("is_correct, question_id, solve_time_seconds, created_at")
        .eq("user_id", user["id"])
        .execute()
    )

    questions = _compose_adaptive_daily_set(goal, all_questions, attempts.data, focus_topics=focus_topics or None)
    question_ids = [q["id"] for q in questions]
    set_id = str(uuid.uuid4())

    db.table("daily_sets").insert({
        "id": set_id,
        "user_id": user["id"],
        "date": today,
        "question_ids": question_ids,
    }).execute()

    return DailySetResponse(id=set_id, date=today, questions=questions)


@router.post("/attempt", response_model=AttemptResponse)
async def submit_attempt(body: AttemptSubmit, user: dict = Depends(get_current_user)):
    db = get_supabase()

    question = (
        db.table("questions")
        .select("*")
        .eq("id", body.question_id)
        .maybe_single()
        .execute()
    )

    if not question.data:
        raise HTTPException(status_code=404, detail="Question not found")

    q = question.data

    is_correct = False
    if body.revealed:
        is_correct = False
    elif q["answer_type"] == "numeric":
        if body.numeric_answer is None:
            raise HTTPException(status_code=400, detail="Numeric answer required for this question")
        correct = q.get("numeric_answer")
        if correct is not None:
            if q.get("is_exact_integer"):
                is_correct = abs(body.numeric_answer - correct) < 0.001
            elif q.get("tolerance_absolute"):
                is_correct = abs(body.numeric_answer - correct) <= q["tolerance_absolute"]
            else:
                pct = q.get("tolerance_percent", 0.5)
                if correct == 0:
                    is_correct = abs(body.numeric_answer) < 0.001
                else:
                    is_correct = abs((body.numeric_answer - correct) / correct) * 100 <= pct
    elif q["answer_type"] == "self_graded":
        if not body.self_grade:
            raise HTTPException(status_code=400, detail="Self grade required for this question")
        is_correct = body.self_grade == "got_it"
    else:
        raise HTTPException(status_code=400, detail=f"Unknown answer type: {q['answer_type']}")

    attempt_id = str(uuid.uuid4())
    db.table("attempts").insert({
        "id": attempt_id,
        "user_id": user["id"],
        "question_id": body.question_id,
        "numeric_answer": body.numeric_answer,
        "self_grade": body.self_grade.value if body.self_grade else None,
        "submitted_answer": body.submitted_answer,
        "is_correct": is_correct,
        "solve_time_seconds": body.solve_time_seconds,
        "attempts_used": body.attempts_used,
        "attempt_limit": body.attempt_limit,
        "revealed": body.revealed,
    }).execute()

    return AttemptResponse(
        id=attempt_id,
        question_id=body.question_id,
        is_correct=is_correct,
        correct_answer=q.get("numeric_answer"),
        solve_time_seconds=body.solve_time_seconds,
        attempts_used=body.attempts_used,
        attempt_limit=body.attempt_limit,
        revealed=body.revealed,
        timestamp=date.today().isoformat(),
    )
