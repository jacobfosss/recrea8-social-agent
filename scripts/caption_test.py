"""Renders short sandbox test videos with different caption-box settings and
saves still frames to content/caption_test/ so the layout can be checked
before it touches a real post. Run via the 'Caption layout test' workflow."""
import json, os, subprocess, sys, time
from pathlib import Path
import requests

KEY = os.environ["SHOTSTACK_SANDBOX_API_KEY"]
BASE = "https://api.shotstack.io/stage"
RAW = "https://raw.githubusercontent.com/jacobfosss/recrea8-social-agent/main/content/posted/"
posted = sorted(os.listdir("content/posted"))
bg = os.environ.get("BG") or [f for f in posted if "educational_background_prepared" in f][-1]
audio = os.environ.get("AUDIO") or [f for f in posted if f.endswith(".mp3") and "combined" in f][-1]
BG_TYPE = "video" if bg.endswith(".mp4") else "image"
OUT = Path("content/caption_test"); OUT.mkdir(parents=True, exist_ok=True)

def caption(extra_clip, extra_asset, size=32):
    asset = {"type": "rich-caption", "src": "alias://speech",
             "font": {"family": "Montserrat", "size": size, "color": "#1D1D1D", "weight": 500},
             "animation": {"style": "highlight"}, "active": {"font": {"color": "#C49A4A"}},
             "align": {"vertical": "middle"}}
    asset.update(extra_asset)
    clip = {"asset": asset, "start": 0, "length": "end"}
    clip.update(extra_clip)
    return clip

VARIANTS = json.loads(os.environ.get("VARIANTS_JSON") or "{}") or {
    "a_current": caption({"width": 900}, {}),
    "b_box": caption({"width": 900, "height": 700}, {}),
    "c_box_pad": caption({"width": 900, "height": 700},
                         {"padding": {"top": 0, "right": 40, "bottom": 0, "left": 40}}),
}

def render(clip):
    payload = {"timeline": {"tracks": [
        {"clips": [clip]},
        {"clips": [{"asset": {"type": BG_TYPE, "src": RAW + bg}, "start": 0, "length": 16}]},
        {"clips": [{"alias": "speech", "asset": {"type": "audio", "src": RAW + audio},
                    "start": 0, "length": 16}]}]},
        "output": {"format": "mp4", "size": {"width": 1080, "height": 1920}}}
    h = {"x-api-key": KEY, "Content-Type": "application/json"}
    r = requests.post(f"{BASE}/render", headers=h, json=payload, timeout=60)
    if not r.ok:
        return None, f"{r.status_code} {r.text[:300]}"
    rid = r.json()["response"]["id"]
    for _ in range(90):
        time.sleep(10)
        s = requests.get(f"{BASE}/render/{rid}", headers=h, timeout=30).json()["response"]
        if s["status"] == "done":
            return s["url"], None
        if s["status"] == "failed":
            return None, s.get("error", "failed")
    return None, "timeout"

report = []
for name, clip in VARIANTS.items():
    url, err = render(clip)
    if err:
        report.append(f"{name}: ERROR {err}"); continue
    mp4 = OUT / f"{name}.mp4"
    mp4.write_bytes(requests.get(url, timeout=120).content)
    for t in (2, 6, 11):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", str(t), "-i", str(mp4),
                        "-frames:v", "1", "-vf", "scale=540:-1", str(OUT / f"{name}_{t}s.png")], check=True)
    mp4.unlink()
    report.append(f"{name}: ok")
(OUT / "report.txt").write_text("\n".join(report) + f"\nbg={bg}\naudio={audio}\n")
print("\n".join(report))
