"""
Pulls royalty-free, commercially-licensed background music from Jamendo's
official free API (free API key, real Creative Commons licensing metadata
per track, not scraping a platform's music library). Falls back to silence
if no JAMENDO_CLIENT_ID is set or nothing matches — never hard-fails.
"""
import os
import random
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "content" / "music" / "library"

JAMENDO_API_BASE = "https://api.jamendo.com/v3.0"


def get_track(mood_tag: str = "calm") -> Path | None:
    client_id = os.environ.get("JAMENDO_CLIENT_ID")
    if not client_id:
        return None

    try:
        resp = requests.get(
            f"{JAMENDO_API_BASE}/tracks/",
            params={
                "client_id": client_id,
                "format": "json",
                "limit": 10,
                "tags": mood_tag,
                "audioformat": "mp32",
                "include": "musicinfo",
                "ccsa": "true",  # Creative Commons tracks, safe for commercial reuse
            },
            timeout=20,
        )
        resp.raise_for_status()
        tracks = resp.json().get("results", [])
        if not tracks:
            return None

        track = random.choice(tracks)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        out_path = CACHE_DIR / f"jamendo_{track['id']}.mp3"
        if not out_path.exists():
            audio_resp = requests.get(track["audio"], timeout=30)
            audio_resp.raise_for_status()
            out_path.write_bytes(audio_resp.content)
        return out_path
    except Exception as e:
        print(f"[music_library] failed to fetch track: {e}")
        return None
