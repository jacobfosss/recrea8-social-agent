"""
Decides WHEN, within a day, educational content actually posts — not a
fixed hour. Starts fully random (since there's no data yet), and
automatically shifts toward whichever hour has historically performed best
once enough real engagement data has accumulated. Guarantees exactly one
post per day either way (never zero, never more than one).

How it works: the workflow checks in periodically throughout the day (see
post_schedule.yml) rather than firing once at one fixed hour. Each check
calls should_post_now() — early on, this is a random dice-roll weighted so
that by end of day it's virtually certain to have posted exactly once,
with the SPECIFIC hour randomized. Once MIN_SAMPLES real posts have scored
engagement data, it switches to preferring whichever hour scored best.

This is a genuinely self-contained module, since it doesn't yet know your
existing metrics_fetcher.py's exact structure — wire that file to call
update_engagement_score() once it has real numbers for a post_id, and
this starts learning automatically. It works correctly even before that
wiring, since the random phase doesn't depend on it.
"""
import json
import random
from datetime import datetime, timezone
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "post_timing.json"
MIN_SAMPLES = 10  # how many scored posts before trusting a "best hour" over randomness
BEST_HOUR_TOLERANCE = 1  # post if within this many hours of the best-performing hour


def _load():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text())
    return []


def _save(records):
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(records, indent=2))


def _today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def has_posted_today(pillar: str) -> bool:
    today = _today_str()
    return any(r["pillar"] == pillar and r["date"] == today for r in _load())


def record_scheduled_post(pillar: str, hour_utc: int, post_id: str = None):
    """Call this right after a successful post, so we know what hour it
    went out at — this is the raw data get_best_hour() later learns from."""
    records = _load()
    records.append({
        "pillar": pillar,
        "date": _today_str(),
        "hour_utc": hour_utc,
        "post_id": post_id,
        "engagement_score": None,  # filled in later once real metrics exist
    })
    _save(records)


def update_engagement_score(post_id: str, score: float):
    """Call this once real engagement data is available for a post (e.g.
    from metrics_fetcher.py ~24h after posting)."""
    records = _load()
    updated = False
    for r in records:
        if r.get("post_id") == post_id:
            r["engagement_score"] = score
            updated = True
    if updated:
        _save(records)
    return updated


def get_best_hour(pillar: str, min_samples: int = MIN_SAMPLES):
    """Returns the hour (0-23 UTC) with the highest average engagement
    score for this pillar, or None if there isn't enough scored data yet
    to trust a pattern over randomness."""
    records = [r for r in _load() if r["pillar"] == pillar and r.get("engagement_score") is not None]
    if len(records) < min_samples:
        return None

    hour_scores = {}
    for r in records:
        hour_scores.setdefault(r["hour_utc"], []).append(r["engagement_score"])

    best_hour = max(hour_scores, key=lambda h: sum(hour_scores[h]) / len(hour_scores[h]))
    return best_hour


def should_post_now(pillar: str, current_hour_utc: int, check_hours: list) -> bool:
    """check_hours: the full sorted list of hours the workflow checks in at
    today (e.g. [8,10,12,14,16,18,20,22]) — used both to compute
    random-phase probability and to know when it's the LAST chance today
    (safety fallback, so a day never passes with zero posts)."""
    if has_posted_today(pillar):
        return False

    best_hour = get_best_hour(pillar)

    if best_hour is not None:
        if abs(current_hour_utc - best_hour) <= BEST_HOUR_TOLERANCE:
            return True
        # safety fallback: if this is the last check of the day and we
        # still haven't posted (e.g. the best hour was already missed for
        # some reason), post anyway rather than skip the whole day
        if current_hour_utc == max(check_hours):
            return True
        return False

    # Random phase — no trustworthy data yet. Weight the probability so
    # that across the day's remaining checks, exactly one post happens on
    # average, with the specific hour genuinely randomized.
    remaining_checks = [h for h in check_hours if h >= current_hour_utc]
    if not remaining_checks:
        return False
    probability = 1.0 / len(remaining_checks)
    return random.random() < probability
