"""
Posts a video to TikTok via the Content Posting API.
Docs: https://developers.tiktok.com/doc/content-posting-api-get-started

NOTE: Until your app passes TikTok's "Direct Post" audit, videos posted this
way land in the user's TikTok inbox as a draft they must confirm manually —
this is a TikTok anti-spam requirement, not a bug in this code.

TikTok only supports video via this API (no static-image feed posts through
Content Posting API for third-party apps), so this is used for the video half
of the "mix of both" content plan.
"""
import os

import requests

API_ROOT = "https://open.tiktokapis.com/v2"


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


def post_video(video_url: str, caption: str) -> str:
    token = _access_token()

    body = {
        "post_info": {
            "title": caption,
            "privacy_level": "SELF_ONLY",  # change once you're comfortable / audited
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "video_url": video_url,
        },
    }

    resp = requests.post(
        f"{API_ROOT}/post/publish/video/init/",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", {}).get("publish_id", "unknown")
