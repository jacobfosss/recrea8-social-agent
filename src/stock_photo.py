"""
Pulls real, licensed stock photography from Pexels' official free API
(free API key, explicit commercial-use license, not scraping) — used only
as a fallback when no real product photo is available in
content/product_photos/. When it IS used, fetches several candidates and
has Claude actually look at them and pick the best one, rather than
trusting a random result — stock photo relevance/quality was a recurring
weak point when picked blindly.
"""
import base64
import os
import random
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "content" / "generated" / "stock_photos"

PEXELS_API_BASE = "https://api.pexels.com/v1"
CANDIDATE_COUNT = 6


TARGET_ASPECT_RATIO = 1080 / 1920  # vertical frame — 0.5625


def _download(photo, out_path):
    if not out_path.exists():
        img_resp = requests.get(photo["src"]["large2x"], timeout=30)
        img_resp.raise_for_status()
        out_path.write_bytes(img_resp.content)
    return out_path


def _fetch_candidates(query: str, orientation: str = "portrait", count: int = CANDIDATE_COUNT):
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        return []
    try:
        resp = requests.get(
            f"{PEXELS_API_BASE}/search",
            headers={"Authorization": api_key},
            params={"query": query, "orientation": orientation, "per_page": count},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get("photos", [])
    except Exception as e:
        print(f"[stock_photo] search failed for '{query}': {e}")
        return []


def _filter_by_aspect_fit(candidates, keep_top_n=4):
    """Pexels' orientation='portrait' filter guarantees roughly portrait
    shape, but not a close match to our actual 9:16 vertical frame — a
    photo that's only mildly portrait (e.g. 4:5) still needs heavy
    cropping to fill a much taller frame. Sort by closeness to our actual
    target ratio and drop the worst-fitting candidates before relevance
    judgment, so we're never choosing between only badly-cropped options."""
    def _ratio_distance(photo):
        w, h = photo.get("width", 1), photo.get("height", 1)
        if h == 0:
            return float("inf")
        return abs((w / h) - TARGET_ASPECT_RATIO)

    sorted_candidates = sorted(candidates, key=_ratio_distance)
    return sorted_candidates[:keep_top_n]


def _claude_pick_best(candidates, query, brand_aesthetic):
    """Downloads thumbnails of each candidate and asks Claude to pick the
    best one — screening OUT any photo showing visible competitor branding
    first, since that's a real brand-risk issue (not just an aesthetic
    miss), then judging relevance/composition among what's left. Falls
    back to the first candidate if the vision call fails for any reason —
    never blocks the pipeline."""
    from anthropic import Anthropic

    try:
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        content_blocks = [{
            "type": "text",
            "text": (
                f"I need a background photo for a social media post about: "
                f"\"{query}\". Brand aesthetic: {brand_aesthetic or 'clean, premium, natural, appetizing'}. "
                f"Here are {len(candidates)} candidate photos, numbered 1-{len(candidates)}.\n\n"
                f"FIRST AND MOST IMPORTANT: reject any photo showing a visible "
                f"brand name, logo, or recognizable packaged product — "
                f"especially any competing food or ice cream brand (e.g. "
                f"Halo Top, Ben & Jerry's, Häagen-Dazs, store-shelf shots "
                f"with readable packaging, etc.). This applies even if the "
                f"photo is otherwise well-composed and relevant — showing a "
                f"competitor's branded product is a real problem, not a "
                f"minor issue.\n\n"
                f"Among the photos with NO visible third-party branding, pick "
                f"the one most relevant to the topic, best composed, and most "
                f"appetizing/on-brand. If every single candidate shows visible "
                f"branding, pick whichever has the LEAST visible branding as a "
                f"last resort.\n\n"
                f"Respond with ONLY the number, nothing else."
            ),
        }]
        for i, photo in enumerate(candidates, 1):
            thumb_resp = requests.get(photo["src"]["small"], timeout=20)
            thumb_resp.raise_for_status()
            b64 = base64.b64encode(thumb_resp.content).decode()
            content_blocks.append({"type": "text", "text": f"Photo {i}:"})
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
        print(f"[stock_photo] Claude curation failed, using first candidate: {e}")

    return candidates[0]


def search_and_download(query: str, orientation: str = "portrait", brand_aesthetic: str = ""):
    """Returns a local path to a Claude-curated photo matching `query`, or
    None if no PEXELS_API_KEY is set / no results found (caller should fall
    back to a solid-color card or product photo in that case)."""
    candidates = _fetch_candidates(query, orientation)
    if not candidates:
        return None

    candidates = _filter_by_aspect_fit(candidates)

    chosen = (
        _claude_pick_best(candidates, query, brand_aesthetic)
        if len(candidates) > 1 and os.environ.get("ANTHROPIC_API_KEY")
        else random.choice(candidates)
    )

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CACHE_DIR / f"pexels_{chosen['id']}.jpg"
    return _download(chosen, out_path)