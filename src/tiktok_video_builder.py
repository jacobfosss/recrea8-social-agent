"""
Builds a TikTok-ready narrated video from content ALREADY generated for
Instagram — the branded carousel slides or the lifestyle card. Rather than
creating separate TikTok-only content, this repurposes what's already been
designed: each image gets a slow Ken Burns zoom and a real Piper voiceover
reading its actual text, stitched into one video with optional background
music. This means every improvement to the Instagram content (better
copy, the branded mark, real product photos) automatically improves what
TikTok gets too, since it's the same underlying content.
"""
import random
from pathlib import Path

from moviepy import (
    AudioFileClip, CompositeAudioClip, CompositeVideoClip,
    ImageClip, concatenate_audioclips, concatenate_videoclips,
)

from . import music_library, voiceover_generator

ROOT = Path(__file__).resolve().parent.parent
VIDEO_OUT_DIR = ROOT / "content" / "generated" / "tiktok_video"
MUSIC_PATH = ROOT / "content" / "music" / "background.mp3"

SIZE = (1080, 1920)  # TikTok's vertical format — different from the 1080x1350 feed size
ZOOM_PER_SECOND = 0.008   # much gentler — these are branded cards with text/
                           # logo positioned near the edges, not open photography,
                           # so aggressive zoom was cropping content that matters
MAX_ZOOM = 1.06            # hard ceiling regardless of clip duration


def _ken_burns_clip(image_path, duration, size=SIZE):
    clip = ImageClip(str(image_path)).with_duration(duration)
    zoom = lambda t: min(1 + ZOOM_PER_SECOND * t, MAX_ZOOM)
    clip = clip.resized(zoom).with_position(("center", "center"))
    return CompositeVideoClip([clip], size=size).with_duration(duration)


def build_tiktok_video_from_content(image_paths: list, narration_texts: list,
                                      filename_hint: str = "tiktok",
                                      music_mood: str = "calm") -> Path:
    """image_paths and narration_texts must be the same length and in the
    same order — each image gets narrated with its corresponding text."""
    if len(image_paths) != len(narration_texts):
        raise ValueError(
            f"image_paths ({len(image_paths)}) and narration_texts "
            f"({len(narration_texts)}) must be the same length"
        )

    VIDEO_OUT_DIR.mkdir(parents=True, exist_ok=True)

    audio_paths = voiceover_generator.generate_voiceover_batch(
        texts=narration_texts,
        filename_hints=[f"{filename_hint}_scene{i}" for i in range(len(narration_texts))],
    )

    scene_clips = []
    for image_path, audio_path in zip(image_paths, audio_paths):
        audio_clip = AudioFileClip(str(audio_path))
        duration = max(audio_clip.duration + 0.5, 1.8)

        base_clip = _ken_burns_clip(image_path, duration)
        scene = base_clip.with_audio(audio_clip)
        scene_clips.append(scene)

    video = concatenate_videoclips(scene_clips, method="compose")

    music_path = MUSIC_PATH if MUSIC_PATH.exists() else music_library.get_track(music_mood)
    if music_path:
        music = AudioFileClip(str(music_path)).with_volume_scaled(0.12)
        if music.duration < video.duration:
            loops = int(video.duration // music.duration) + 1
            music = concatenate_audioclips([music] * loops)
        music = music.subclipped(0, video.duration)
        combined_audio = CompositeAudioClip([video.audio, music])
        video = video.with_audio(combined_audio)

    out_path = VIDEO_OUT_DIR / f"{filename_hint}_{random.randint(1000, 9999)}.mp4"
    video.write_videofile(str(out_path), fps=30, codec="libx264", audio_codec="aac", logger=None)
    return out_path


def build_music_slideshow_from_content(image_paths: list, filename_hint: str = "slideshow",
                                         music_mood: str = "upbeat",
                                         seconds_per_slide: float = 3.5) -> Path:
    """Same branded carousel slides, no narration — just each slide held for
    a fixed duration with a song playing underneath, like a native TikTok/
    Reels slideshow. No voiceover calls at all, so this is both simpler and
    cheaper than the narrated version. Reuses the exact same slide images
    the educational carousel already generated for Instagram — same hook,
    facts, brand tie-in, and source slide, just a different TikTok
    treatment (music instead of narration)."""
    VIDEO_OUT_DIR.mkdir(parents=True, exist_ok=True)

    # give the source/citation slide (last one) a bit longer, since it has
    # more to read and no voice guiding the pace
    scene_clips = []
    for i, image_path in enumerate(image_paths):
        is_last = (i == len(image_paths) - 1)
        duration = seconds_per_slide + 1.5 if is_last else seconds_per_slide
        scene_clips.append(_ken_burns_clip(image_path, duration))

    video = concatenate_videoclips(scene_clips, method="compose")

    music_path = MUSIC_PATH if MUSIC_PATH.exists() else music_library.get_track(music_mood)
    if music_path:
        music = AudioFileClip(str(music_path)).with_volume_scaled(0.5)  # louder — no
                                                                          # voice competing for attention
        if music.duration < video.duration:
            loops = int(video.duration // music.duration) + 1
            music = concatenate_audioclips([music] * loops)
        music = music.subclipped(0, video.duration)
        video = video.with_audio(music)

    out_path = VIDEO_OUT_DIR / f"{filename_hint}_{random.randint(1000, 9999)}.mp4"
    video.write_videofile(str(out_path), fps=30, codec="libx264", audio_codec="aac", logger=None)
    return out_path