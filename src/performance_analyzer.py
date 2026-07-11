"""
Aggregates data/post_history.json into a short plain-language summary of what's
working, used to steer future caption/topic generation. Simple, transparent
stats-over-history — not a black box.
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "data" / "post_history.json"
INSIGHTS_PATH = ROOT / "data" / "performance_insights.json"

MIN_POSTS_FOR_A_PATTERN = 3  # don't draw conclusions from too little data


def _load_history():
    if HISTORY_PATH.exists():
        return json.loads(HISTORY_PATH.read_text())
    return []


def _engagement_score(metrics: dict) -> float:
    if not metrics:
        return 0.0
    return (
        metrics.get("likes", 0)
        + metrics.get("comments", 0) * 2      # comments weighted higher, more effort
        + metrics.get("shares", 0) * 3        # shares weighted highest, best growth signal
        + metrics.get("saved", 0) * 2
    )


def analyze():
    history = [r for r in _load_history() if r.get("metrics")]

    if len(history) < MIN_POSTS_FOR_A_PATTERN:
        summary = "Not enough posted-and-measured history yet to draw patterns."
        _write(summary, {})
        return summary

    by_topic = defaultdict(list)
    by_media_type = defaultdict(list)
    by_source = defaultdict(list)
    by_caption_length_bucket = defaultdict(list)

    for r in history:
        score = _engagement_score(r["metrics"])
        by_topic[r.get("topic", "unknown")].append(score)
        by_media_type[r.get("media_type", "unknown")].append(score)
        by_source[r.get("source", "unknown")].append(score)
        length = len(r.get("caption", "").split())
        bucket = "short (<30 words)" if length < 30 else "medium (30-60)" if length <= 60 else "long (60+)"
        by_caption_length_bucket[bucket].append(score)

    def avg(scores):
        return sum(scores) / len(scores) if scores else 0

    ranked_topics = sorted(by_topic.items(), key=lambda kv: avg(kv[1]), reverse=True)
    ranked_media = sorted(by_media_type.items(), key=lambda kv: avg(kv[1]), reverse=True)
    ranked_length = sorted(by_caption_length_bucket.items(), key=lambda kv: avg(kv[1]), reverse=True)

    lines = []
    if ranked_topics:
        best_topic, best_scores = ranked_topics[0]
        lines.append(f"Best-performing topic so far: '{best_topic}' "
                      f"(avg engagement score {avg(best_scores):.1f} over {len(best_scores)} posts).")
    if len(ranked_media) > 1:
        top_media, top_scores = ranked_media[0]
        lines.append(f"{top_media.capitalize()} posts are outperforming other media types "
                      f"(avg score {avg(top_scores):.1f}).")
    if ranked_length:
        best_len, len_scores = ranked_length[0]
        lines.append(f"Captions in the '{best_len}' range perform best.")

    summary = " ".join(lines) if lines else "No clear pattern yet."

    detail = {
        "topics": {k: avg(v) for k, v in ranked_topics},
        "media_types": {k: avg(v) for k, v in ranked_media},
        "caption_length_buckets": {k: avg(v) for k, v in ranked_length},
        "sample_size": len(history),
    }
    _write(summary, detail)
    return summary


def _write(summary, detail):
    INSIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    INSIGHTS_PATH.write_text(json.dumps({"summary": summary, "detail": detail}, indent=2))


def load_summary() -> str:
    if INSIGHTS_PATH.exists():
        return json.loads(INSIGHTS_PATH.read_text()).get("summary", "")
    return ""


if __name__ == "__main__":
    print(analyze())
