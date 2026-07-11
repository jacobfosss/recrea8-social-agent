"""
Builds a short vertical (1080x1920) narrated video from a list of script
lines: for each line, a Ken Burns-style slow zoom/pan on a photo (or on-brand
color card if no photo), a Piper voiceover, and animated word-by-word
captions timed proportionally to each word's share of the line's audio
duration (a reliable, simple approximation — true phoneme alignment exists
in Piper's output but word-boundary mapping from it is fragile; this
proportional approach is what most auto-caption tools effectively use too).

Optional: drop a track into content/music/background.mp3 yourself, or set
JAMENDO_CLIENT_ID to pull a real Creative Commons track automatically via
music_library.py. Silent if neither is available — never blocks the pipeline.
"""
import random
from pathlib import Path

from moviepy import (
    AudioFileClip, CompositeAudioClip, CompositeVideoClip,
    ImageClip, concatenate_audioclips, concatenate_videoclips,
)
from PIL import Image, ImageDraw, ImageFont

from . import branding, music_library, stock_photo, voiceover_generator
from .content_generator import render_graphic_card

ROOT = Path(__file__).resolve().parent.parent
VIDEO_OUT_DIR = ROOT / "content" / "generated" / "video"
CAPTION_FRAMES_DIR = ROOT / "content" / "generated" / "caption_frames"
MUSIC_PATH = ROOT / "content" / "music" / "background.mp3"

SIZE = (1080, 1920)
ZOOM_PER_SECOND = 0.03  # subtle Ken Burns zoom, not dizzying


def _caption_frame(word: str, size=SIZE) -> Path:
    """Renders one word as a bold centered caption card (transparent bg)."""
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_path = branding.get_font_path()
    font = ImageFont.truetype(font_path, 100) if font_path else ImageFont.load_default()

    bbox = draw.textbbox((0, 0), word, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = (size[0] - w) / 2, size[1] * 0.78 - h / 2

    for dx, dy in [(-3, 0), (3, 0), (0, -3), (0, 3)]:
        draw.text((x + dx, y + dy), word, font=font, fill=(0, 0, 0, 220))
    draw.text((x, y), word, font=font, fill=(255, 255, 255, 255))

    CAPTION_FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    out = CAPTION_FRAMES_DIR / f"cap_{random.randint(0,10**9)}.png"
    img.save(out)
    return out


def _word_timings(text: str, total_duration: float):
    """Splits total_duration across words proportionally to word length."""
    words = text.split()
    if not words:
        return []
    weights = [len(w) + 1 for w in words]
    total_weight = sum(weights)
    timings = []
    t = 0.0
    for word, weight in zip(words, weights):
        dur = total_duration * (weight / total_weight)
        timings.append((word, t, dur))
        t += dur
    return timings


def _ken_burns_clip(image_path, duration, size=SIZE):
    """Slow zoom on a static image for a less static, more native-feeling scene."""
    clip = ImageClip(str(image_path)).with_duration(duration)
    zoom = lambda t: 1 + ZOOM_PER_SECOND * t
    clip = clip.resized(zoom).with_position(("center", "center"))
    return CompositeVideoClip([clip], size=size).with_duration(duration)


def build_narrated_video(script_lines: list, filename_hint: str = "narrated",
                          photo_query: str = None, music_mood: str = "calm") -> Path:
    VIDEO_OUT_DIR.mkdir(parents=True, exist_ok=True)
    scene_clips = []

    for i, line in enumerate(script_lines):
        audio_path = voiceover_generator.generate_voiceover(line, f"{filename_hint}_scene{i}")
        audio_clip = AudioFileClip(str(audio_path))
        duration = max(audio_clip.duration + 0.4, 1.5)

        bg_photo = stock_photo.search_and_download(photo_query) if photo_query else None
        if bg_photo:
            base_clip = _ken_burns_clip(bg_photo, duration)
        else:
            card_path = render_graphic_card(line, style_description="", size=SIZE)
            base_clip = _ken_burns_clip(card_path, duration)

        caption_layers = [base_clip]
        for word, start, dur in _word_timings(line, audio_clip.duration):
            frame_path = _caption_frame(word)
            word_clip = (
                ImageClip(str(frame_path))
                .with_start(start)
                .with_duration(dur)
            )
            caption_layers.append(word_clip)

        scene = CompositeVideoClip(caption_layers, size=SIZE).with_duration(duration).with_audio(audio_clip)
        scene_clips.append(scene)

    video = concatenate_videoclips(scene_clips, method="compose")

    music_path = MUSIC_PATH if MUSIC_PATH.exists() else music_library.get_track(music_mood)
    if music_path:
        music = AudioFileClip(str(music_path)).with_volume_scaled(0.15)
        if music.duration < video.duration:
            loops = int(video.duration // music.duration) + 1
            music = concatenate_audioclips([music] * loops)
        music = music.subclipped(0, video.duration)
        combined_audio = CompositeAudioClip([video.audio, music])
        video = video.with_audio(combined_audio)

    out_path = VIDEO_OUT_DIR / f"{filename_hint}_{random.randint(1000,9999)}.mp4"
    video.write_videofile(str(out_path), fps=30, codec="libx264", audio_codec="aac", logger=None)
    return out_path


if __name__ == "__main__":
    p = build_narrated_video([
        "Ultra-processed doesn't have to mean ultra-compromised.",
        "Real ingredients. Real flavor. Zero fake stuff.",
    ], "demo")
    print(f"Wrote {p}")
