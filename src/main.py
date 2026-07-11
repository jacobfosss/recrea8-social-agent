"""
Entry point. Run with:
    python src/main.py            # actually posts
    python src/main.py --dry-run  # selects/generates content and prints what
                                   # would be posted, without calling any
                                   # social API
"""
import argparse
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import content_selector, media_host, instagram_poster, tiktok_poster, approval_workflow, post_history

ROOT = Path(__file__).resolve().parent.parent


def load_config():
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    config = load_config()

    content = content_selector.select_content(config)
    print(f"[selected] source={content['source']} type={content['media_type']} "
          f"file={content['media_path']}")
    print(f"[caption]\n{content['caption']}\n")

    if args.dry_run:
        print("[dry-run] Not posting anything. Remove --dry-run to post for real.")
        return

    public_url = media_host.publish_to_public_url(content["media_path"])
    print(f"[hosted] {public_url}")

    platforms = config.get("platforms", {})

    if config.get("posting", {}).get("require_approval", False):
        approval_workflow.create_approval_request(content, public_url, platforms)
        print("[approval] draft created — will publish once you comment 'approve' "
              "on the GitHub issue.")
        return

    if platforms.get("instagram"):
        try:
            post_id = instagram_poster.post(public_url, content["media_type"], content["caption"])
            print(f"[instagram] posted, id={post_id}")
            post_history.record_post("instagram", post_id, content)
        except Exception as e:
            print(f"[instagram] FAILED: {e}")

    if platforms.get("tiktok") and content["media_type"] == "video":
        try:
            publish_id = tiktok_poster.post_video(public_url, content["caption"])
            print(f"[tiktok] submitted, publish_id={publish_id}")
            post_history.record_post("tiktok", publish_id, content)
        except Exception as e:
            print(f"[tiktok] FAILED: {e}")
    elif platforms.get("tiktok"):
        print("[tiktok] skipped — this piece of content is an image; "
              "TikTok's Content Posting API only accepts video.")


if __name__ == "__main__":
    main()
