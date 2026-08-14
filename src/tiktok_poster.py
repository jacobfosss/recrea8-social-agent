"""
Posts a video to TikTok via the Content Posting API.
Docs: https://developers.tiktok.com/doc/content-posting-api-get-started

Uses FILE_UPLOAD, not PULL_FROM_URL. PULL_FROM_URL requires verifying
ownership of the domain the video is hosted on (DNS record or meta tag) —
our videos are hosted at raw.githubusercontent.com, which is GitHub's
domain, not ours, so we can never satisfy that requirement. FILE_UPLOAD
sends the video bytes directly to TikTok instead, sidestepping domain
ownership entirely.

NOTE: Until your app passes TikTok's "Direct Post" audit, videos posted
this way land in the user's TikTok inbox as a draft they must confirm
manually — this is a TikTok anti-spam requirement, not a bug in this code.
"""
import os
from pathlib import Path

import requests

API_ROOT = "https://open.tiktokapis.com/v2"

MIN_CHUNK_SIZE = 5 * 1024 * 1024    # 5 MB
MAX_CHUNK_SIZE = 64 * 1024 * 1024   # 64 MB
MAX_FINAL_CHUNK_SIZE = 128 * 1024 * 1024  # 128 MB, final chunk only


def _access_token() -> str:
    """Exchange the stored refresh token for a fresh short-lived access token."""
    resp = requests.post(
        f"{API_ROOT}/oauth/token/",
        data={
            "client_key": os.environ["TIKTOK_CLIENT_KEY"],
            "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
            "grant_type": "refresh_token",
            "refresh_token": os.environ["TIKTOK_REFRESH_TOKEN"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _compute_chunks(video_size: int) -> tuple:
    """Returns (chunk_size, total_chunk_count) per TikTok's documented rules:
    files under 5MB go as a single chunk; otherwise chunks are 5-64MB, with
    total_chunk_count = video_size // chunk_size (rounded down) — meaning
    the actual final chunk absorbs the remainder and can exceed chunk_size
    (up to 128MB), which is expected and documented, not an edge-case bug."""
    if video_size < MIN_CHUNK_SIZE:
        return video_size, 1

    chunk_size = 10 * 1024 * 1024  # 10MB — a reasonable middle value in the allowed 5-64MB range
    total_chunk_count = video_size // chunk_size
    if total_chunk_count < 1:
        total_chunk_count = 1
    return chunk_size, total_chunk_count


def _upload_file_chunks(upload_url: str, video_path: Path, video_size: int,
                          chunk_size: int, total_chunk_count: int):
    with open(video_path, "rb") as f:
        for i in range(total_chunk_count):
            start = i * chunk_size
            is_last = (i == total_chunk_count - 1)
            end = video_size - 1 if is_last else (start + chunk_size - 1)

            f.seek(start)
            chunk_bytes = f.read((end - start) + 1)

            resp = requests.put(
                upload_url,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{video_size}",
                    "Content-Type": "video/mp4",
                },
                data=chunk_bytes,
                timeout=120,
            )
            resp.raise_for_status()


def post_video(video_path, caption: str) -> str:
    """video_path: a LOCAL file path (not a hosted URL — FILE_UPLOAD reads
    directly from disk, no hosting step needed)."""
    video_path = Path(video_path)
    video_size = video_path.stat().st_size
    chunk_size, total_chunk_count = _compute_chunks(video_size)

    token = _access_token()

    init_body = {
        "post_info": {
            "title": caption,
            "privacy_level": "SELF_ONLY",  # change once you're comfortable / audited
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunk_count,
        },
    }

    init_resp = requests.post(
        f"{API_ROOT}/post/publish/video/init/",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=init_body,
        timeout=30,
    )
    init_resp.raise_for_status()
    init_data = init_resp.json().get("data", {})
    upload_url = init_data.get("upload_url")
    publish_id = init_data.get("publish_id", "unknown")

    if not upload_url:
        raise RuntimeError(f"TikTok init response had no upload_url: {init_resp.text}")

    _upload_file_chunks(upload_url, video_path, video_size, chunk_size, total_chunk_count)

    return publish_id