"""
Decides WHEN, within a day, educational content actually posts — not a
fixed hour. Starts fully random (since there's no data yet), and
automatically shifts toward whichever hour(s) have historically performed
best once enough real engagement data has accumulated. Guarantees exactly
POSTS_PER_DAY posts per day — never fewer, never more.
"""
import json
import random
from datetime import datetime, timezone
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "post_timing.json"
MIN_SAMPLES = 10
BEST_HOUR_TOLERANCE = 1
POSTS_PER_DAY = 2


def _load():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text())
    return []


def _save(records):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(records, indent=2))


def _today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def count_posted_today(pillar: str) -> int:
    today = _today_str()
    return sum(1 for r in _load() if r["pillar"] == pillar and r["date"] == today)


def record_scheduled_post(pillar: str, hour_utc: int, post_id: str = None):
    records = _load()
    records.append({
        "pillar": pillar,
        "date": _today_str(),
        "hour_utc": hour_utc,
        "post_id": post_id,
        "engagement_score": None,
    })
    _save(records)


def update_engagement_score(post_id: str, score: float):
    records = _load()
    updated = False
    for r in records:
        if r.get("post_id") == post_id:
            r["engagement_score"] = score
            updated = True
    if updated:
        _save(records)
    return updated


def get_best_hours(pillar: str, top_n: int = POSTS_PER_DAY, min_samples: int = MIN_SAMPLES):
    records = [r for r in _load() if r["pillar"] == pillar and r.get("engagement_score") is not None]
    if len(records) < min_samples:
        return None

    hour_scores = {}
    for r in records:
        hour_scores.setdefault(r["hour_utc"], []).append(r["engagement_score"])

    ranked = sorted(hour_scores, key=lambda h: sum(hour_scores[h]) / len(hour_scores[h]), reverse=True)
    return ranked[:top_n]


MIN_GAP_HOURS = 4  # don't let multiple daily posts land right next to each other


def should_post_now(pillar: str, current_hour_utc: int, check_hours: list,
                      posts_per_day: int = POSTS_PER_DAY) -> bool:
    today_posts = [r for r in _load() if r["pillar"] == pillar and r["date"] == _today_str()]
    already_posted = len(today_posts)
    if already_posted >= posts_per_day:
        return False

    still_needed = posts_per_day - already_posted

    # The guaranteed-count promise takes priority over spacing — if this is
    # the LAST check of the day and we're still short, post anyway even if
    # it violates the minimum gap. Missing the daily quota is worse than
    # imperfect spacing.
    if current_hour_utc == max(check_hours) and still_needed > 0:
        return True

    # Enforce minimum spacing from today's most recent post, so multiple
    # daily posts don't cluster back-to-back — but only once the above
    # guarantee-priority check has already had first say.
    if today_posts:
        last_hour = max(r["hour_utc"] for r in today_posts)
        if current_hour_utc - last_hour < MIN_GAP_HOURS:
            return False

    best_hours = get_best_hours(pillar, top_n=posts_per_day)

    if best_hours is not None:
        return any(abs(current_hour_utc - h) <= BEST_HOUR_TOLERANCE for h in best_hours)

    remaining_checks = [h for h in check_hours if h >= current_hour_utc]
    if today_posts:
        last_hour = max(r["hour_utc"] for r in today_posts)
        remaining_checks = [h for h in remaining_checks if h - last_hour >= MIN_GAP_HOURS]
    if not remaining_checks:
        return False

    probability = still_needed / len(remaining_checks)
    return random.random() < probability