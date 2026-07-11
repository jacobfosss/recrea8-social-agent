"""
Turns a folder of reference images (screenshots YOU save of accounts/posts you
admire — content/style_references/) into a reusable style guide.

IMPORTANT — what this deliberately does NOT do: it does not scrape Instagram
or TikTok, and it does not download or reuse anyone else's images, video, or
voiceovers. Automated scraping violates both platforms' Terms of Service, and
reusing someone else's creative work is a copyright problem regardless of
intent. This only reads images YOU have chosen to save locally, and asks
Claude to describe the *style* (colors, layout, tone, mood) in words — never
to reproduce or closely imitate the specific artwork.

Usage: drop a handful of reference screenshots into content/style_references/,
then run this to (re)generate data/style_guide.json.
"""
import base64
import json
import mimetypes
from pathlib import Path

from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
REFERENCES_DIR = ROOT / "content" / "style_references"
STYLE_GUIDE_PATH = ROOT / "data" / "style_guide.json"

MODEL = "claude-sonnet-5"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _client():
    import os
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _describe_image(client, image_path: Path) -> str:
    media_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    b64 = base64.b64encode(image_path.read_bytes()).decode()

    prompt = (
        "This is a reference image saved for aesthetic inspiration only — not "
        "to be copied or closely imitated. Describe its VISUAL STYLE in "
        "general, reusable terms: color palette, layout/composition pattern, "
        "typography feel, mood/tone, lighting. Do not describe specific "
        "subjects, logos, faces, or brand elements verbatim — only the "
        "transferable style qualities. 3-4 sentences max."
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def build_style_guide():
    if not REFERENCES_DIR.exists():
        REFERENCES_DIR.mkdir(parents=True, exist_ok=True)

    images = [p for p in REFERENCES_DIR.iterdir() if p.suffix.lower() in IMAGE_EXTS]
    if not images:
        _write({"summary": "", "per_image_notes": []})
        print("[style] no reference images found in content/style_references/")
        return

    client = _client()
    notes = []
    for img in images:
        try:
            notes.append(_describe_image(client, img))
        except Exception as e:
            print(f"[style] failed on {img.name}: {e}")

    # Synthesize the individual notes into one reusable style summary
    synth_prompt = (
        "Here are separate style descriptions of several reference images:\n\n"
        + "\n---\n".join(notes)
        + "\n\nSynthesize these into ONE cohesive style guide paragraph "
          "(colors, layout tendencies, typography, mood, overall aesthetic) "
          "that a designer could follow to create NEW, original content with "
          "a similar feel. General principles only, nothing image-specific."
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": synth_prompt}],
    )
    summary = "".join(b.text for b in resp.content if b.type == "text")

    _write({"summary": summary, "per_image_notes": notes})
    print(f"[style] built style guide from {len(images)} reference image(s)")


def _write(data):
    STYLE_GUIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STYLE_GUIDE_PATH.write_text(json.dumps(data, indent=2))


def load_style_summary() -> str:
    if STYLE_GUIDE_PATH.exists():
        return json.loads(STYLE_GUIDE_PATH.read_text()).get("summary", "")
    return ""


if __name__ == "__main__":
    build_style_guide()
