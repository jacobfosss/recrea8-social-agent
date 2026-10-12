"""
Sends a video to TikTok via the Content Posting API.

Two modes, picked by the TIKTOK_POST_MODE env var:

- "draft" (default): Upload endpoint, /v2/post/publish/inbox/video/init/
  (scope video.upload). The video lands in the TikTok app as a draft with an
  inbox notification; you open it, paste the caption, and tap Post. This needs
  no Direct Post audit and works on a public account. TikTok caps this at
  5 pending (un-posted) drafts per 24 hours, and the API can't set a caption,
  so the caption is printed in the log for you to paste.

- "direct": Direct Post endpoint, /v2/post/publish/video/init/ (scope
  video.publish). Publishes straight to the profile. Until the Direct Post
  audit is approved, TikTok only allows this to a PRIVATE account
  (unaudited_client_can_only_post_to_private_accounts).

Both use FILE_UPLOAD (video bytes sent directly), not PULL_FROM_URL, because
PULL_FROM_URL requires verifying ownership of the host domain and our files
live on raw.githubusercontent.com, which we don't own.
"""
import os
from pathlib import Path

import requests

API_ROOT = "https://open.tiktokapis.com/v2"

DRAFT_INIT_URL = f"{API_ROOT}/post/publish/inbox/video/init/"
DIRECT_INIT_URL = f"{API_ROOT}/post/publish/video/init/"

MAX_CHUNK_SIZE = 64 * 1024 * 1024
MULTI_CHUNK_SIZE = 10 * 1024 * 1024


def _post_mode() -> str:
    mode = os.environ.get("TIKTOK_POST_MODE", "draft").strip().lower()
    return "direct" if mode == "direct" else "draft"


def _direct_privacy_level() -> str:
    # SELF_ONLY while unaudited (also requires the account itself to be private);
    # set TIKTOK_PRIVACY_LEVEL=PUBLIC_TO_EVERYONE once the Direct Post audit passes.
    return os.environ.get("TIKTOK_PRIVACY_LEVEL", "SELF_ONLY")


def _access_token() -> str:
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
    """A file that fits in one chunk must declare chunk_size == video_size
    (TikTok rejects a mismatch with 'The chunk size is invalid'). Larger
    files split into 10MB chunks; the last chunk absorbs the remainder."""
    if video_size <= MAX_CHUNK_SIZE:
        return video_size, 1
    return MULTI_CHUNK_SIZE, video_size // MULTI_CHUNK_SIZE


def _upload_file_chunks(upload_url: str, video_path: Path, video_size: int,
                        chunk_size: int, total_chunk_count: int):
    with open(video_path, "rb") as f:
        for i in range(total_chunk_count):
            start = i * chunk_size
            is_last = (i == total_chunk_count - 1)
            end = video_size - 1 if is_last else (start + chunk_size - 1)
            f.seek(start)
            chunk_bytes = f.read(end - start + 1)
            resp = requests.put(
                upload_url,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{video_size}",
                    "Content-Length": str(len(chunk_bytes)),
                    "Content-Type": "video/mp4",
                },
                data=chunk_bytes,
                timeout=120,
            )
            if resp.status_code >= 400:
                print(f"[tiktok] chunk {i} upload rejected ({resp.status_code}): {resp.text}")
            resp.raise_for_status()


def build_init_body(mode: str, caption: str, video_size: int,
                    chunk_size: int, total_chunk_count: int) -> dict:
    source_info = {
        "source": "FILE_UPLOAD",
        "video_size": video_size,
        "chunk_size": chunk_size,
        "total_chunk_count": total_chunk_count,
    }
    if mode == "draft":
        # The inbox/upload endpoint takes only source_info; caption is added
        # by hand in the TikTok app when finishing the draft.
        return {"source_info": source_info}
    return {
        "post_info": {
            "title": caption,
            "privacy_level": _direct_privacy_level(),
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        },
        "source_info": source_info,
    }


def post_video(video_path, caption: str) -> str:
    """video_path: a LOCAL file path. Returns TikTok's publish_id."""
    video_path = Path(video_path)
    video_size = video_path.stat().st_size
    chunk_size, total_chunk_count = _compute_chunks(video_size)
    mode = _post_mode()

    token = _access_token()
    init_resp = requests.post(
        DRAFT_INIT_URL if mode == "draft" else DIRECT_INIT_URL,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=UTF-8"},
        json=build_init_body(mode, caption, video_size, chunk_size, total_chunk_count),
        timeout=30,
    )
    if init_resp.status_code >= 400:
        print(f"[tiktok] init request rejected ({init_resp.status_code}): {init_resp.text}")
    init_resp.raise_for_status()

    data = init_resp.json().get("data", {})
    upload_url = data.get("upload_url")
    publish_id = data.get("publish_id", "unknown")
    if not upload_url:
        raise RuntimeError(f"TikTok init response had no upload_url: {init_resp.text}")

    _upload_file_chunks(upload_url, video_path, video_size, chunk_size, total_chunk_count)

    if mode == "draft":
        print("[tiktok] sent to your TikTok drafts. Open the TikTok app, tap the "
              "inbox notification, paste this caption, and post:")
        print("----- CAPTION -----")
        print(caption)
        print("-------------------")
    return publish_id