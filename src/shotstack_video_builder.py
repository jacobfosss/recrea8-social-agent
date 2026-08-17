"""
Builds narrated TikTok/Reels videos using Shotstack's cloud rendering API.

IMPORTANT DESIGN NOTE: scenes now use RAW background media (photo or real
video, no text baked in) — Shotstack's caption track is the only source of
on-screen text now. Baking text into the image via Pillow AND having
Shotstack auto-caption the same narration would double up the text.

Each scene gets its OWN audio clip (matching how the rest of the pipeline
already generates narration — one voiceover per beat/slide), and each
scene's on-screen duration is matched to that clip's ACTUAL length, not a
guessed fixed number. The previous version assumed one audio file spanned
the whole video, which is why narration cut out after the first scene in
testing — this version fixes that at the root.
"""
import os
import random
import time
from pathlib import Path

import requests
from pydub import AudioSegment

from . import media_host

SHOTSTACK_BASE = "https://api.shotstack.io"
VIDEO_OUT_DIR = Path(__file__).resolve().parent.parent / "content" / "generated" / "shotstack_video"
AUDIO_TEMP_DIR = Path(__file__).resolve().parent.parent / "content" / "generated" / "shotstack_audio_combined"

CAPTION_FONT_COLOR = "#EDE7DA"
CAPTION_FONT_FAMILY = "Montserrat"
CAPTION_STROKE_COLOR = "#1D1D1D"
ACTIVE_WORD_GOLD = "#C49A4A"  # matches the brand gold used throughout the carousel design


def _stage(use_production: bool) -> str:
    return "v1" if use_production else "stage"


def _api_key(use_production: bool) -> str:
    key_name = "SHOTSTACK_PRODUCTION_API_KEY" if use_production else "SHOTSTACK_SANDBOX_API_KEY"
    key = os.environ.get(key_name)
    if not key:
        raise RuntimeError(f"{key_name} not set in .env")
    return key


def _submit_render(payload: dict, use_production: bool) -> str:
    stage = _stage(use_production)
    resp = requests.post(
        f"{SHOTSTACK_BASE}/{stage}/render",
        headers={"x-api-key": _api_key(use_production), "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        print(f"[shotstack] render request rejected ({resp.status_code}): {resp.text}")
    resp.raise_for_status()
    return resp.json()["response"]["id"]


def _poll_render(render_id: str, use_production: bool, timeout_seconds: int = 900) -> str:
    stage = _stage(use_production)
    headers = {"x-api-key": _api_key(use_production)}
    start = time.time()
    last_status = None

    while time.time() - start < timeout_seconds:
        resp = requests.get(f"{SHOTSTACK_BASE}/{stage}/render/{render_id}", headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()["response"]
        status = data["status"]

        if status != last_status:
            elapsed = int(time.time() - start)
            print(f"[shotstack] render status: {status} (at {elapsed}s)")
            last_status = status

        if status == "done":
            return data["url"]
        if status == "failed":
            raise RuntimeError(f"Shotstack render {render_id} failed: {data.get('error', 'unknown error')}")

        time.sleep(5)

    raise TimeoutError(
        f"Shotstack render {render_id} did not finish within {timeout_seconds}s "
        f"— last known status was '{last_status}'. If this keeps happening with "
        f"real product video included, the video file may be too large/long — "
        f"check its size and consider trimming it."
    )


def _download(url: str, out_path: Path) -> Path:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    return out_path


def _combine_audio(audio_paths: list) -> tuple:
    """Concatenates per-scene audio files into one continuous track (needed
    since Shotstack's caption auto-transcription works off a single aliased
    clip), and returns (combined_file_path, [each scene's individual
    duration in seconds]) so scene visuals can be timed correctly against
    the combined track."""
    AUDIO_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    combined = AudioSegment.empty()
    durations = []

    for p in audio_paths:
        segment = AudioSegment.from_file(str(p))
        durations.append(len(segment) / 1000.0)  # pydub gives milliseconds
        combined += segment

    combined_path = AUDIO_TEMP_DIR / f"combined_{os.getpid()}_{int(time.time())}.mp3"
    combined.export(str(combined_path), format="mp3")
    return combined_path, durations


def _wait_until_fetchable(url: str, max_attempts: int = 10, delay_seconds: float = 2.0) -> bool:
    """GitHub's raw content CDN can have a brief propagation delay right
    after a file is first committed via the Contents API — Shotstack can
    try to fetch a freshly-hosted asset before GitHub's CDN has actually
    caught up, failing with a confusing 'asset could not be found' error
    even though the file is completely fine moments later. This polls
    until the URL is genuinely fetchable before we ever hand it to
    Shotstack, rather than finding out only after a wasted render attempt."""
    for attempt in range(max_attempts):
        try:
            resp = requests.head(url, timeout=10)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(delay_seconds)

    print(f"[shotstack] WARNING: {url} still not fetchable after "
          f"{max_attempts} attempts — proceeding anyway, but this render "
          f"may fail the same way.")
    return False


def build_video(scene_visuals: list, scene_audio_paths: list, filename_hint: str = "shotstack",
                  caption_intensity: str = "calm", music_path: Path = None,
                  use_production: bool = False, caption_palette: str = "light_on_dark") -> Path:
    """scene_visuals: list of (path, is_video) tuples — one raw background
    per scene, no baked-in text. scene_audio_paths: list of Paths, same
    length and order — one narration clip per scene. Each scene's on-screen
    duration is matched to its OWN audio clip's real length.

    caption_palette: "light_on_dark" (cream text, for dark backgrounds —
    the creative pillar's varied photo/video backgrounds) or "dark_on_light"
    (near-black text, for the educational pillar's cream background —
    cream-on-cream would be nearly invisible). Both use gold for the
    active/currently-spoken word either way.

    Returns a local Path to the downloaded finished video.
    """
    if len(scene_visuals) != len(scene_audio_paths):
        raise ValueError(
            f"scene_visuals ({len(scene_visuals)}) and scene_audio_paths "
            f"({len(scene_audio_paths)}) must be the same length — one "
            f"visual and one audio clip per scene."
        )

    VIDEO_OUT_DIR.mkdir(parents=True, exist_ok=True)

    combined_audio_path, scene_durations = _combine_audio(scene_audio_paths)

    visual_urls = [
        (media_host.publish_to_public_url(path), is_video)
        for path, is_video in scene_visuals
    ]
    audio_url = media_host.publish_to_public_url(combined_audio_path)
    music_url = media_host.publish_to_public_url(music_path) if music_path else None

    # Verify every hosted asset is actually fetchable before submitting to
    # Shotstack — GitHub's CDN can lag a few seconds behind a fresh upload.
    for url, _ in visual_urls:
        _wait_until_fetchable(url)
    _wait_until_fetchable(audio_url)
    if music_url:
        _wait_until_fetchable(music_url)

    visual_clips = []
    cursor = 0.0
    for (url, is_video), duration in zip(visual_urls, scene_durations):
        clip = {
            "asset": {"type": "video" if is_video else "image", "src": url},
            "start": round(cursor, 2),
            "length": round(duration, 2),
        }
        if not is_video and filename_hint != "educational":
            clip["effect"] = "zoomIn"  # Ken Burns still adds life to creative's varied
                                         # stock photos — but educational reuses ONE fixed
                                         # background the whole video, where zoom has no
                                         # real purpose and crops into "BETTER INFORMED"
        visual_clips.append(clip)
        cursor += duration

    total_duration = cursor

    if caption_palette == "dark_on_light":
        base_font_color = CAPTION_STROKE_COLOR  # near-black — reused as
                                                   # the base text color here
        stroke_color = "#EDE7DA"                  # light stroke, inverted
                                                    # from the dark-background version
    else:
        base_font_color = CAPTION_FONT_COLOR
        stroke_color = CAPTION_STROKE_COLOR

    caption_style = "karaoke" if caption_intensity == "energetic" else "highlight"
    caption_track = {
        "clips": [{
            "asset": {
                "type": "rich-caption",
                "src": "alias://speech",
                "font": {
                    "family": CAPTION_FONT_FAMILY,
                    "size": 32 if caption_intensity == "calm" else 38,
                    "color": base_font_color,
                    "weight": 500,  # medium, not bold — matches the poster's
                                     # own refined, lighter-weight typography
                                     # rather than a heavy/loud look
                },
                "animation": {
                    "style": caption_style,
                },
                "active": {
                    # the word currently being spoken pops to brand gold —
                    # true regardless of palette, since gold reads clearly
                    # against both the dark and light backgrounds
                    "font": {"color": ACTIVE_WORD_GOLD},
                },
                "align": {"vertical": "middle"},
            },
            "start": 0,
            "length": "end",
            "width": 900,  # ~90px margin each side of the 1080-wide frame,
                            # keeping captions clear of the edges and clear
                            # of the corner design elements above/below the
                            # empty middle band
        }]
    }

    audio_track = {
        "clips": [{
            "alias": "speech",
            "asset": {"type": "audio", "src": audio_url},
            "start": 0,
            "length": "auto",
        }]
    }

    tracks = [caption_track, {"clips": visual_clips}, audio_track]

    if music_url:
        tracks.append({
            "clips": [{
                "asset": {"type": "audio", "src": music_url, "volume": 0.15},
                "start": 0,
                "length": round(total_duration, 2),
            }]
        })

    payload = {
        "timeline": {"tracks": tracks},
        "output": {"format": "mp4", "size": {"width": 1080, "height": 1920}},
    }

    try:
        render_id = _submit_render(payload, use_production)
    except requests.HTTPError:
        print("[shotstack] Rich Captions request was rejected for an "
              "unexpected reason — falling back to the older basic caption "
              "type as a safety net so the render still completes. Send me "
              "the error text above so I can look into it.")
        tracks[0] = {
            "clips": [{
                "asset": {
                    "type": "caption",
                    "src": "alias://speech",
                    "font": {
                        "color": CAPTION_FONT_COLOR,
                        "family": CAPTION_FONT_FAMILY,
                        "size": 32 if caption_intensity == "calm" else 38,
                        "stroke": CAPTION_STROKE_COLOR,
                        "strokeWidth": 1.5,
                    },
                },
                "start": 0,
                "length": "end",
            }]
        }
        payload["timeline"]["tracks"] = tracks
        render_id = _submit_render(payload, use_production)

    print(f"[shotstack] render submitted, id={render_id} — polling for completion...")
    result_url = _poll_render(render_id, use_production)

    out_path = VIDEO_OUT_DIR / f"{filename_hint}_{random.randint(100000, 999999)}.mp4"
    _download(result_url, out_path)
    print(f"[shotstack] video ready: {out_path}")
    return out_path