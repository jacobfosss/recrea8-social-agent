"""
Generates new content when nothing suitable exists in content/library/.
- Uses Claude to write a caption + a short quote/text for a graphic.
- Uses Pillow to render an on-brand image card: real licensed stock
  photography (via stock_photo.py) as the base when available, your own
  logo/font (via branding.py) if you've provided them, and a graceful
  fallback to a solid-color card if neither is set up yet.
"""
import os
import random
import textwrap
from pathlib import Path

from anthropic import Anthropic
from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import branding, stock_photo

MODEL = "claude-sonnet-5"  # swap to "claude-haiku-4-5-20251001" for a cheaper/faster option

GENERATED_DIR = Path(__file__).resolve().parent.parent / "content" / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def _client() -> Anthropic:
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def generate_caption_and_text(topics, brand_voice, hashtag_count=5, max_words=60,
                               performance_insights="", brand_context=""):
    """Ask Claude for a short on-image quote/text plus a full social caption."""
    topic = random.choice(topics)
    client = _client()
    insights_block = (
        f"\nWhat's worked well in past posts (use this to inform tone/length/angle, "
        f"but don't force-mention it): {performance_insights}\n"
        if performance_insights else ""
    )
    context_block = f"\nBrand context: {brand_context}\n" if brand_context else ""
    prompt = f"""You are writing social media content for a brand.

Brand voice: {brand_voice}
{context_block}Topic for this post: {topic}
{insights_block}
Return exactly two parts, separated by "---":
1. A short punchy line (under 12 words) to put ON an image card, about this topic.
2. A full Instagram/TikTok caption (under {max_words} words) expanding on it,
   ending with {hashtag_count} relevant hashtags.

No preamble, no labels, just the two parts separated by "---".
"""
    resp = client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    parts = text.split("---")
    card_text = parts[0].strip()
    caption = parts[1].strip() if len(parts) > 1 else card_text
    return card_text, caption


def _apply_bottom_gradient(img: Image.Image) -> Image.Image:
    """Darkens the lower portion of a photo so white text stays legible."""
    w, h = img.size
    overlay = Image.new("L", (1, h), 0)
    for y in range(h):
        t = max(0, (y - h * 0.35) / (h * 0.65))
        overlay.putpixel((0, y), int(200 * (t ** 1.5)))
    overlay = overlay.resize((w, h))
    black = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    black.putalpha(overlay)
    return Image.alpha_composite(img.convert("RGBA"), black).convert("RGB")


def render_graphic_card(card_text, style_description, size=(1080, 1350), photo_query=None):
    """Renders an on-brand image card. Uses a real stock photo background when
    a PEXELS_API_KEY is configured and photo_query is given; otherwise falls
    back to a solid on-brand color, so this never blocks the pipeline."""
    bg_photo_path = stock_photo.search_and_download(photo_query) if photo_query else None

    if bg_photo_path:
        photo = Image.open(bg_photo_path).convert("RGB")
        photo = ImageOps.fit(photo, size, Image.LANCZOS)
        img = _apply_bottom_gradient(photo)
        text_color = (255, 255, 255)
        text_anchor_bottom = True
    else:
        bg_colors = [(24, 24, 27), (30, 41, 59), (55, 48, 84), (20, 60, 60)]
        img = Image.new("RGB", size, random.choice(bg_colors))
        text_color = (245, 245, 245)
        text_anchor_bottom = False

    draw = ImageDraw.Draw(img)
    font_path = branding.get_font_path()
    font_size = 68
    font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

    wrapped = textwrap.fill(card_text, width=20)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=12)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size[0] - text_w) / 2
    y = (size[1] - text_h - 140) if text_anchor_bottom else (size[1] - text_h) / 2
    draw.multiline_text((x, y), wrapped, font=font, fill=text_color,
                         align="center", spacing=12)

    logo_path = branding.get_logo_path()
    if logo_path:
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((150, 150))
        img = img.convert("RGBA")
        img.paste(logo, (size[0] - logo.width - 50, size[1] - logo.height - 50), logo)
        img = img.convert("RGB")

    out_path = GENERATED_DIR / f"card_{random.randint(100000, 999999)}.png"
    img.save(out_path)
    return out_path


def generate_new_post(topics, brand_voice, hashtag_count=5, max_words=60, style="",
                       performance_insights="", brand_context=""):
    card_text, caption = generate_caption_and_text(
        topics, brand_voice, hashtag_count, max_words, performance_insights, brand_context
    )
    topic = topics[0] if topics else "healthy food"
    image_path = render_graphic_card(card_text, style, photo_query=topic)
    return {"media_path": image_path, "media_type": "image", "caption": caption}
