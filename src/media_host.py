"""
Instagram and TikTok's APIs need media at a public URL, not a raw file upload.
This pushes the chosen file into the GitHub repo (under content/posted/) via
the GitHub Contents API and returns the raw.githubusercontent.com URL.

Requires GITHUB_TOKEN, GITHUB_REPO ("user/repo"), GITHUB_BRANCH in the env.
"""
import base64
import os
import time

import requests

API_ROOT = "https://api.github.com"


def _headers():
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
    }


def publish_to_public_url(local_path) -> str:
    repo = os.environ["GITHUB_REPO"]
    branch = os.environ.get("GITHUB_BRANCH", "main")
    remote_path = f"content/posted/{int(time.time())}_{os.path.basename(local_path)}"

    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    resp = requests.put(
        f"{API_ROOT}/repos/{repo}/contents/{remote_path}",
        headers=_headers(),
        json={
            "message": f"Add media for post: {os.path.basename(local_path)}",
            "content": content_b64,
            "branch": branch,
        },
        timeout=30,
    )
    resp.raise_for_status()

    raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{remote_path}"
    return raw_url
