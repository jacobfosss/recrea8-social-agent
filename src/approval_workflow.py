"""
Optional human-approval step before anything actually posts. Uses GitHub
Issues as the review UI — free, no extra service to set up.
"""
import json
import os
from pathlib import Path

import requests

from . import instagram_poster, tiktok_poster, post_history

ROOT = Path(__file__).resolve().parent.parent
PENDING_PATH = ROOT / "data" / "pending_posts.json"

GITHUB_API_BASE = "https://api.github.com"


def _headers():
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
    }


def _load_pending():
    if PENDING_PATH.exists():
        return json.loads(PENDING_PATH.read_text())
    return {}


def _save_pending(pending):
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(pending, indent=2))


def _tiktok_preview_block(tiktok_public_url):
    if not tiktok_public_url:
        return ""
    return f"\n**TikTok video:** {tiktok_public_url}\n"


def create_approval_request(content, public_url, platforms, tiktok_public_url=None):
    repo = os.environ["GITHUB_REPO"]
    media_preview = (
        f"![preview]({public_url})" if content["media_type"] == "image"
        else f"[video preview]({public_url})"
    )
    body = f"""{media_preview}
{_tiktok_preview_block(tiktok_public_url)}
**Source:** {content.get('source')}
**Topic:** {content.get('topic', 'n/a')}
**Platforms queued:** {', '.join(p for p, on in platforms.items() if on)}

**Caption:**
{content['caption']}

---
Comment `approve` on this issue to publish it. Close the issue (or ignore it)
to skip this post — nothing publishes until you approve.
"""
    resp = requests.post(
        f"{GITHUB_API_BASE}/repos/{repo}/issues",
        headers=_headers(),
        json={"title": f"[Pending approval] {content.get('topic', content['source'])}",
              "body": body, "labels": ["pending-approval"]},
        timeout=30,
    )
    resp.raise_for_status()
    issue_number = resp.json()["number"]

    pending = _load_pending()
    pending[str(issue_number)] = {
        "public_url": public_url,
        "media_type": content["media_type"],
        "caption": content["caption"],
        "platforms": platforms,
        "topic": content.get("topic", "unknown"),
        "source": content.get("source", "unknown"),
        "tiktok_public_url": tiktok_public_url,
    }
    _save_pending(pending)
    print(f"[approval] opened issue #{issue_number} for review")
    return issue_number


def create_carousel_approval_request(content, public_urls, platforms, tiktok_public_url=None):
    repo = os.environ["GITHUB_REPO"]
    previews = "\n".join(f"![slide {i+1}]({url})" for i, url in enumerate(public_urls))
    body = f"""**{len(public_urls)}-slide carousel**

{previews}
{_tiktok_preview_block(tiktok_public_url)}
**Source:** {content.get('source')}
**Topic:** {content.get('topic', 'n/a')}
**Platforms queued:** {', '.join(p for p, on in platforms.items() if on)}

**Caption:**
{content['caption']}

---
Comment `approve` on this issue to publish it. Close the issue (or ignore it)
to skip this post — nothing publishes until you approve.
"""
    resp = requests.post(
        f"{GITHUB_API_BASE}/repos/{repo}/issues",
        headers=_headers(),
        json={"title": f"[Pending approval] Carousel: {content.get('topic', content['source'])}",
              "body": body, "labels": ["pending-approval"]},
        timeout=30,
    )
    resp.raise_for_status()
    issue_number = resp.json()["number"]

    pending = _load_pending()
    pending[str(issue_number)] = {
        "public_urls": public_urls,
        "media_type": "carousel",
        "caption": content["caption"],
        "platforms": platforms,
        "topic": content.get("topic", "unknown"),
        "source": content.get("source", "unknown"),
        "tiktok_public_url": tiktok_public_url,
    }
    _save_pending(pending)
    print(f"[approval] opened issue #{issue_number} for carousel review")
    return issue_number


def _issue_is_approved(repo, issue_number):
    resp = requests.get(
        f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/comments",
        headers=_headers(), timeout=30,
    )
    resp.raise_for_status()
    return any("approve" in c.get("body", "").lower() for c in resp.json())


def _close_issue(repo, issue_number):
    requests.patch(
        f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}",
        headers=_headers(), json={"state": "closed"}, timeout=30,
    )


def check_and_publish_approved():
    repo = os.environ["GITHUB_REPO"]
    pending = _load_pending()
    if not pending:
        print("[approval] nothing pending")
        return

    still_pending = {}
    for issue_number, draft in pending.items():
        try:
            if _issue_is_approved(repo, issue_number):
                platforms = draft["platforms"]
                content_stub = {"topic": draft.get("topic", "unknown"),
                                 "source": draft.get("source", "unknown"),
                                 "media_type": draft["media_type"],
                                 "caption": draft["caption"]}

                if draft["media_type"] == "carousel":
                    if platforms.get("instagram"):
                        post_id = instagram_poster.post_carousel(
                            draft["public_urls"], draft["caption"])
                        print(f"[approval] published carousel to Instagram, id={post_id}")
                        post_history.record_post(
                            "instagram", post_id, content_stub, draft["public_urls"][0])
                else:
                    if platforms.get("instagram"):
                        post_id = instagram_poster.post(
                            draft["public_url"], draft["media_type"], draft["caption"])
                        print(f"[approval] published to Instagram, id={post_id}")
                        post_history.record_post("instagram", post_id, content_stub, draft["public_url"])

                # TikTok: independent of whether the Instagram content was a
                # carousel or single image — the narrated video is a
                # separate asset built specifically for TikTok
                if platforms.get("tiktok") and draft.get("tiktok_public_url"):
                    publish_id = tiktok_poster.post_video(draft["tiktok_public_url"], draft["caption"])
                    print(f"[approval] submitted to TikTok, publish_id={publish_id}")
                    post_history.record_post("tiktok", publish_id, content_stub, draft["tiktok_public_url"])

                _close_issue(repo, issue_number)
            else:
                still_pending[issue_number] = draft
        except Exception as e:
            print(f"[approval] failed publishing issue #{issue_number}: {e}")
            still_pending[issue_number] = draft

    _save_pending(still_pending)


if __name__ == "__main__":
    check_and_publish_approved()