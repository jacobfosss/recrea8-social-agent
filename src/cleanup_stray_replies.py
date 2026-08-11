"""
One-off cleanup tool: finds replies YOUR account posted within a specific
recent time window (to match when the comment_reply bot was mistakenly
active) on your recent Instagram posts, and deletes them.

Defaults to dry-run — shows what it WOULD delete without deleting anything.
Run with --delete once you've reviewed the dry-run output and are sure.

Usage:
    python3 -m src.cleanup_stray_replies --hours 6              # dry run, last 6 hours
    python3 -m src.cleanup_stray_replies --hours 6 --delete     # actually deletes
    python3 -m src.cleanup_stray_replies --minutes 90           # last 90 minutes instead
"""
import argparse
import os
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


def _get_own_username(token):
    ig_id = os.environ["IG_BUSINESS_ACCOUNT_ID"]
    resp = requests.get(
        f"{GRAPH_BASE}/{ig_id}",
        params={"fields": "username", "access_token": token},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("username")


def _recent_media_ids(token, limit=25):
    ig_id = os.environ["IG_BUSINESS_ACCOUNT_ID"]
    resp = requests.get(
        f"{GRAPH_BASE}/{ig_id}/media",
        params={"fields": "id,timestamp", "limit": limit, "access_token": token},
        timeout=30,
    )
    resp.raise_for_status()
    return [m["id"] for m in resp.json().get("data", [])]


def _top_level_comments(token, media_id):
    resp = requests.get(
        f"{GRAPH_BASE}/{media_id}/comments",
        params={"fields": "id,username,text", "access_token": token},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def _replies_for_comment(token, comment_id):
    resp = requests.get(
        f"{GRAPH_BASE}/{comment_id}/replies",
        params={"fields": "id,username,text,timestamp", "access_token": token},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def _delete_comment(token, comment_id):
    resp = requests.delete(
        f"{GRAPH_BASE}/{comment_id}",
        params={"access_token": token},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _parse_ig_timestamp(ts_str):
    # Instagram returns something like "2026-07-11T20:15:00+0000"
    return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S%z")


def find_and_clean_own_replies(cutoff, delete=False, media_limit=25):
    token = os.environ["IG_ACCESS_TOKEN"]
    own_username = _get_own_username(token)
    print(f"[cleanup] your account username: @{own_username}")
    print(f"[cleanup] only targeting replies posted after: {cutoff.isoformat()}")

    found = []
    for media_id in _recent_media_ids(token, media_limit):
        for comment in _top_level_comments(token, media_id):
            try:
                replies = _replies_for_comment(token, comment["id"])
            except Exception:
                continue
            for reply in replies:
                if reply.get("username") != own_username:
                    continue
                ts_raw = reply.get("timestamp")
                if not ts_raw:
                    continue
                try:
                    reply_time = _parse_ig_timestamp(ts_raw)
                except ValueError:
                    continue
                if reply_time >= cutoff:
                    found.append(reply)

    print(f"[cleanup] found {len(found)} of your own replies within the window:")
    for reply in found:
        print(f"  - id={reply['id']}  time={reply.get('timestamp')}  "
              f"text=\"{reply.get('text', '')[:80]}\"")

    if not delete:
        print("\n[cleanup] DRY RUN — nothing deleted. Re-run with --delete to actually remove these.")
        return

    deleted = 0
    for reply in found:
        try:
            _delete_comment(token, reply["id"])
            deleted += 1
            print(f"[cleanup] deleted {reply['id']}")
        except Exception as e:
            print(f"[cleanup] failed to delete {reply['id']}: {e}")

    print(f"[cleanup] done — deleted {deleted}/{len(found)}")


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true",
                         help="Actually delete found replies (default is dry-run)")
    parser.add_argument("--media-limit", type=int, default=25,
                         help="How many recent posts to check (default 25)")
    parser.add_argument("--hours", type=float, default=None,
                         help="Only target replies posted within the last N hours")
    parser.add_argument("--minutes", type=float, default=None,
                         help="Only target replies posted within the last N minutes")
    args = parser.parse_args()

    if args.minutes is not None:
        window = timedelta(minutes=args.minutes)
    elif args.hours is not None:
        window = timedelta(hours=args.hours)
    else:
        window = timedelta(hours=24)  # sensible default if neither is specified

    cutoff = datetime.now(timezone.utc) - window
    find_and_clean_own_replies(cutoff, delete=args.delete, media_limit=args.media_limit)
