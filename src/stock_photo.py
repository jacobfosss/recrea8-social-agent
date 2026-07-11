"""
Pulls real, licensed stock photography from Pexels' official free API
(free API key, explicit commercial-use license, not scraping) to use as a
photographic base for posts instead of flat color cards.
"""
import os
import random
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "content" / "generated" / "stock_photos"

PEXELS_API_BASE = "https://api.pexels.com/v1"


def search_and_download(query: str, orientation: str = "portrait") -> Path | None:
    """Returns a local path to a downloaded photo matching `query`, or None if
    no PEXELS_API_KEY is set / no results found (caller should fall back to a
    solid-color card in that case — this should never hard-fail the pipeline)."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        return None

    try:
        resp = requests.get(
            f"{PEXELS_API_BASE}/search",
            headers={"Authorization": api_key},
            params={"query": query, "orientation": orientation, "per_page": 10},
            timeout=20,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        if not photos:
            return None

        photo = random.choice(photos)
        image_url = photo["src"]["large2x"]

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out_path = CACHE_DIR / f"pexels_{photo['id']}.jpg"
        if not out_path.exists():
            img_resp = requests.get(image_url, timeout=30)
            img_resp.raise_for_status()
            out_path.write_bytes(img_resp.content)
        return out_path
    except Exception as e:
        print(f"[stock_photo] failed for query '{query}': {e}")
        return None
