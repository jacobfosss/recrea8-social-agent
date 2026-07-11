"""
Replies to comments on YOUR OWN Instagram posts automatically. This is a
sanctioned use of the Graph API (the instagram_manage_comments permission
exists specifically for this) — distinct from commenting on other accounts'
posts, which this project does not and will not automate (see
engagement_assist.py for the human-in-the-loop alternative to that).
"""
import json
import os
from pathlib import Path

import requests
from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
REPLIED_LOG_PATH = ROOT / "data" / "replied_comments.json"

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
MODEL = "claude-sonnet-5"

# Very short/low-effort comments usually aren't worth an individual reply and
# are more likely to be spam — skip them rather than reply to everything.
MIN_COMMENT_LENGTH = 3


def _load_replied():
    if REPLIED_LOG_PATH.exists():
        return set(json.loads(REPLIED_LOG_PATH.read_text()))
    return set()


def _save_replied(replied_ids):
    REPLIED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPLIED_LOG_PATH.write_text(json.dumps(list(replied_ids), indent=2))


def _recent_media_ids(token, limit=10):
    ig_id = os.environ["IG_BUSINESS_ACCOUNT_ID"]
    resp = requests.get(
        f"{GRAPH_BASE}/{ig_id}/media",
        params={"fields": "id,timestamp", "limit": limit, "access_token": token},
        timeout=30,
    )
    resp.raise_for_status()
    return [m["id"] for m in resp.json().get("data", [])]


def _comments_for_media(token, media_id):
    resp = requests.get(
        f"{GRAPH_BASE}/{media_id}/comments",
        params={"fields": "id,text,username,timestamp", "access_token": token},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def _draft_reply(comment_text, brand_voice, brand_context):
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = f"""A follower left this comment on our Instagram post: "{comment_text}"

Brand voice: {brand_voice}
Brand context: {brand_context}

Write a short (under 20 words), warm, genuine reply. If it's a question,
answer it plainly. If it's just a compliment/emoji, respond briefly and
warmly — don't be generic or robotic. No hashtags, no emojis unless it fits
naturally. If the comment is spam, nonsensical, or clearly not worth a reply,
respond with exactly: SKIP
"""
    resp = client.messages.create(model=MODEL, max_tokens=100,
                                   messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    return None if text == "SKIP" else text


def _post_reply(token, comment_id, message):
    resp = requests.post(
        f"{GRAPH_BASE}/{comment_id}/replies",
        data={"message": message, "access_token": token},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def reply_to_new_comments(brand_voice="", brand_context="", media_limit=10):
    token = os.environ["IG_ACCESS_TOKEN"]
    replied = _load_replied()
    new_replies = 0

    for media_id in _recent_media_ids(token, media_limit):
        for comment in _comments_for_media(token, media_id):
            if comment["id"] in replied:
                continue
            if len(comment.get("text", "").strip()) < MIN_COMMENT_LENGTH:
                replied.add(comment["id"])  # mark seen so we don't re-check forever
                continue
            try:
                reply_text = _draft_reply(comment["text"], brand_voice, brand_context)
                if reply_text:
                    _post_reply(token, comment["id"], reply_text)
                    new_replies += 1
                    print(f"[comment-reply] replied to @{comment.get('username','?')}: {reply_text}")
                replied.add(comment["id"])
            except Exception as e:
                print(f"[comment-reply] failed on comment {comment['id']}: {e}")

    _save_replied(replied)
    print(f"[comment-reply] posted {new_replies} new repl{'y' if new_replies==1 else 'ies'}")


if __name__ == "__main__":
    import yaml
    config = yaml.safe_load(open(ROOT / "config.yaml"))
    reply_to_new_comments(
        brand_voice=config.get("brand_voice", ""),
        brand_context=config.get("brand_context", ""),
    )
