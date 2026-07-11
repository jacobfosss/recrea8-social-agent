"""Shared helper so both the direct-post path (main.py) and the
approval-queue path (approval_workflow.py) record posts identically —
keeping the performance-learning loop fed regardless of which path was used.
"""
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "data" / "post_history.json"


def record_post(platform, post_id, content):
    history = json.loads(HISTORY_PATH.read_text()) if HISTORY_PATH.exists() else []
    history.append({
        "post_id": post_id,
        "platform": platform,
        "timestamp": time.time(),
        "topic": content.get("topic", "unknown"),
        "media_type": content["media_type"],
        "source": content["source"],
        "caption": content["caption"],
        "metrics": None,
    })
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2))
