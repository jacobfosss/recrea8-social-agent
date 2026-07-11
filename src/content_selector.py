"""
Decides what gets posted this run — one of three content types:
- "library": an unused item from content/library/
- "educational": a research-backed post from data/research_queue.json
- "lifestyle": a freshly generated on-brand quote/graphic card
Weighted by config.posting.content_mix, but always falls back gracefully if
a given source has nothing available.
Keeps data/posted_log.json so nothing repeats.
"""
import json
import random
from datetime import datetime
from pathlib import Path

from . import content_generator, performance_analyzer, research_agent, style_analyzer, video_builder

ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = ROOT / "content" / "library"
LOG_PATH = ROOT / "data" / "posted_log.json"

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTS = {".mp4", ".mov"}

DEFAULT_MIX = {"library": 0.25, "educational": 0.45, "lifestyle": 0.30}


def _load_log():
    if LOG_PATH.exists():
        return json.loads(LOG_PATH.read_text())
    return {"posted_files": []}


def _save_log(log):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, indent=2))


def _unused_library_items(log):
    if not LIBRARY_DIR.exists():
        return []
    posted = set(log["posted_files"])
    items = []
    for f in LIBRARY_DIR.iterdir():
        if f.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS and f.name not in posted:
            items.append(f)
    return items


def _weighted_topic_choice(topics, insights_detail):
    """Pick a topic, biasing toward ones that have historically scored higher.
    Falls back to plain random when there isn't enough data yet."""
    topic_scores = insights_detail.get("topics", {}) if insights_detail else {}
    if not topic_scores:
        return random.choice(topics)
    baseline = 1.0
    weights = [max(topic_scores.get(t, 0), 0) + baseline for t in topics]
    return random.choices(topics, weights=weights, k=1)[0]


def _pick_content_type(config, has_library_candidates, has_research_item):
    mix = dict(DEFAULT_MIX)
    mix.update(config.get("posting", {}).get("content_mix", {}))

    available = {"lifestyle": mix.get("lifestyle", 0.3)}
    if has_library_candidates:
        available["library"] = mix.get("library", 0.25)
    if has_research_item:
        available["educational"] = mix.get("educational", 0.45)

    types = list(available.keys())
    weights = list(available.values())
    return random.choices(types, weights=weights, k=1)[0]


def _build_library_post(chosen, config, insights_summary):
    media_type = "video" if chosen.suffix.lower() in VIDEO_EXTS else "image"
    topic = chosen.stem.replace("_", " ")
    caption = content_generator.generate_caption_and_text(
        topics=[topic],
        brand_voice=config.get("brand_voice", ""),
        hashtag_count=config.get("posting", {}).get("hashtag_count", 5),
        max_words=config.get("posting", {}).get("caption_max_words", 60),
        performance_insights=insights_summary,
        brand_context=config.get("brand_context", ""),
    )[1]
    return {"media_path": chosen, "media_type": media_type, "caption": caption,
            "source": "library", "topic": topic}


def _build_educational_post(item, config):
    as_video = config.get("content_generation", {}).get("educational_as_video", False)
    if as_video:
        script_lines = [item["card_text"]] + item["caption"].split(". ")[:2]
        media_path = video_builder.build_narrated_video(script_lines, filename_hint="educational")
        media_type = "video"
    else:
        media_path = content_generator.render_graphic_card(
            item["card_text"],
            style_description=config.get("content_generation", {}).get("image_style", ""),
        )
        media_type = "image"

    research_agent.mark_used(item["pmid"])
    return {"media_path": media_path, "media_type": media_type, "caption": item["caption"],
            "source": "educational", "topic": item["topic"]}


def _build_lifestyle_post(config, insights_summary, insights_detail, pillar_label=None):
    topics = config.get("topics", ["general"])
    topic = _weighted_topic_choice(topics, insights_detail)
    style_guide = style_analyzer.load_style_summary()
    brand_context = config.get("brand_context", "")
    if pillar_label:
        brand_context = f"{brand_context}\nToday's content theme: {pillar_label}".strip()
    result = content_generator.generate_new_post(
        topics=[topic],
        brand_voice=config.get("brand_voice", ""),
        hashtag_count=config.get("posting", {}).get("hashtag_count", 5),
        max_words=config.get("posting", {}).get("caption_max_words", 60),
        style=(config.get("content_generation", {}).get("image_style", "") + " " + style_guide).strip(),
        performance_insights=insights_summary,
        brand_context=brand_context,
    )
    result["source"] = "lifestyle"
    result["topic"] = topic
    return result


def _todays_pillar(config):
    weekday_name = datetime.now().strftime("%A").lower()
    return config.get("content_calendar", {}).get(weekday_name)


def select_content(config):
    """Returns a dict: {media_path, media_type, caption, source, topic}"""
    log = _load_log()
    mode = config.get("posting", {}).get("mode", "auto")
    pillar = _todays_pillar(config)

    insights_summary = performance_analyzer.load_summary()
    insights_detail = {}
    insights_path = ROOT / "data" / "performance_insights.json"
    if insights_path.exists():
        insights_detail = json.loads(insights_path.read_text()).get("detail", {})

    if mode == "library_only":
        candidates = _unused_library_items(log)
        if candidates:
            result = _build_library_post(random.choice(candidates), config, insights_summary)
            log["posted_files"].append(result["media_path"].name)
            _save_log(log)
            return result
        # fall through to lifestyle if library is empty

    library_candidates = _unused_library_items(log)
    research_item = research_agent.get_next_unused_item()

    if pillar and pillar.get("content_type") == "library" and not library_candidates:
        pillar = None  # can't honor it, fall back to normal weighting
    if pillar and pillar.get("content_type") == "educational" and not research_item:
        pillar = None

    content_type = (
        pillar["content_type"] if pillar
        else _pick_content_type(config, bool(library_candidates), bool(research_item))
    )
    pillar_label = pillar["pillar"] if pillar else None

    if content_type == "library":
        result = _build_library_post(random.choice(library_candidates), config, insights_summary)
        log["posted_files"].append(result["media_path"].name)
    elif content_type == "educational":
        result = _build_educational_post(research_item, config)
        log["posted_files"].append(str(result["media_path"].name))
    else:
        result = _build_lifestyle_post(config, insights_summary, insights_detail, pillar_label)
        log["posted_files"].append(str(result["media_path"].name))

    if pillar_label:
        result["pillar"] = pillar_label

    _save_log(log)
    return result
