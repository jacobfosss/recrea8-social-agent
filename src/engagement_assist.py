"""
Genuine-engagement assist tool. Uses Instagram Graph API's Business Discovery
endpoint (a sanctioned, official way to view public business/creator
accounts' recent posts and stats — built for exactly this kind of audience
research, not scraping) to surface recent posts from accounts you name, and
has Claude draft a thoughtful suggested comment for each.

Deliberately NOT automated past this point: it writes a digest for a human to
read and manually act on. Auto-posting comments on other people's content is
against platform policy regardless of how good the draft is — see
comment_reply.py's docstring for the sanctioned alternative (replying to
comments on your OWN posts).
"""
import os
from datetime import datetime
from pathlib import Path

import requests
from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
DIGEST_PATH = ROOT / "data" / "engagement_digest.md"

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
MODEL = "claude-sonnet-5"


def _fetch_recent_posts(target_username, limit=3):
    token = os.environ["IG_ACCESS_TOKEN"]
    own_ig_id = os.environ["IG_BUSINESS_ACCOUNT_ID"]

    fields = (
        f"business_discovery.username({target_username})"
        f"{{media.limit({limit}){{caption,like_count,comments_count,permalink,timestamp}}}}"
    )
    resp = requests.get(
        f"{GRAPH_BASE}/{own_ig_id}",
        params={"fields": fields, "access_token": token},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("business_discovery", {}).get("media", {}).get("data", [])


def _draft_comment(post_caption, brand_voice, brand_context):
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    prompt = f"""Draft a genuine, specific Instagram comment to leave on this post
(as our brand engaging authentically with the community — not
self-promotional, no mention of our own product/brand name, just add real
value or perspective).

Our brand voice: {brand_voice}
Our brand context (for tone only, don't reference directly): {brand_context}

Post caption: "{post_caption}"

One short comment, under 20 words, specific to this post (not generic
"love this!"). No emojis unless they fit naturally, no hashtags.
"""
    resp = client.messages.create(model=MODEL, max_tokens=100,
                                   messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def build_digest(target_accounts, brand_voice="", brand_context="", posts_per_account=3):
    lines = [f"# Engagement digest — {datetime.now().strftime('%Y-%m-%d')}", "",
             "Suggested comments for you to review and post yourself — nothing here "
             "is posted automatically.", ""]

    for username in target_accounts:
        lines.append(f"## @{username}")
        try:
            posts = _fetch_recent_posts(username, posts_per_account)
            if not posts:
                lines.append("_No recent posts found (account may not be a Business/Creator account)._\n")
                continue
            for post in posts:
                caption = (post.get("caption") or "")[:200]
                suggested = _draft_comment(caption, brand_voice, brand_context)
                lines.append(f"- **Post:** {post.get('permalink', 'n/a')}")
                lines.append(f"  - Caption snippet: _{caption[:100]}..._")
                lines.append(f"  - Suggested comment: \"{suggested}\"")
            lines.append("")
        except Exception as e:
            lines.append(f"_Failed to fetch: {e}_\n")

    DIGEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIGEST_PATH.write_text("\n".join(lines))
    print(f"[engagement-assist] wrote digest to {DIGEST_PATH}")


if __name__ == "__main__":
    import yaml
    config = yaml.safe_load(open(ROOT / "config.yaml"))
    engagement_cfg = config.get("engagement", {})
    build_digest(
        target_accounts=engagement_cfg.get("accounts_to_monitor", []),
        brand_voice=config.get("brand_voice", ""),
        brand_context=config.get("brand_context", ""),
        posts_per_account=engagement_cfg.get("posts_per_account", 3),
    )
