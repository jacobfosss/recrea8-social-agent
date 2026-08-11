"""
One-off test script for the new Shotstack video builder — run this BEFORE
wiring Shotstack into the main pipeline, to confirm the integration
actually works against the real API.

Uses your SANDBOX key (free, watermarked output) so this costs nothing to
run as many times as needed.

Usage: python3 test_shotstack.py
Auto-discovers the most recent generated images and voiceover audio in
your content/generated/ folder. Or pass specific files:
  python3 test_shotstack.py path/to/image1.png path/to/image2.png --audio path/to/audio.mp3
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv()

from src import shotstack_video_builder

ROOT = Path(__file__).resolve().parent
GENERATED_DIR = ROOT / "content" / "generated"
VOICEOVER_DIR = GENERATED_DIR / "voiceover"


def _most_recent(directory: Path, extensions: set, count: int = 1) -> list:
    if not directory.exists():
        return []
    files = [f for f in directory.iterdir() if f.suffix.lower() in extensions]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files[:count]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="*", help="Specific image paths (optional)")
    parser.add_argument("--audio", help="Specific audio path (optional)")
    args = parser.parse_args()

    if args.images:
        image_paths = [Path(p) for p in args.images]
    else:
        image_paths = _most_recent(GENERATED_DIR, {".png", ".jpg", ".jpeg"}, count=3)
        if not image_paths:
            print("No images found in content/generated/ — generate some first "
                  "(e.g. python3 -m src.main --content-type lifestyle --dry-run), "
                  "or pass image paths directly as arguments.")
            return

    if args.audio:
        audio_path = Path(args.audio)
    else:
        recent_audio = _most_recent(VOICEOVER_DIR, {".mp3", ".wav"}, count=1)
        if not recent_audio:
            print("No audio found in content/generated/voiceover/ — generate some "
                  "first (e.g. python3 -m src.main --content-type creative --dry-run), "
                  "or pass an audio path directly with --audio.")
            return
        audio_path = recent_audio[0]

    print(f"Using {len(image_paths)} image(s):")
    for p in image_paths:
        print(f"  - {p}")
    print(f"Using audio: {audio_path}")
    print()
    print("Submitting to Shotstack SANDBOX (free, watermarked output)...")
    print()

    result = shotstack_video_builder.build_video(
        image_paths=image_paths,
        audio_path=audio_path,
        filename_hint="test_shotstack",
        caption_intensity="energetic",  # word-by-word karaoke style, per your choice
        use_production=False,  # sandbox — free, safe to test repeatedly
    )

    print()
    print(f"DONE. Video saved to: {result}")
    print("Open it and check: captions present? word-by-word working, or did it")
    print("fall back to basic captions? (check the printed output above for a")
    print("fallback warning if so)")


if __name__ == "__main__":
    main()
