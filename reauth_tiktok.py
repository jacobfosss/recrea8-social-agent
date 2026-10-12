"""
One-time TikTok re-authorization to add the video.upload scope (needed for
sending videos to your drafts). Your current refresh token was granted
without it, which is why TikTok returned scope_not_authorized.

Run from the project folder:  python3 reauth_tiktok.py
It prints a link, you approve in the browser, paste back the URL you land
on, and it saves the new refresh token into .env.
"""
import secrets
import sys
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from dotenv import dotenv_values

ENV_PATH = Path(".env")
REDIRECT_URI = "https://recrea8.one"
SCOPES = "user.info.basic,video.upload,video.publish"


def main():
    if not ENV_PATH.exists():
        sys.exit("No .env here. Run this from the recrea8-social-agent folder.")
    env = dotenv_values(ENV_PATH)
    client_key = env.get("TIKTOK_CLIENT_KEY")
    client_secret = env.get("TIKTOK_CLIENT_SECRET")
    if not client_key or not client_secret:
        sys.exit("TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET missing from .env.")

    state = secrets.token_urlsafe(16)
    auth_url = "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
        "client_key": client_key,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "disable_auto_auth": 1,
    })

    print("\n1) Open this link in your browser, log in as @recrea8_, and approve ALL permissions:\n")
    print(auth_url)
    print("\n2) You'll land on recrea8.one. Copy the FULL address from the browser bar")
    print("   (it starts with https://recrea8.one/?code=...) and paste it here.\n")
    redirected = input("Paste URL: ").strip()

    params = parse_qs(urlparse(redirected).query)  # parse_qs URL-decodes the code
    if "error" in params:
        sys.exit(f"TikTok returned an error: {params.get('error')} {params.get('error_description')}")
    if params.get("state", [""])[0] != state:
        sys.exit("State mismatch. Start over and use the link from THIS run.")
    code = params.get("code", [""])[0]
    if not code:
        sys.exit("No code found in that URL. Make sure you copied the whole address.")

    resp = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    data = resp.json()
    refresh = data.get("refresh_token")
    if not refresh:
        sys.exit(f"Token exchange failed: {data}")

    granted = data.get("scope", "")
    print(f"\nGranted scopes: {granted}")
    if "video.upload" not in granted:
        print("WARNING: video.upload was NOT granted. Re-run and make sure it's approved.")

    lines = ENV_PATH.read_text().splitlines()
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith("TIKTOK_REFRESH_TOKEN="):
            lines[i] = f"TIKTOK_REFRESH_TOKEN={refresh}"
            replaced = True
    if not replaced:
        lines.append(f"TIKTOK_REFRESH_TOKEN={refresh}")
    ENV_PATH.write_text("\n".join(lines) + "\n")
    print("Saved the new refresh token to .env.")


if __name__ == "__main__":
    main()