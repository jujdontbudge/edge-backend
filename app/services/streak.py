from datetime import date, timedelta

from ..core.supabase import get_supabase


def calculate_streak(user_id: str) -> dict:
    db = get_supabase()

    resp = (
        db.table("attempts")
        .select("created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )

    if not resp.data:
        return {"current": 0, "longest": 0, "total_solved": 0, "freezes_remaining": 2, "last_active_date": None}

    active_dates = set(row["created_at"][:10] for row in resp.data)

    freeze_resp = (
        db.table("streak_freezes")
        .select("freeze_date")
        .eq("user_id", user_id)
        .gte("freeze_date", date.today().replace(day=1).isoformat())
        .execute()
    )
    freeze_dates = set(row["freeze_date"] for row in (freeze_resp.data or []))
    freezes_used = len(freeze_dates)
    freezes_remaining = max(0, 2 - freezes_used)

    covered_dates = active_dates | freeze_dates

    current = 0
    check_date = date.today()
    for _ in range(365):
        ds = check_date.isoformat()
        if ds in covered_dates:
            current += 1
            check_date -= timedelta(days=1)
        else:
            break

    all_dates = sorted(covered_dates)
    longest = current
    run = 0
    prev = None
    for ds in all_dates:
        d = date.fromisoformat(ds)
        if prev and (d - prev).days == 1:
            run += 1
        else:
            run = 1
        longest = max(longest, run)
        prev = d

    sorted_active = sorted(active_dates, reverse=True)
    return {
        "current": current,
        "longest": longest,
        "total_solved": len(resp.data),
        "freezes_remaining": freezes_remaining,
        "last_active_date": sorted_active[0] if sorted_active else None,
    }
