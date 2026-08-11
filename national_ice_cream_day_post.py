"""
One-off script for a special-occasion post (National Ice Cream Day).
Run once with: python3 national_ice_cream_day_post.py
Not part of the regular scheduled pipeline — this is a manual, one-time run.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml
from dotenv import load_dotenv

load_dotenv()

from src import content_generator

ROOT = Path(__file__).resolve().parent
LIBRARY_DIR = ROOT / "content" / "library"
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

config = yaml.safe_load(open("config.yaml"))

# Mission-first framing — not the athlete origin story. That's real
# supporting history, but the lead message here is the whole-food mission.
special_context = (
    "Recrea8 exists to build a genuinely better version of ice cream — "
    "whole food, nothing artificial, made with real ingredients your body "
    "actually recognizes, in service of our broader mission of building a "
    "better food system. That's the whole point: real, whole-food "
    "ingredients and all the benefits real food provides, without giving "
    "up how indulgent ice cream should taste.\n"
    "Today is National Ice Cream Day. This post should feel celebratory "
    "and fun, not just informational — proud of what we made, inviting "
    "people to celebrate with us today."
)

# Prefer a real product photo from content/library if one exists — a
# holiday brand-celebration post should show the actual product, not a
# generic stock/generated image.
library_photos = [
    f for f in LIBRARY_DIR.iterdir()
    if f.suffix.lower() in IMAGE_EXTS
] if LIBRARY_DIR.exists() else []

card_text, caption = content_generator.generate_caption_and_text(
    topics=["National Ice Cream Day"],
    brand_voice=config.get("brand_voice", ""),
    brand_context=special_context,
    hashtag_count=config.get("posting", {}).get("hashtag_count", 5),
    max_words=config.get("posting", {}).get("caption_max_words", 60),
)

if library_photos:
    chosen_photo = random.choice(library_photos)
    print(f"[media] Using real product photo: {chosen_photo}")
    print("[note] Pair this real photo with the caption below manually — "
          "no text overlay needed on your own product photography.")
else:
    print("[media] No real product photos found in content/library/ — "
          "falling back to a generated card. For a holiday brand post, "
          "strongly consider adding a real product photo instead.")
    media_path = content_generator.render_graphic_card(
        card_text,
        style_description=config.get("content_generation", {}).get("image_style", ""),
        photo_query=None,  # force solid-color fallback rather than an unrelated stock photo
    )
    print(f"[media] {media_path}")

print(f"\n[caption]\n{caption}")

