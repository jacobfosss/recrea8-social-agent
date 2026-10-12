"""
"Pasture" background style for educational videos: real drone/farm/pasture
footage from Pexels behind the captions, instead of the fixed "Better
Informed" poster. Alternates with the poster style in groups of 3
(3 poster, 3 pasture, repeat).

Each clip is processed with ffmpeg so it's exactly 1080x1920, exactly as
long as its narration (looped if the stock clip is shorter), silent, and
slightly darkened so cream captions stay readable.
"""
import json
import os
import random
import subprocess
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "educational_style.json"
RAW_DIR = ROOT / "content" / "generated" / "pasture_raw"
OUT_DIR = ROOT / "content" / "generated" / "pasture_clips"

PEXELS_VIDEO_API = "https://api.pexels.com/videos/search"
GROUP_SIZE = 3

QUERIES = [
    "drone green pasture farmland",
    "aerial farm fields countryside",
    "cows grazing green pasture",
    "dairy cows meadow",
    "rolling green hills farm",
    "pasture sunrise golden hour",
    "aerial view farmland drone",
    "cattle grazing field",
    "green grass field wind",
    "farm barn countryside",
]


# ---------- rotation ----------

def _load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"count": 0}


def next_style() -> str:
    """Returns 'poster' or 'pasture' and advances the counter.
    3 poster, 3 pasture, repeat. EDU_STYLE=poster|pasture forces one
    (for testing) without touching the rotation."""
    forced = os.environ.get("EDU_STYLE", "").strip().lower()
    if forced in ("poster", "pasture"):
        return forced
    state = _load_state()
    n = state.get("count", 0)
    style = "poster" if (n // GROUP_SIZE) % 2 == 0 else "pasture"
    state["count"] = n + 1
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))
    return style


# ---------- Pexels ----------

def _search(query: str, orientation: str):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    try:
        r = requests.get(PEXELS_VIDEO_API, headers={"Authorization": key},
                         params={"query": query, "orientation": orientation, "per_page": 15},
                         timeout=20)
        r.raise_for_status()
        return r.json().get("videos", [])
    except Exception as e:
        print(f"[pasture] search failed for '{query}': {e}")
        return []


def _best_file(video: dict):
    files = [f for f in video.get("video_files", []) if f.get("link")]
    if not files:
        return None
    hd = [f for f in files if (f.get("height") or 0) >= 1080 and (f.get("width") or 0) <= 4096]
    pool = hd or files
    return sorted(pool, key=lambda f: (f.get("height") or 0) * (f.get("width") or 0))[0 if hd else -1]


def _download_candidate(used_ids: set, queries: list):
    """Tries queries in order (portrait first, then landscape, which ffmpeg
    crops to vertical). Returns a local raw path or None."""
    for q in queries:
        for orientation in ("portrait", "landscape"):
            videos = [v for v in _search(q, orientation)
                      if v.get("id") not in used_ids and (v.get("duration") or 0) >= 4]
            random.shuffle(videos)
            for v in videos:
                f = _best_file(v)
                if not f:
                    continue
                RAW_DIR.mkdir(parents=True, exist_ok=True)
                path = RAW_DIR / f"pexels_{v['id']}.mp4"
                if not path.exists():
                    try:
                        resp = requests.get(f["link"], timeout=120)
                        resp.raise_for_status()
                        path.write_bytes(resp.content)
                    except Exception as e:
                        print(f"[pasture] download failed: {e}")
                        continue
                used_ids.add(v["id"])
                return path
    return None


# ---------- ffmpeg ----------

def process_clip(raw_path: Path, duration: float, out_path: Path) -> Path:
    """Exactly `duration` seconds, 1080x1920, silent, slightly darkened.
    Loops the source if it's shorter than the narration."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-stream_loop", "-1", "-i", str(raw_path),
        "-t", f"{duration:.2f}",
        "-vf", ("scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,eq=brightness=-0.10:saturation=1.08,fps=30"),
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    return out_path


def _audio_duration(path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def build_pasture_visuals(scene_audio_paths: list):
    """One processed pasture clip per scene, each matching that scene's
    narration length. Returns [(path, True), ...] or None if Pexels didn't
    return enough footage (caller falls back to the poster style)."""
    queries = QUERIES[:]
    random.shuffle(queries)
    used_ids, visuals = set(), []
    for i, audio in enumerate(scene_audio_paths):
        duration = _audio_duration(audio)
        rotated = queries[i % len(queries):] + queries[:i % len(queries)]
        raw = _download_candidate(used_ids, rotated)
        if raw is None:
            print("[pasture] not enough footage found — falling back to poster style")
            return None
        out = OUT_DIR / f"pasture_{random.randint(100000, 999999)}_s{i}.mp4"
        visuals.append((process_clip(raw, duration, out), True))
    return visuals
