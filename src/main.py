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

from src import (content_selector, media_host, instagram_poster, tiktok_poster,
                  tiktok_video_builder, approval_workflow, post_history)

ROOT = Path(__file__).resolve().parent.parent


def load_config():
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def _build_tiktok_video(content):
    """Builds a TikTok video from whatever content was already selected
    for Instagram. If the content is already a video (the creative
    pillar), it's shared directly instead of being rebuilt.

    Educational content gets a DEDICATED Shotstack build: fresh branded
    backgrounds with NO baked-in text (the Instagram carousel images have
    text baked in — reusing those here would double up with Shotstack's
    captions), narrated with real per-scene audio, captioned with
    Shotstack's word-synced captions instead of a wall of static text.

    Lifestyle content still uses the older Ken Burns approach — it's a
    single card, not a text-dense carousel, so it isn't affected by the
    same "too much text at once" problem.
    """
    from . import content_generator, shotstack_video_builder, voiceover_generator

    if content["media_type"] == "video":
        return None  # already a video — main() will reuse the same hosted URL for both platforms

    if content["source"] == "educational" and content.get("slide_texts"):
        slide_texts = content["slide_texts"]
        total_slides = len(slide_texts)

        scene_visuals = []
        for i in range(total_slides):
            bg_path = content_generator.render_video_background(
                slide_index=i + 1, total_slides=total_slides,
            )
            scene_visuals.append((bg_path, False))

        scene_audio_paths = voiceover_generator.generate_voiceover_batch(
            texts=slide_texts,
            filename_hints=[f"educational_scene{i}" for i in range(total_slides)],
        )

        return shotstack_video_builder.build_video(
            scene_visuals=scene_visuals,
            scene_audio_paths=scene_audio_paths,
            filename_hint="educational",
            caption_intensity="calm",  # word-synced, not full karaoke bounce —
                                         # matches educational content's calmer tone
            caption_palette="dark_on_light",  # near-black text — the new
                                                # cream background would make
                                                # the old cream text invisible
            use_production=True,  # LIVE — educational is confirmed 10/10
                                    # and ready; creative/lifestyle stay on
                                    # sandbox until they hit the same bar
        )

    if content["media_type"] == "carousel":
        image_paths = content["media_paths"]
        narration_texts = content.get("slide_texts")
        if not narration_texts or len(narration_texts) != len(image_paths):
            narration_texts = [content["caption"]] * len(image_paths)
    else:
        image_paths = [content["media_path"]]
        narration_texts = [content.get("card_text") or content["caption"]]

    return tiktok_video_builder.build_tiktok_video_from_content(
        image_paths=image_paths,
        narration_texts=narration_texts,
        filename_hint=content["source"],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--content-type", choices=["educational", "lifestyle", "library", "creative"],
                         default=None,
                         help="Force a specific content type instead of the weighted-random pick — "
                              "used to guarantee a daily cadence (e.g. one educational + one lifestyle post).")
    parser.add_argument("--scheduled-check", action="store_true",
                         help="For content types with dynamic timing (currently educational): consult "
                              "time_optimizer before generating anything, so the workflow can check in "
                              "several times a day without posting more than once.")
    parser.add_argument("--check-hours", default="8,10,12,14,16,18,20,22",
                         help="Comma-separated UTC hours the workflow checks in at today — used by "
                              "time_optimizer to compute random-phase probability and the end-of-day "
                              "safety fallback.")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    config = load_config()

    if args.scheduled_check and args.content_type == "educational":
        from . import time_optimizer
        from datetime import datetime, timezone

        current_hour = datetime.now(timezone.utc).hour
        check_hours = [int(h) for h in args.check_hours.split(",")]

        if not time_optimizer.should_post_now("educational", current_hour, check_hours):
            print(f"[scheduler] not posting educational this check (hour={current_hour} UTC) — "
                  f"either already posted today, or this isn't the chosen time yet.")
            return

        print(f"[scheduler] posting educational now (hour={current_hour} UTC)")

    content = content_selector.select_content(config, forced_content_type=args.content_type)
    is_carousel = content["media_type"] == "carousel"
    is_already_video = content["media_type"] == "video"

    if is_carousel:
        print(f"[selected] source={content['source']} type=carousel "
              f"slides={len(content['media_paths'])}")
        for p in content["media_paths"]:
            print(f"  - {p}")
    else:
        print(f"[selected] source={content['source']} type={content['media_type']} "
              f"file={content['media_path']}")
    print(f"[caption]\n{content['caption']}\n")

    platforms = config.get("platforms", {})
    tiktok_video_path = None

    if platforms.get("tiktok") and not is_already_video:
        try:
            tiktok_video_path = _build_tiktok_video(content)
            print(f"[tiktok] built narrated video: {tiktok_video_path}")
        except Exception as e:
            print(f"[tiktok] video build FAILED: {e}")

    if args.dry_run:
        print("[dry-run] Not posting anything. Remove --dry-run to post for real.")
        return

    if is_carousel:
        public_urls = [media_host.publish_to_public_url(p) for p in content["media_paths"]]
        print(f"[hosted] {len(public_urls)} slides")
    else:
        public_url = media_host.publish_to_public_url(content["media_path"])
        print(f"[hosted] {public_url}")

    tiktok_public_url = None
    if is_already_video:
        # creative pillar: same video, same hosted URL, both platforms
        tiktok_public_url = public_url
    elif tiktok_video_path:
        tiktok_public_url = media_host.publish_to_public_url(tiktok_video_path)
        print(f"[hosted] tiktok video: {tiktok_public_url}")

    # Creative posts always require approval, regardless of the global
    # setting — this is a standing rule, not just today's default, since
    # humor is much easier to get wrong than education, and it stays true
    # even if you later turn off approval for the well-tested pillars.
    # Approval logic — three tiers, not one global switch:
    # - educational: NEVER requires approval — a standing bypass, since
    #   it's the proven, 10/10 pillar. This holds regardless of the
    #   global setting below.
    # - creative: ALWAYS requires approval — a standing rule from earlier,
    #   since humor is much easier to get wrong than education. This also
    #   holds regardless of the global setting.
    # - everything else (lifestyle, library): follows whatever
    #   posting.require_approval says in config.yaml.
    source = content.get("source")
    if source == "educational":
        needs_approval = False
    elif source == "creative":
        needs_approval = True
    else:
        needs_approval = config.get("posting", {}).get("require_approval", False)

    if needs_approval:
        if is_carousel:
            approval_workflow.create_carousel_approval_request(
                content, public_urls, platforms, tiktok_public_url=tiktok_public_url)
        else:
            approval_workflow.create_approval_request(
                content, public_url, platforms, tiktok_public_url=tiktok_public_url)
        print("[approval] draft created — will publish once you comment 'approve' "
              "on the GitHub issue.")
        return

    if platforms.get("instagram"):
        try:
            if is_carousel:
                post_id = instagram_poster.post_carousel(public_urls, content["caption"])
            else:
                post_id = instagram_poster.post(public_url, content["media_type"], content["caption"])
            print(f"[instagram] posted, id={post_id}")
            post_history.record_post(
                "instagram", post_id, content,
                public_urls[0] if is_carousel else public_url,
            )
        except Exception as e:
            print(f"[instagram] FAILED: {e}")

    if platforms.get("tiktok") and tiktok_public_url:
        try:
            publish_id = tiktok_poster.post_video(tiktok_public_url, content["caption"])
            print(f"[tiktok] submitted, publish_id={publish_id}")
            post_history.record_post("tiktok", publish_id, content, tiktok_public_url)
            if content.get("source") == "educational":
                from . import time_optimizer
                from datetime import datetime, timezone
                time_optimizer.record_scheduled_post(
                    "educational", datetime.now(timezone.utc).hour, post_id=publish_id)
        except Exception as e:
            print(f"[tiktok] FAILED: {e}")


if __name__ == "__main__":
    main()