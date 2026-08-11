"""
Generates new content when nothing suitable exists in content/library/.
- Uses Claude to write a caption + a short quote/text for a graphic.
- Uses Pillow to render an on-brand image card: real licensed stock
  photography (via stock_photo.py) as the base when available, your own
  logo/font (via branding.py) if you've provided them, and a graceful
  fallback to a solid-color card if neither is set up yet.
- Educational carousels use a dedicated on-brand template (see
  generate_educational_carousel) built around the packaging's nested-8 mark
  instead of stock photography, since stock photos can't reliably match
  abstract scientific claims.
"""
import json
import os
import random
import re
import textwrap
from pathlib import Path

from anthropic import Anthropic
from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import branding, stock_photo

MODEL = "claude-sonnet-5"  # swap to "claude-haiku-4-5-20251001" for a cheaper/faster option

GENERATED_DIR = Path(__file__).resolve().parent.parent / "content" / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)
PRODUCT_PHOTOS_DIR = Path(__file__).resolve().parent.parent / "content" / "product_photos"
PRODUCT_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
_PHOTO_EXTS = {".jpg", ".jpeg", ".png"}
BRANDING_DIR = Path(__file__).resolve().parent.parent / "content" / "branding"

MARK_BLACK = (7, 7, 7)
GOLD = (196, 154, 74)
CREAM_TEXT = (237, 231, 218)

LOGO_MARK_PATH = BRANDING_DIR / "logo_mark_black.png"
CAROUSEL_CARD_SIZE = (1080, 1350)
CAROUSEL_MARK_WIDTH = 300

_CLINICAL_TRIGGER_WORDS = [
    "sweetener", "allulose", "aspartame", "sucralose", "saccharin",
    "gum", "stabilizer", "emulsifier", "seed oil", "dye", "additive",
    "corn syrup", "carrageenan",
]
_FOOD_FORWARD_FALLBACK_QUERIES = [
    "ice cream scoop", "dessert bowl", "healthy dessert", "ice cream cone",
    "whole foods kitchen", "fresh ingredients",
]

# Minimum acceptable length for a parsed slide — anything shorter than this
# is almost certainly a parsing failure, not real content, and should be
# retried rather than silently rendered as filler.
MIN_SLIDE_TEXT_LENGTH = 40


def _client() -> Anthropic:
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


_INGREDIENT_PHOTO_TERMS = {
    "honey": "honey dripping jar",
    "cacao": "raw cacao beans chocolate",
    "cocoa": "raw cacao beans chocolate",
    "mint": "fresh mint leaves",
    "spirulina": "spirulina powder green",
    "magnesium": "magnesium supplement natural",
    "whey": "whey protein natural",
    "protein": "protein powder natural",
    "amino acid": "protein powder natural",
    "egg yolk": "farm fresh eggs",
    "milk": "fresh whole milk dairy",
    "a2": "grass fed dairy cow",
    "grass-fed": "grass fed dairy cow",
    "grass fed": "grass fed dairy cow",
}


def _food_forward_photo_query(topic: str) -> str:
    """Recrea8's photo searches should always show something genuinely
    connected to the brand — either a specific real ingredient (honey,
    cacao, spirulina, grass-fed dairy, etc.) when the topic is about one,
    the actual product (ice cream) for general/lifestyle topics, or a safe
    food-forward fallback for clinical-sounding 'what's NOT in it' topics.
    Without ingredient-specific matching, topics like 'picnic dessert
    ideas' or 'why we use honey' return generic desserts/drinks that don't
    show anything actually relevant to the brand."""
    topic_lower = (topic or "").lower()

    if any(word in topic_lower for word in _CLINICAL_TRIGGER_WORDS):
        return random.choice(_FOOD_FORWARD_FALLBACK_QUERIES)

    for keyword, photo_term in _INGREDIENT_PHOTO_TERMS.items():
        if keyword in topic_lower:
            return photo_term

    if "ice cream" in topic_lower:
        return topic

    return f"{topic} ice cream"


def generate_caption_and_text(topics, brand_voice, hashtag_count=5, max_words=60,
                               performance_insights="", brand_context=""):
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
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    parts = text.split("---")
    card_text = parts[0].strip()
    caption = parts[1].strip() if len(parts) > 1 else card_text
    return card_text, caption


def _apply_bottom_gradient(img: Image.Image) -> Image.Image:
    w, h = img.size
    overlay = Image.new("L", (1, h), 0)
    for y in range(h):
        t = max(0, (y - h * 0.35) / (h * 0.65))
        overlay.putpixel((0, y), int(200 * (t ** 1.5)))
    overlay = overlay.resize((w, h))
    black = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    black.putalpha(overlay)
    return Image.alpha_composite(img.convert("RGBA"), black).convert("RGB")


def _random_product_photo():
    """Returns a random real photo from the reusable product_photos pool,
    or None if it's empty. Unlike content/library/, these are never marked
    'used' — they're a persistent pool meant to be reused across many
    posts with different text overlays, since a handful of good real
    photos can support far more posts than a single-use library."""
    photos = [p for p in PRODUCT_PHOTOS_DIR.iterdir() if p.suffix.lower() in _PHOTO_EXTS]
    return random.choice(photos) if photos else None


_PRODUCT_VIDEO_EXTS = {".mp4", ".mov"}


def random_product_media():
    """Same pool as _random_product_photo(), but checks for real product
    VIDEO first (a hand scooping, the lid coming off, etc.) before falling
    back to a still photo. Returns (path, is_video). Real product video
    gives both brand accuracy AND motion consistency with the rest of a
    video's real B-roll — a still photo, even with Ken Burns zoom applied,
    visibly breaks rhythm against genuine moving footage elsewhere in the
    same video. Drop any short product video into content/product_photos/
    to use this automatically — no other setup needed."""
    videos = [p for p in PRODUCT_PHOTOS_DIR.iterdir() if p.suffix.lower() in _PRODUCT_VIDEO_EXTS]
    if videos:
        return random.choice(videos), True

    photo = _random_product_photo()
    return (photo, False) if photo else (None, False)


def render_graphic_card(card_text, style_description, size=(1080, 1350), photo_query=None,
                          use_product_photo_pool=True):
    if not card_text or not card_text.strip():
        card_text = "Real ingredients. Real food. Real Recrea8."

    # Priority 1: a real product photo, if you've uploaded any — preferred
    # for content ABOUT the product (lifestyle posts). Skip this entirely
    # for content that needs a SPECIFIC contextual match per image (e.g.
    # creative beats — a line about car engine oil needs an oil photo, not
    # a random shot of your ice cream pint).
    bg_photo_path = _random_product_photo() if use_product_photo_pool else None
    used_real_photo = bg_photo_path is not None

    # Priority 2: Pexels stock photo (Claude-curated), only if no real
    # photo is available and a search topic was given.
    if not bg_photo_path and photo_query:
        bg_photo_path = stock_photo.search_and_download(photo_query, brand_aesthetic=style_description)

    if bg_photo_path:
        photo = Image.open(bg_photo_path)
        photo = ImageOps.exif_transpose(photo)  # respect camera/phone rotation metadata —
        photo = photo.convert("RGB")             # without this, some photos load sideways
        photo = ImageOps.fit(photo, size, Image.LANCZOS)
        img = _apply_bottom_gradient(photo)
        text_color = (255, 255, 255)
        text_anchor_bottom = True
    else:
        # Priority 3: solid color fallback — never blocks the pipeline
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
    image_path = render_graphic_card(card_text, style, photo_query=_food_forward_photo_query(topic))
    return {"media_path": image_path, "media_type": "image", "caption": caption, "card_text": card_text}


# --------------------------------------------------------------------------
# Educational carousel template
# --------------------------------------------------------------------------

def _scaled_mark(target_w=CAROUSEL_MARK_WIDTH):
    mark = Image.open(LOGO_MARK_PATH).convert("RGB")
    scale = target_w / mark.size[0]
    return mark.resize((target_w, int(mark.size[1] * scale)), Image.LANCZOS)


def _carousel_body_font(size):
    font_path = branding.get_font_path()
    return ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()


def _draw_footer(draw, slide_index, total_slides):
    footer_font_path = branding.get_font_path()
    footer_font = ImageFont.truetype(footer_font_path, 30) if footer_font_path else ImageFont.load_default()
    footer_text = f"RECREA8   {slide_index}/{total_slides}"
    draw.text((60, CAROUSEL_CARD_SIZE[1] - 70), footer_text, font=footer_font,
               fill=GOLD, anchor="lm")


def _safe_text_zone(mark_height):
    """The vertical region body text is allowed to occupy — HARD constraint:
    top is always below the mark's bottom edge, bottom always leaves room
    for the footer. Text is never placed outside this zone, regardless of
    how long it is (font size shrinks to fit instead)."""
    mark_bottom = 40 + mark_height
    zone_top = mark_bottom + 50
    zone_bottom = CAROUSEL_CARD_SIZE[1] - 140
    return zone_top, zone_bottom


def _fit_text_in_zone(draw, text, zone_top, zone_bottom, start_font_size=42,
                        min_font_size=26, wrap_width=32):
    """Shrinks font size until the wrapped text block's height fits entirely
    within [zone_top, zone_bottom]. Guarantees the text can never overlap
    the logo mark, no matter how long the content is."""
    font_size = start_font_size
    while font_size >= min_font_size:
        font = _carousel_body_font(font_size)
        this_wrap_width = wrap_width + int((start_font_size - font_size) * 0.6)
        wrapped = textwrap.fill(text, width=this_wrap_width)
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=14)
        th = bbox[3] - bbox[1]
        if th <= (zone_bottom - zone_top):
            return wrapped, font, bbox
        font_size -= 2

    font = _carousel_body_font(min_font_size)
    wrapped = textwrap.fill(text, width=wrap_width + 20)
    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=14)
    return wrapped, font, bbox


def _build_content_slide(text: str, slide_index: int, total_slides: int) -> Path:
    img = Image.new("RGB", CAROUSEL_CARD_SIZE, MARK_BLACK)
    mark = _scaled_mark()
    img.paste(mark, (CAROUSEL_CARD_SIZE[0] - mark.size[0] - 40, 40))
    draw = ImageDraw.Draw(img)

    zone_top, zone_bottom = _safe_text_zone(mark.size[1])
    wrapped, font, bbox = _fit_text_in_zone(draw, text, zone_top, zone_bottom)

    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (CAROUSEL_CARD_SIZE[0] - tw) / 2
    y = zone_top + ((zone_bottom - zone_top) - th) / 2
    draw.multiline_text((x, y), wrapped, font=font, fill=CREAM_TEXT, align="center", spacing=14)

    _draw_footer(draw, slide_index, total_slides)

    out_path = GENERATED_DIR / f"carousel_{random.randint(100000, 999999)}.png"
    img.save(out_path)
    return out_path


def _build_source_slide(title: str, journal: str, year: str,
                          slide_index: int, total_slides: int) -> Path:
    img = Image.new("RGB", CAROUSEL_CARD_SIZE, MARK_BLACK)
    mark = _scaled_mark()
    img.paste(mark, (CAROUSEL_CARD_SIZE[0] - mark.size[0] - 40, 40))
    draw = ImageDraw.Draw(img)

    footer_font_path = branding.get_font_path()
    label_font = ImageFont.truetype(footer_font_path, 34) if footer_font_path else ImageFont.load_default()
    draw.text((CAROUSEL_CARD_SIZE[0] / 2, 480), "SOURCE", font=label_font,
               fill=GOLD, anchor="mm", align="center")

    title_font = _carousel_body_font(46)
    wrapped_title = textwrap.fill(title, width=28)
    bbox = draw.multiline_textbbox((0, 0), wrapped_title, font=title_font, spacing=10)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.multiline_text(((CAROUSEL_CARD_SIZE[0] - tw) / 2, 560), wrapped_title,
                         font=title_font, fill=CREAM_TEXT, align="center", spacing=10)

    meta_font = ImageFont.truetype(footer_font_path, 32) if footer_font_path else ImageFont.load_default()
    meta_text = f"{journal}, {year}"
    wrapped_meta = textwrap.fill(meta_text, width=42)
    title_bottom = 560 + th  # actual bottom edge of the title block above
    draw.multiline_text((CAROUSEL_CARD_SIZE[0] / 2, title_bottom + 50), wrapped_meta,
                         font=meta_font, fill=GOLD, anchor="ma", align="center", spacing=8)

    _draw_footer(draw, slide_index, total_slides)

    out_path = GENERATED_DIR / f"carousel_{random.randint(100000, 999999)}.png"
    img.save(out_path)
    return out_path


def _clean_slide_part(raw: str) -> str:
    """Strips numbering/labels Claude sometimes adds despite instructions
    (e.g. '1.', '2)', 'THE MECHANISM:') so parsing isn't thrown off by them."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^\d+[\.\)]\s*", "", cleaned)
    cleaned = re.sub(r"^[A-Z \-]{3,40}:\s*", "", cleaned)
    return cleaned.strip()


def _parse_dash_separated(text: str) -> list:
    raw_parts = [p for p in text.split("---") if p.strip()]
    parts = [_clean_slide_part(p) for p in raw_parts]
    return [p for p in parts if len(p) >= MIN_SLIDE_TEXT_LENGTH]


def _parse_numbered_list(text: str) -> list:
    """Fallback parsing strategy: some Claude responses come back as a
    numbered list (1. ... 2. ... 3. ...) even when asked for '---'
    separators. Try splitting on numbered-line boundaries instead."""
    lines = re.split(r"\n\s*\d+[\.\)]\s*", "\n" + text.strip())
    parts = [_clean_slide_part(p) for p in lines if p.strip()]
    return [p for p in parts if len(p) >= MIN_SLIDE_TEXT_LENGTH]


def _request_slides_as_json(research_item: dict, brand_voice: str, brand_context: str) -> list:
    """Last-resort strategy before falling back to generic text: ask for
    strict JSON output instead of a delimiter-separated format. JSON is
    far more reliably parseable than hoping a text delimiter survives
    formatting quirks."""
    client = _client()
    prompt = f"""Write 3 slides for an educational Instagram carousel about
this study for a nutrition brand. Hook slide (already written): "{research_item['card_text']}"
Study summary: {research_item['caption']}
Brand voice: {brand_voice}
Brand context: {brand_context}

Slide A = THE MECHANISM (how/why, 1-2 sentences, ~20-30 words, concrete detail)
Slide B = MAKE IT TANGIBLE (a specific number or comparison, 1-2 sentences, ~20-30 words)
Slide C = THE TAKEAWAY (practical + brand tie-in, 1-2 sentences, ~20-30 words)

Respond with ONLY valid JSON, no other text, in exactly this shape:
{{"slide_a": "...", "slide_b": "...", "slide_c": "..."}}
"""
    resp = client.messages.create(model=MODEL, max_tokens=900,
                                   messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(text)
        parts = [data.get("slide_a", ""), data.get("slide_b", ""), data.get("slide_c", "")]
        parts = [_clean_slide_part(p) for p in parts]
        if all(len(p) >= MIN_SLIDE_TEXT_LENGTH for p in parts):
            return parts
    except (json.JSONDecodeError, AttributeError):
        pass
    return []


def _request_carousel_slides(research_item: dict, brand_voice: str, brand_context: str) -> list:
    """Asks Claude for 3 genuinely substantive, multi-sentence slides — real
    'aha moment' content, not generic filler. Tries multiple parsing
    strategies and retries across several attempts before ever falling
    back to generic placeholder text, since that fallback shipping as real
    content is worse than spending a couple extra API calls to get it right."""
    client = _client()

    base_prompt = f"""You're building slides 2-4 of a 4-slide Instagram
educational carousel breaking down a real study for a nutrition-focused
brand. Slide 1 (already written) is this hook: "{research_item['card_text']}"

Full study summary (paraphrase, never quote): {research_item['caption']}

Brand voice: {brand_voice}
Brand context: {brand_context}

Write exactly 3 slides. Each should be 1-2 sentences, roughly 20-30 words —
tight and punchy, genuinely informative, not vague teasers. This video is
narrated aloud, so total length matters: keep every slide concise enough
that the full 5-slide video (including the hook and source citation) lands
around 45-60 seconds when spoken aloud. By the end of slide 4, someone
should walk away having learned a specific, concrete fact they didn't know
before and see food differently. No generic filler like "here's what the
research found" — every slide must state an actual fact, number,
mechanism, or insight, just said more concisely.

Slide 2 — THE MECHANISM: explain HOW or WHY this happens, in plain language,
with a concrete specific detail from the study.
Slide 3 — MAKE IT TANGIBLE: a specific number, comparison, or real-world
example that makes the finding concrete and memorable.
Slide 4 — THE TAKEAWAY: one specific, practical thing to do differently,
connected naturally to why Recrea8 is made the way it is.

Return exactly 3 slides separated by "---". No numbering, no labels, no
preamble — just the 3 slides of actual content.
"""

    for attempt in range(4):
        resp = client.messages.create(model=MODEL, max_tokens=900,
                                       messages=[{"role": "user", "content": base_prompt}])
        text = "".join(b.text for b in resp.content if b.type == "text")

        parts = _parse_dash_separated(text)
        if len(parts) >= 3:
            return parts[:3]

        parts = _parse_numbered_list(text)
        if len(parts) >= 3:
            return parts[:3]

        base_prompt += ("\n\nIMPORTANT: your previous response did not return "
                         "3 clearly separated, substantive slides. Return "
                         "exactly 3 slides separated by the literal text "
                         "'---', each a real 1-3 sentence fact, no shorter "
                         "than a full sentence. No markdown formatting, no "
                         "bold text, no headers.")

    # Structurally different last resort: strict JSON output, which is far
    # more reliable to parse than hoping a text delimiter survives
    json_parts = _request_slides_as_json(research_item, brand_voice, brand_context)
    if json_parts:
        return json_parts

    # Only reached if every strategy genuinely failed across 5 total API
    # calls — extremely rare, and logged loudly since generic filler
    # shipping as real content is a real quality problem, not a shrug
    print("[content_generator] WARNING: carousel slide generation failed "
          "after all retry strategies — using minimal fallback. This "
          "should be rare; if you see this often, check the API response "
          "manually.")
    return [
        "Here's the mechanism behind this finding — worth reading the source study directly for full detail.",
        "The specific numbers behind this are worth a closer look at the source below.",
        "This is exactly the kind of finding that shapes how we choose ingredients at Recrea8.",
    ]


def generate_educational_carousel(research_item: dict, brand_voice: str,
                                    brand_context: str, style: str = "",
                                    photo_query: str = None):
    """Turns one research_agent.py queue item into a 5-slide carousel:
    1. Hook (reuses the item's existing card_text)
    2. The mechanism — how/why, with a concrete detail
    3. Made tangible — a specific number or comparison
    4. The takeaway — practical + brand tie-in
    5. Source citation (title/journal/year only — no reproduced copyrighted
       page layout or screenshot)

    Returns (slide_paths, slide_texts) — the rendered images AND their raw
    text, since the raw text is needed separately for TikTok video
    narration (can't extract text back out of a finished image).
    """
    parts = _request_carousel_slides(research_item, brand_voice, brand_context)
    slide_texts = [research_item["card_text"]] + parts
    total_slides = 5

    slide_paths = []
    for i, slide_text in enumerate(slide_texts, start=1):
        slide_paths.append(_build_content_slide(slide_text, i, total_slides))

    source_path = _build_source_slide(
        title=research_item.get("source_title", "Recent published research"),
        journal=research_item.get("source_journal", ""),
        year=research_item.get("source_year", ""),
        slide_index=5,
        total_slides=total_slides,
    )
    slide_paths.append(source_path)

    source_narration = (
        f"Source: {research_item.get('source_title', 'this study')}, "
        f"published in {research_item.get('source_journal', 'a peer-reviewed journal')} "
        f"in {research_item.get('source_year', '')}."
    )
    slide_texts.append(source_narration)

    return slide_paths, slide_texts


# --------------------------------------------------------------------------
# Creative/entertainment pillar — hook/twist/payoff style video, distinct
# from the informational educational and lifestyle content. This is scripted
# wit delivered through our existing photo+voiceover pipeline — genuine
# live-action stunt production is outside what any free AI pipeline can do,
# but a sharp attention-grabbing structure is fully achievable with text and
# narration alone.
# --------------------------------------------------------------------------

def _salvage_beats_with_regex(raw_text: str) -> list:
    """Last-resort extraction when JSON parsing genuinely fails — pulls out
    "text"/"visual" pairs by pattern matching instead of requiring the
    whole response to be strictly valid JSON. One bad character in one
    field shouldn't sink an otherwise-good response."""
    text_matches = re.findall(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text)
    visual_matches = re.findall(r'"visual"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text)
    if len(text_matches) >= 4 and len(visual_matches) >= 4:
        return [
            {"text": _clean_slide_part(t), "visual": v.strip()}
            for t, v in zip(text_matches[:4], visual_matches[:4])
        ]
    return []


def generate_creative_beats(topic: str, brand_voice: str, brand_context: str):
    """Returns a list of 4 dicts: {"text": ..., "visual": ...} for a hook/
    twist/payoff style video. Each beat includes a specific visual
    suggestion (a short Pexels-searchable phrase, e.g. "cows grazing green
    pasture") describing what should be ON SCREEN during that line —
    without this, every beat in the video shared one generic photo search
    based only on the overall topic, so a line about cows wouldn't
    actually show cows."""
    client = _client()
    prompt = f"""You're writing a short, witty, attention-grabbing video
script for a nutrition/ice cream brand's social media. Topic: {topic}

Brand voice: {brand_voice}
Brand context: {brand_context}

This should NOT sound like an educational post — it should be genuinely
funny, clever, or surprising, the kind of thing that makes someone stop
scrolling because they didn't expect it. Think: a joke, an unexpected
comparison, a relatable bit, a clever twist — NOT a lecture.

Tone guardrail: keep this casual and witty, never clinical or like a lab
report — avoid phrasing that sounds like an unsubstantiated health or
recovery CLAIM (e.g. implying the product treats, cures, or recovers
someone from something). This does NOT mean avoiding science or nutrition
entirely — real research, ingredients, and nutrition facts are fair game
and often the source of the best jokes (like the guar gum/wrestling-move
line) — just keep the delivery relatable and fun, not like reciting a
study.

Write exactly 4 short beats (each under 12 words, punchy, works as spoken
narration over video):
1. HOOK — an unexpected opening line that stops the scroll
2. TWIST — the turn that makes the hook make sense, or subverts it further
3. PAYOFF — the actual point, delivered with the same wit as the hook
4. CTA — a short, confident brand tie-in — NOT "buy now"

For EACH beat, also suggest a specific, filmable visual — a short phrase
(3-6 words) describing what should be ON SCREEN while that line plays,
specific enough to search stock photography with (e.g. "cows grazing green
pasture", "grocery store label closeup", "honey dripping jar"). This must
match what that SPECIFIC line is actually about, not just the general
topic.

IMPORTANT constraint on visuals: NEVER suggest a shot of a person eating,
holding, or scooping ice cream, or any shot showing an ice cream
tub/container/packaging — stock footage for these shows generic or
competitor-branded products, not Recrea8, and that's a real brand problem.
Instead, for beats about the finished product, suggest ingredient-focused
or process-focused visuals instead (e.g. "cream pouring closeup", "honey
drizzle jar", "spoon in fresh cream" — texture/ingredients, not a branded
tub or a bite being taken).

Respond with ONLY valid JSON, no other text, in exactly this shape:
{{"beats": [
  {{"text": "...", "visual": "..."}},
  {{"text": "...", "visual": "..."}},
  {{"text": "...", "visual": "..."}},
  {{"text": "...", "visual": "..."}}
]}}
"""
    fallback = [
        {"text": "Ice cream that doesn't need a confession booth after.", "visual": "ice cream scoop closeup"},
        {"text": "No seed oils. No gums. No regrets.", "visual": "ice cream ingredients label"},
        {"text": "Just real ingredients, doing what they're supposed to.", "visual": "fresh ingredients kitchen"},
        {"text": "Recrea8. Actually good, actually good for you.", "visual": "ice cream cone"},
    ]

    for attempt in range(3):
        resp = client.messages.create(model=MODEL, max_tokens=800,
                                       messages=[{"role": "user", "content": prompt}])
        raw_text = "".join(b.text for b in resp.content if b.type == "text").strip()

        # extract just the {...} substring, robust to any preamble/postamble
        # text or code fences Claude might add despite instructions not to
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        json_candidate = match.group(0) if match else raw_text

        try:
            data = json.loads(json_candidate)
            beats = data.get("beats", [])
            cleaned = [
                {"text": _clean_slide_part(b.get("text", "")), "visual": b.get("visual", "").strip()}
                for b in beats
            ]
            cleaned = [b for b in cleaned if len(b["text"]) >= 5 and b["visual"]]
            if len(cleaned) >= 4:
                return cleaned[:4]
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            if not raw_text:
                print(f"[content_generator] creative beats parse attempt {attempt + 1}: "
                      f"received an empty response from the API (rare, usually transient).")
            else:
                salvaged = _salvage_beats_with_regex(raw_text)
                if salvaged:
                    return salvaged
                print(f"[content_generator] creative beats parse attempt {attempt + 1} "
                      f"failed ({e}). Raw response was:\n{raw_text[:1500]}")

        prompt += ("\n\nIMPORTANT: your previous response did not return valid "
                   "JSON in the exact required shape. Return ONLY the JSON "
                   "object, no preamble, no code fences, no other text.")

    print("[content_generator] WARNING: creative beats generation failed "
          "to parse after 2 attempts — using minimal fallback.")
    return fallback


# --------------------------------------------------------------------------
# Video background for Shotstack-based educational videos — same branded
# signature (nested-8 mark, black/cream/gold) as the Instagram carousel,
# but with NO body text baked in, since Shotstack's captions handle all
# on-screen text now. Optionally overlays a real product/ingredient photo
# at low opacity for depth on select slides.
# --------------------------------------------------------------------------

EDUCATIONAL_BG_PATH = BRANDING_DIR / "educational_background.png"
_prepared_educational_bg_cache = None


def render_video_background(slide_index: int, total_slides: int,
                              glow_photo_path=None, size=(1080, 1920)) -> Path:
    """Returns the finalized fixed background poster for educational videos
    — same image every slide, since Shotstack's captions now carry all the
    changing on-screen text. The source image is already close enough to a
    9:16 aspect ratio that a plain resize is clean, with no visible
    distortion and no padding needed."""
    global _prepared_educational_bg_cache
    if _prepared_educational_bg_cache and _prepared_educational_bg_cache.exists():
        return _prepared_educational_bg_cache

    img = Image.open(EDUCATIONAL_BG_PATH).convert("RGB")
    resized = img.resize(size, Image.LANCZOS)

    out_path = GENERATED_DIR / f"educational_background_prepared_{random.randint(100000, 999999)}.png"
    resized.save(out_path)
    _prepared_educational_bg_cache = out_path
    return out_path