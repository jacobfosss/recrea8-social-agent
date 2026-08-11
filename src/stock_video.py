"""
Searches Pexels' VIDEO library — real motion footage, not static photos —
for genuinely dynamic B-roll. This is what actually solves the "feels like
a slideshow" problem: no amount of caption/transition polish on a still
image produces real motion, only actual video clips do.
"""
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "content" / "generated" / "stock_video"

PEXELS_VIDEO_API = "https://api.pexels.com/videos/search"
TARGET_ASPECT_RATIO = 1080 / 1920


def _best_video_file(video: dict):
    """Pexels returns several quality/resolution variants per video —
    prefer HD portrait-oriented files, since that's the closest match to
    our vertical frame and avoids wasting bandwidth on 4K files we'd just
    downscale anyway."""
    files = video.get("video_files", [])
    portrait_hd = [f for f in files if f.get("height", 0) > f.get("width", 0) and f.get("quality") == "hd"]
    if portrait_hd:
        return portrait_hd[0]
    hd = [f for f in files if f.get("quality") == "hd"]
    if hd:
        return hd[0]
    return files[0] if files else None


def _claude_pick_best_video(candidates: list, query: str):
    """Judges candidates by their thumbnail image (Pexels provides one per
    video) rather than blindly taking the first result — same approach
    already working well for photo selection. Falls back to the first
    candidate if the vision call fails for any reason."""
    if len(candidates) <= 1 or not os.environ.get("ANTHROPIC_API_KEY"):
        return candidates[0] if candidates else None

    import base64
    from anthropic import Anthropic

    try:
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        content_blocks = [{
            "type": "text",
            "text": (
                f"I need a background video clip for a social media post about: "
                f"\"{query}\". Here are {len(candidates)} candidate video thumbnails, "
                f"numbered 1-{len(candidates)}.\n\n"
                f"FIRST AND MOST IMPORTANT: reject any thumbnail showing a visible "
                f"brand name, logo, or recognizable packaged food product — "
                f"especially any competing food or ice cream brand. This applies "
                f"even if otherwise relevant.\n\n"
                f"Among the rest, pick the one most relevant to the topic, best "
                f"composed, and most appetizing/appealing — reject anything that "
                f"looks odd, unappetizing, or low quality even if topically related. "
                f"Respond with ONLY the number, nothing else."
            ),
        }]
        for i, video in enumerate(candidates, 1):
            thumb_url = video.get("image")
            if not thumb_url:
                continue
            thumb_resp = requests.get(thumb_url, timeout=20)
            thumb_resp.raise_for_status()
            b64 = base64.b64encode(thumb_resp.content).decode()
            content_blocks.append({"type": "text", "text": f"Video {i}:"})
            content_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
            })

        resp = client.messages.create(
            model="claude-sonnet-5", max_tokens=10,
            messages=[{"role": "user", "content": content_blocks}],
        )
        answer = "".join(b.text for b in resp.content if b.type == "text").strip()
        idx = int("".join(ch for ch in answer if ch.isdigit())) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]
    except Exception as e:
        print(f"[stock_video] Claude curation failed, using first candidate: {e}")

    return candidates[0]


def search_and_download_video(query: str, min_duration: float = 2.0, max_duration: float = 15.0):
    """Returns a local path to a Claude-curated Pexels video matching
    `query`, or None if no PEXELS_API_KEY is set, no results found, or no
    result fits the requested duration range (caller should fall back to a
    static photo in that case)."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        return None

    try:
        resp = requests.get(
            PEXELS_VIDEO_API,
            headers={"Authorization": api_key},
            params={"query": query, "orientation": "portrait", "per_page": 6},
            timeout=20,
        )
        resp.raise_for_status()
        videos = resp.json().get("videos", [])
    except Exception as e:
        print(f"[stock_video] search failed for '{query}': {e}")
        return None

    candidates = [v for v in videos if min_duration <= v.get("duration", 0) <= max_duration]
    if not candidates:
        return None

    chosen = _claude_pick_best_video(candidates, query)
    if not chosen:
        return None
    file_info = _best_video_file(chosen)
    if not file_info:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CACHE_DIR / f"pexels_video_{chosen['id']}.mp4"
    if not out_path.exists():
        video_resp = requests.get(file_info["link"], timeout=60)
        video_resp.raise_for_status()
        out_path.write_bytes(video_resp.content)

    return out_path