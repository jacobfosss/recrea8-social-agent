"""
Posts a photo or Reel to Instagram via the Meta Graph API.
Docs: https://developers.facebook.com/docs/instagram-platform/content-publishing
"""
import os
import time

import requests

GRAPH_VERSION = "v21.0"
BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


def _ig_user_id():
    return os.environ["IG_BUSINESS_ACCOUNT_ID"]


def _token():
    return os.environ["IG_ACCESS_TOKEN"]


def post_image(image_url: str, caption: str) -> str:
    ig_id = _ig_user_id()
    token = _token()

    create = requests.post(
        f"{BASE}/{ig_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": token},
        timeout=30,
    )
    create.raise_for_status()
    creation_id = create.json()["id"]

    publish = requests.post(
        f"{BASE}/{ig_id}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=30,
    )
    publish.raise_for_status()
    return publish.json()["id"]


def post_reel(video_url: str, caption: str, poll_seconds=10, timeout_seconds=300) -> str:
    ig_id = _ig_user_id()
    token = _token()

    create = requests.post(
        f"{BASE}/{ig_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": token,
        },
        timeout=30,
    )
    create.raise_for_status()
    creation_id = create.json()["id"]

    # Instagram processes the video asynchronously — poll until FINISHED.
    waited = 0
    while waited < timeout_seconds:
        status = requests.get(
            f"{BASE}/{creation_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=30,
        ).json()
        if status.get("status_code") == "FINISHED":
            break
        if status.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram failed to process video: {status}")
        time.sleep(poll_seconds)
        waited += poll_seconds
    else:
        raise TimeoutError("Instagram video processing did not finish in time")

    publish = requests.post(
        f"{BASE}/{ig_id}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=30,
    )
    publish.raise_for_status()
    return publish.json()["id"]


def post_story(media_url: str, media_type: str) -> str:
    """Stories don't take a caption field the way feed posts do — text should
    already be baked into the image/video itself if you want copy on it."""
    ig_id = _ig_user_id()
    token = _token()

    data = {"media_type": "STORIES", "access_token": token}
    data["video_url" if media_type == "video" else "image_url"] = media_url

    create = requests.post(f"{BASE}/{ig_id}/media", data=data, timeout=30)
    create.raise_for_status()
    creation_id = create.json()["id"]

    if media_type == "video":
        # Stories videos are processed async too, same as Reels
        waited, poll_seconds, timeout_seconds = 0, 10, 180
        while waited < timeout_seconds:
            status = requests.get(
                f"{BASE}/{creation_id}",
                params={"fields": "status_code", "access_token": token},
                timeout=30,
            ).json()
            if status.get("status_code") == "FINISHED":
                break
            if status.get("status_code") == "ERROR":
                raise RuntimeError(f"Instagram failed to process story video: {status}")
            time.sleep(poll_seconds)
            waited += poll_seconds

    publish = requests.post(
        f"{BASE}/{ig_id}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=30,
    )
    publish.raise_for_status()
    return publish.json()["id"]


def post(media_url: str, media_type: str, caption: str) -> str:
    if media_type == "video":
        return post_reel(media_url, caption)
    return post_image(media_url, caption)
