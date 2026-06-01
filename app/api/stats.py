from datetime import date, timedelta
from math import exp

from fastapi import APIRouter, Depends

from ..core.auth import get_current_user
from ..core.supabase import get_supabase
from ..models.schemas import StatsResponse, StreakResponse
from ..services.streak import calculate_streak

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _score_for_rating(rating: float) -> int:
    return round(max(1.0, min(5.0, rating)) * 200)


def _topic_scores(attempts: list[dict], questions_by_id: dict[str, dict]) -> list[dict]:
    topics = sorted({q.get("topic", "unknown") for q in questions_by_id.values() if q.get("topic")})
    topics.extend(sorted({a.get("topic", "unknown") for a in attempts if a.get("topic") and a.get("topic") not in topics}))
    if not topics:
        topics = ["probability", "expected_value", "combinatorics", "statistics", "game_theory", "discrete_math"]

    attempts_by_topic: dict[str, list[dict]] = {topic: [] for topic in topics}
    for attempt in sorted(attempts, key=lambda item: item.get("created_at") or ""):
        question = questions_by_id.get(attempt["question_id"], {})
        topic = question.get("topic") or attempt.get("topic") or "unknown"
        attempts_by_topic.setdefault(topic, []).append(attempt)

    scores = []
    for topic in sorted(attempts_by_topic.keys()):
        rating = 2.5
        uncertainty = 1.0
        topic_attempts = attempts_by_topic[topic]
        total_level = 0
        consec_wrong = 0
        for attempt in topic_attempts:
            question = questions_by_id.get(attempt["question_id"], {})
            level = int(question.get("level") or 3)
            total_level += level
            expected = 1.0 / (1.0 + exp(-0.6 * (rating - level)))
            outcome = 1.0 if attempt.get("is_correct") else 0.0
            k_factor = min(0.8, max(0.2, 0.6 * uncertainty))
            rating = max(1.0, min(5.0, rating + k_factor * (outcome - expected)))
            if attempt.get("is_correct"):
                consec_wrong = 0
                if (attempt.get("solve_time_seconds") or 0) < 60:
                    difficulty_scale = level / 5.0
                    rating = min(5.0, rating + 0.01 + 0.015 * difficulty_scale)
                uncertainty = max(0.3, uncertainty * 0.95)
            else:
                consec_wrong += 1
                if (attempt.get("solve_time_seconds") or 0) > 120:
                    rating = max(1.0, rating - 0.02)
                if consec_wrong >= 3:
                    uncertainty = min(1.0, uncertainty + 0.1)
                else:
                    uncertainty = max(0.3, uncertainty * 0.95)

        correct = sum(1 for a in topic_attempts if a.get("is_correct"))
        attempted = len(topic_attempts)
        avg_level = round(total_level / attempted, 2) if attempted else 0
        scores.append({
            "topic": topic,
            "score": _score_for_rating(rating),
            "rating": round(rating, 3),
            "level_band": max(1, min(5, round(rating))),
            "attempted": attempted,
            "accuracy": round(correct / attempted * 100, 1) if attempted else 0,
            "avg_level": avg_level,
        })
    return scores


@router.get("", response_model=StatsResponse)
async def get_stats(user: dict = Depends(get_current_user)):
    db = get_supabase()
    streak = calculate_streak(user["id"])

    all_attempts = (
        db.table("attempts")
        .select("is_correct, question_id, solve_time_seconds, attempts_used, revealed, created_at")
        .eq("user_id", user["id"])
        .execute()
    )

    thirty_days_ago = (date.today() - timedelta(days=30)).isoformat()
    seven_days_ago = (date.today() - timedelta(days=7)).isoformat()
    previous_seven_days_ago = (date.today() - timedelta(days=14)).isoformat()
    recent = [a for a in all_attempts.data if a["created_at"][:10] >= thirty_days_ago]
    recent_7d = [a for a in all_attempts.data if a["created_at"][:10] >= seven_days_ago]
    previous_7d = [
        a for a in all_attempts.data
        if previous_seven_days_ago <= a["created_at"][:10] < seven_days_ago
    ]

    accuracy_all = (
        sum(1 for a in all_attempts.data if a["is_correct"]) / len(all_attempts.data)
        if all_attempts.data else 0
    )
    accuracy_30d = (
        sum(1 for a in recent if a["is_correct"]) / len(recent)
        if recent else 0
    )
    accuracy_7d = (
        sum(1 for a in recent_7d if a["is_correct"]) / len(recent_7d)
        if recent_7d else 0
    )
    previous_accuracy_7d = (
        sum(1 for a in previous_7d if a["is_correct"]) / len(previous_7d)
        if previous_7d else 0
    )
    avg_attempts_30d = (
        sum(a.get("attempts_used") or 1 for a in recent) / len(recent)
        if recent else 0
    )
    avg_attempts_7d = (
        sum(a.get("attempts_used") or 1 for a in recent_7d) / len(recent_7d)
        if recent_7d else 0
    )
    reveal_rate_30d = (
        sum(1 for a in recent if a.get("revealed")) / len(recent)
        if recent else 0
    )
    reveal_rate_7d = (
        sum(1 for a in recent_7d if a.get("revealed")) / len(recent_7d)
        if recent_7d else 0
    )

    question_ids = list(set(a["question_id"] for a in all_attempts.data))
    if question_ids:
        questions = (
            db.table("questions")
            .select("id, topic, level")
            .in_("id", question_ids)
            .execute()
        )
        topic_map = {q["id"]: q["topic"] for q in questions.data}
        questions_by_id = {q["id"]: q for q in questions.data}
    else:
        topic_map = {}
        questions_by_id = {}

    by_topic: dict[str, dict] = {}
    for a in all_attempts.data:
        topic = topic_map.get(a["question_id"], "unknown")
        if topic not in by_topic:
            by_topic[topic] = {"attempted": 0, "correct": 0, "avg_attempts": 0}
        by_topic[topic]["attempted"] += 1
        by_topic[topic]["avg_attempts"] += a.get("attempts_used") or 1
        if a["is_correct"]:
            by_topic[topic]["correct"] += 1

    for t_data in by_topic.values():
        t_data["accuracy"] = round(t_data["correct"] / t_data["attempted"] * 100) if t_data["attempted"] else 0
        t_data["avg_attempts"] = round(t_data["avg_attempts"] / t_data["attempted"], 2) if t_data["attempted"] else 0

    topic_scores = _topic_scores(all_attempts.data, questions_by_id)
    topic_scores_by_name = {item["topic"]: item for item in topic_scores}
    for topic, metrics in by_topic.items():
        if topic in topic_scores_by_name:
            metrics["score"] = topic_scores_by_name[topic]["score"]
            metrics["avg_level"] = topic_scores_by_name[topic]["avg_level"]

    scored_topics = [item for item in topic_scores if item["attempted"] > 0]
    if not scored_topics:
        scored_topics = topic_scores
    weak_spots = sorted(scored_topics, key=lambda item: (item["score"], -item["attempted"]))[:4]
    best_spots = sorted(scored_topics, key=lambda item: (-item["score"], -item["attempted"]))[:4]
    attempted_topics = [item for item in topic_scores if item["attempted"] > 0]
    overall_score = round(
        sum(item["score"] * (0.3 + min(1.0, item["attempted"] / 8)) for item in attempted_topics)
        / max(0.1, sum(0.3 + min(1.0, item["attempted"] / 8) for item in attempted_topics))
    ) if attempted_topics else 500

    trend_7d = []
    today = date.today()
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        key = day.isoformat()
        day_attempts = [a for a in all_attempts.data if a["created_at"][:10] == key]
        accuracy = (
            sum(1 for a in day_attempts if a["is_correct"]) / len(day_attempts) * 100
            if day_attempts else 0
        )
        trend_7d.append({
            "date": key,
            "attempts": len(day_attempts),
            "accuracy": round(accuracy, 1),
        })

    return StatsResponse(
        streak=StreakResponse(**streak),
        accuracy_30d=round(accuracy_30d * 100, 1),
        accuracy_7d=round(accuracy_7d * 100, 1),
        accuracy_delta_7d=round((accuracy_7d - previous_accuracy_7d) * 100, 1),
        accuracy_all=round(accuracy_all * 100, 1),
        avg_attempts_30d=round(avg_attempts_30d, 2),
        avg_attempts_7d=round(avg_attempts_7d, 2),
        reveal_rate_30d=round(reveal_rate_30d * 100, 1),
        reveal_rate_7d=round(reveal_rate_7d * 100, 1),
        trend_7d=trend_7d,
        weak_spots=weak_spots,
        best_spots=best_spots,
        topic_scores=topic_scores,
        overall_score=overall_score,
        by_topic=by_topic,
        total_attempted=len(all_attempts.data),
    )
