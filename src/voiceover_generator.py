"""
Generates voiceover audio for video scripts using Piper — a free, open-source,
fully offline neural TTS engine (no API key, no per-use cost, no rate limit).

The voice model downloads once (a few MB) from Hugging Face's mirror of
Piper's voices and is cached locally, so subsequent runs are instant and
fully offline.
"""
import urllib.request
from pathlib import Path

from piper import PiperVoice

ROOT = Path(__file__).resolve().parent.parent
VOICES_DIR = ROOT / "data" / "voices"
AUDIO_OUT_DIR = ROOT / "content" / "generated" / "audio"

# A calm, clear, professional default voice. Full voice list:
# https://github.com/rhasspy/piper/blob/master/VOICES.md
DEFAULT_VOICE = "en_US-lessac-medium"
VOICE_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"


def _ensure_voice_downloaded(voice_name: str = DEFAULT_VOICE) -> Path:
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    model_path = VOICES_DIR / f"{voice_name}.onnx"
    config_path = VOICES_DIR / f"{voice_name}.onnx.json"

    if not model_path.exists():
        print(f"[voiceover] downloading voice model '{voice_name}' (one-time, a few MB)...")
        urllib.request.urlretrieve(f"{VOICE_BASE_URL}/en_US-lessac-medium.onnx", model_path)
    if not config_path.exists():
        urllib.request.urlretrieve(f"{VOICE_BASE_URL}/en_US-lessac-medium.onnx.json", config_path)

    return model_path


def generate_voiceover(text: str, filename_hint: str = "voiceover") -> Path:
    """Renders `text` to a WAV file and returns its path."""
    AUDIO_OUT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = _ensure_voice_downloaded()

    voice = PiperVoice.load(str(model_path))
    out_path = AUDIO_OUT_DIR / f"{filename_hint}.wav"

    with open(out_path, "wb") as f:
        voice.synthesize_wav(text, f)

    return out_path


if __name__ == "__main__":
    p = generate_voiceover("This is a test of the voiceover system.", "test")
    print(f"Wrote {p}")
