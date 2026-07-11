"""
Pulls engagement metrics for previously-posted content and fills them into
data/post_history.json. Meant to run on a delay after posting (metrics need
time to accumulate) — see .github/workflows/metrics_pull.yml.
"""
import json
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "data" / "post_history.json"

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

MIN_AGE_SECONDS_BEFORE_PULL = 24 * 60 * 60  # give posts a day to accumulate engagement


def _load_history():
    if HISTORY_PATH.exists():
        return json.loads(HISTORY_PATH.read_text())
    return []


def _save_history(history):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2))


def _fetch_instagram_metrics(media_id: str) -> dict:
    token = os.environ["IG_ACCESS_TOKEN"]

    # Basic fields are always available, no extra scope needed.
    basic = requests.get(
        f"{GRAPH_BASE}/{media_id}",
        params={"fields": "like_count,comments_count,media_type", "access_token": token},
        timeout=30,
    ).json()

    metrics = {
        "likes": basic.get("like_count", 0),
        "comments": basic.get("comments_count", 0),
    }

    # Reach/saved/shares need the Insights endpoint and vary by media type.
    metric_names = "reach,saved,shares"
    insights = requests.get(
        f"{GRAPH_BASE}/{media_id}/insights",
        params={"metric": metric_names, "access_token": token},
        timeout=30,
    ).json()

    for entry in insights.get("data", []):
        values = entry.get("values", [])
        if values:
            metrics[entry["name"]] = values[-1].get("value", 0)

    return metrics


def _fetch_tiktok_metrics(publish_id: str) -> dict:
    """
    Only returns real data once your TikTok app is past Direct Post audit and
    the video is actually public (not sitting as an unconfirmed draft).
    Returns an empty dict otherwise — that's expected, not an error.
    """
    try:
        token_resp = requests.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            data={
                "client_key": os.environ["TIKTOK_CLIENT_KEY"],
                "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
                "grant_type": "refresh_token",
                "refresh_token": os.environ["TIKTOK_REFRESH_TOKEN"],
            },
            timeout=30,
        )
        token = token_resp.json().get("access_token")
        resp = requests.post(
            "https://open.tiktokapis.com/v2/video/query/",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "filters": {"video_ids": [publish_id]},
                "fields": ["like_count", "comment_count", "share_count", "view_count"],
            },
            timeout=30,
        )
        videos = resp.json().get("data", {}).get("videos", [])
        if not videos:
            return {}
        v = videos[0]
        return {
            "likes": v.get("like_count", 0),
            "comments": v.get("comment_count", 0),
            "shares": v.get("share_count", 0),
            "views": v.get("view_count", 0),
        }
    except Exception:
        return {}


def pull_pending_metrics():
    history = _load_history()
    now = time.time()
    updated = 0

    for record in history:
        if record.get("metrics"):
            continue  # already has metrics, don't re-pull
        if now - record["timestamp"] < MIN_AGE_SECONDS_BEFORE_PULL:
            continue  # too soon, give it more time

        try:
            if record["platform"] == "instagram":
                record["metrics"] = _fetch_instagram_metrics(record["post_id"])
            elif record["platform"] == "tiktok":
                metrics = _fetch_tiktok_metrics(record["post_id"])
                if metrics:
                    record["metrics"] = metrics
            updated += 1
        except Exception as e:
            print(f"[metrics] failed for {record['post_id']}: {e}")

    _save_history(history)
    print(f"[metrics] updated {updated} record(s)")


if __name__ == "__main__":
    pull_pending_metrics()
