"""
Text-to-speech narration. Tries ElevenLabs first (much more natural-
sounding, ~$0.05-0.10 per 1,000 characters — trivial at this app's actual
volume). Falls back automatically to Piper (free, offline, more robotic)
if no ELEVENLABS_API_KEY is set, or if the ElevenLabs call fails.

IMPORTANT: use generate_voiceover_batch() for any multi-scene video, NOT
repeated calls to generate_voiceover(). The provider (ElevenLabs vs Piper)
is decided ONCE per batch and used consistently for every scene — deciding
independently per scene meant a mid-generation credit-cap hit could leave
some scenes on Derek's real voice and others silently on Piper, producing
a jarring voice change partway through a single video.
"""
import os
import wave
from pathlib import Path

import requests

GENERATED_DIR = Path(__file__).resolve().parent.parent / "content" / "generated" / "voiceover"

ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech"
DEFAULT_ELEVENLABS_VOICE_ID = "Q0Et7LOU7VpeoeCRQAVS"  # Derek - Fun & Energetic
# Confirmed real ElevenLabs parameter (0.7-1.2 range, default 1.0). Slightly
# above default tightens pacing/reduces the gap between sentences — the
# "Derek pauses too long" feedback.
ELEVENLABS_SPEED = 1.1

PIPER_VOICE_NAME = "en_US-ryan-high"
PIPER_VOICES_DIR = Path(__file__).resolve().parent.parent / "data" / "voices"
_piper_voice_cache = None


def _try_elevenlabs(text: str, out_path: Path) -> bool:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return False

    voice_id = os.environ.get("ELEVENLABS_VOICE_ID", DEFAULT_ELEVENLABS_VOICE_ID)
    try:
        resp = requests.post(
            f"{ELEVENLABS_API_URL}/{voice_id}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={
                "text": text,
                "model_id": "eleven_flash_v2_5",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "speed": ELEVENLABS_SPEED,
                },
            },
            timeout=30,
        )
        resp.raise_for_status()
        out_path.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"[voiceover] ElevenLabs call failed ({e}) — falling back to Piper.")
        return False


def _get_piper_voice():
    global _piper_voice_cache
    if _piper_voice_cache is not None:
        return _piper_voice_cache

    from piper import PiperVoice
    from piper.download_voices import download_voice

    PIPER_VOICES_DIR.mkdir(parents=True, exist_ok=True)
    model_path = PIPER_VOICES_DIR / f"{PIPER_VOICE_NAME}.onnx"

    if not model_path.exists():
        print(f"[voiceover] downloading voice model '{PIPER_VOICE_NAME}' (one-time, a few MB)...")
        download_voice(PIPER_VOICE_NAME, PIPER_VOICES_DIR)

    _piper_voice_cache = PiperVoice.load(str(model_path))
    return _piper_voice_cache


def _piper_fallback(text: str, out_path: Path) -> Path:
    voice = _get_piper_voice()
    with wave.open(str(out_path), "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    return out_path


def generate_voiceover(text: str, filename_hint: str = "voiceover") -> Path:
    """Single-clip version — fine for one-off narration, but for any
    MULTI-SCENE video use generate_voiceover_batch() instead, so the voice
    provider stays consistent across every scene."""
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    mp3_path = GENERATED_DIR / f"{filename_hint}.mp3"
    if _try_elevenlabs(text, mp3_path):
        return mp3_path
    wav_path = GENERATED_DIR / f"{filename_hint}.wav"
    return _piper_fallback(text, wav_path)


def generate_voiceover_batch(texts: list, filename_hints: list) -> list:
    """Generates narration for multiple scenes in ONE video, guaranteeing
    the SAME voice provider for every single scene — no exceptions. If
    ElevenLabs fails on ANY scene partway through, the entire batch is
    redone on Piper, including scenes that already succeeded on
    ElevenLabs. This costs a little wasted work in the failure case, but
    it's the only way to guarantee true consistency — a partial mix
    (scene 1 on Derek, scenes 2+ on Piper) is still a voice change
    mid-video, which is exactly the bug this exists to prevent.
    """
    if len(texts) != len(filename_hints):
        raise ValueError("texts and filename_hints must be the same length")

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    elevenlabs_results = []
    all_succeeded = True

    for text, hint in zip(texts, filename_hints):
        mp3_path = GENERATED_DIR / f"{hint}.mp3"
        if _try_elevenlabs(text, mp3_path):
            elevenlabs_results.append(mp3_path)
        else:
            all_succeeded = False
            break

    if all_succeeded:
        return elevenlabs_results

    if elevenlabs_results:
        print(f"[voiceover] ElevenLabs succeeded on {len(elevenlabs_results)} scene(s) "
              f"but failed partway through this batch — redoing the ENTIRE "
              f"video on Piper instead, so the voice stays consistent "
              f"throughout rather than changing mid-video. Check your "
              f"ElevenLabs credit cap if this keeps happening.")

    return [_piper_fallback(text, GENERATED_DIR / f"{hint}.wav")
            for text, hint in zip(texts, filename_hints)]