"""
"Nature" background style for educational videos: a look under the hood at
where Recrea8's ingredients come from. Every other educational video uses
this instead of the "Better Informed" poster.

Each video picks ONE ingredient world (dairy, honey, vanilla, cacao, mint &
greens) so it stays visually coherent, then edits real Pexels footage into a
calm, cinematic sequence:

  - shot rhythm like a nature documentary: aerial establishing shot -> wide
    -> close-up -> detail, repeating, a new shot every ~4.5s
  - Claude screens every candidate clip's thumbnail first and rejects
    anything off-topic, staged-looking, low quality, branded, with text or
    watermarks, factory/industrial, or with people's faces as the subject
  - one consistent, gentle grade on every shot (no filters, no zooms, no
    flashy transitions) and short crossfades between shots
  - a soft dark band behind the middle of the frame, where the captions sit,
    so cream text stays readable over bright skies without boxes or outlines

Output: one continuous 1080x1920 silent video exactly as long as the
narration. Returns None on any shortfall so the caller falls back to the
poster style and the post still goes out.
"""
import base64
import io
import json
import os
import random
import re
import subprocess
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "educational_style.json"
RAW_DIR = ROOT / "content" / "generated" / "nature_raw"
WORK_DIR = ROOT / "content" / "generated" / "nature_work"
OUT_DIR = ROOT / "content" / "generated" / "nature_backgrounds"

PEXELS_VIDEO_API = "https://api.pexels.com/videos/search"
SHOT_SECONDS = 4.5      # average time on each shot
XFADE = 0.6             # crossfade between shots
W, H, FPS = 1080, 1920, 30

# One ingredient world per video. Each shot type has several queries so the
# pool is deep enough to fill a ~60s video without repeating a clip.
THEMES = {
    "dairy": {
        "label": "dairy: pastures, grazing cows, farms",
        "keywords": ["dairy", "milk", "cow", "cattle", "protein", "whey", "casein",
                      "cream", "pasture", "grass-fed", "yogurt", "cheese", "butter"],
        "shots": {
            "aerial": ["aerial drone green pasture farm", "drone flying over farmland countryside",
                        "aerial rolling green hills farm", "drone cows field aerial"],
            "wide": ["cows grazing green pasture", "dairy cows meadow", "herd of cows field sunset",
                      "cattle grazing hills"],
            "close": ["cow eating grass close up", "cow face close up", "calf in pasture",
                       "dairy cow portrait"],
            "detail": ["dew on grass morning sunlight", "grass blowing wind golden hour",
                        "misty pasture sunrise", "wildflowers pasture breeze"],
        },
    },
    "honey": {
        "label": "honey: bees, hives, wildflowers",
        "keywords": ["honey", "bee", "sugar", "sweetener", "sweet", "pollen", "flower",
                      "glucose", "fructose", "sucrose"],
        "shots": {
            "aerial": ["aerial wildflower meadow drone", "drone flower field countryside",
                        "aerial lavender field"],
            "wide": ["beekeeper beehive", "beehives in meadow", "wildflower meadow sunlight"],
            "close": ["bee on flower close up", "honeybee pollinating flower", "bees on honeycomb",
                       "bees hive entrance"],
            "detail": ["honey dripping", "honeycomb close up", "honey dipper pouring honey"],
        },
    },
    "vanilla": {
        "label": "vanilla: orchids, pods, plantations",
        "keywords": ["vanilla", "flavor", "flavour", "aroma", "extract", "natural flavor",
                      "artificial flavor", "vanillin"],
        "shots": {
            "aerial": ["aerial tropical plantation", "drone tropical forest island",
                        "aerial jungle green hills"],
            "wide": ["vanilla plantation", "tropical farm plants", "rainforest sunlight"],
            "close": ["vanilla orchid flower", "vanilla beans", "vanilla pods"],
            "detail": ["vanilla bean split", "vanilla pods drying", "vanilla bean macro"],
        },
    },
    "cacao": {
        "label": "cacao: pods, farms, rainforest",
        "keywords": ["cacao", "cocoa", "chocolate", "flavanol", "polyphenol", "ferment",
                      "antioxidant", "theobromine"],
        "shots": {
            "aerial": ["aerial rainforest drone", "drone tropical forest canopy",
                        "aerial jungle river"],
            "wide": ["cacao farm", "cocoa plantation", "cocoa tree"],
            "close": ["cacao pod", "cocoa pod tree", "opening cacao pod", "cocoa fruit"],
            "detail": ["cocoa beans", "cocoa beans drying", "raw cacao beans hands"],
        },
    },
    "mint_greens": {
        "label": "mint & greens: mint, forest, spirulina",
        "keywords": ["mint", "spirulina", "algae", "plant", "green", "vegetable", "fiber",
                      "fibre", "gut", "microbiome", "leaf", "forest", "whole food", "whole-food"],
        "shots": {
            "aerial": ["aerial forest drone", "drone green forest river", "aerial misty forest"],
            "wide": ["forest sunlight trees", "herb garden", "mint plants field", "forest stream"],
            "close": ["mint leaves close up", "fresh mint plant", "green leaves water drops",
                       "leaves sunlight close up"],
            "detail": ["green algae water", "spirulina", "fresh herbs harvest",
                        "water drops on leaf"],
        },
    },
}
THEME_ORDER = ["dairy", "honey", "cacao", "vanilla", "mint_greens"]
SHOT_PATTERN = ["aerial", "close", "wide", "detail", "close", "aerial", "detail", "close"]


# ---------- rotation ----------

def _load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"count": 0}


def _save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def next_style() -> str:
    """'poster' and 'pasture' (nature footage) alternate one-for-one.
    EDU_STYLE=poster|pasture forces one without touching the rotation."""
    forced = os.environ.get("EDU_STYLE", "").strip().lower()
    if forced in ("poster", "pasture"):
        return forced
    state = _load_state()
    n = state.get("count", 0)
    style = "poster" if n % 2 == 0 else "pasture"
    state["count"] = n + 1
    _save_state(state)
    return style


def pick_theme(topic_text: str = "") -> str:
    """Matches the study's subject when it clearly fits one ingredient
    (a cacao study gets cacao footage); otherwise rotates through all the
    ingredient worlds so every one gets airtime. EDU_THEME forces one."""
    forced = os.environ.get("EDU_THEME", "").strip().lower()
    if forced in THEMES:
        return forced
    text = (topic_text or "").lower()
    scores = {t: sum(text.count(k) for k in cfg["keywords"]) for t, cfg in THEMES.items()}
    best = max(scores, key=scores.get)
    state = _load_state()
    if scores[best] >= 2:
        theme = best
    else:
        i = state.get("theme_index", 0)
        theme = THEME_ORDER[i % len(THEME_ORDER)]
        state["theme_index"] = i + 1
    state["last_theme"] = theme
    _save_state(state)
    return theme


# ---------- Pexels ----------

def _search(query: str, orientation: str):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    import time
    for attempt in range(3):
        try:
            r = requests.get(PEXELS_VIDEO_API, headers={"Authorization": key},
                             params={"query": query, "orientation": orientation,
                                     "per_page": 15, "size": "medium"},
                             timeout=20)
            if r.status_code == 429 and attempt < 2:
                time.sleep(20 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json().get("videos", [])
        except Exception as e:
            print(f"[nature] search failed for '{query}': {e}")
            return []
    return []


def _best_file(video: dict):
    """Smallest file that is still sharp after cropping to vertical:
    portrait >= 1080 wide; landscape >= 2160 tall preferred (a 4K frame
    crops to a full-resolution vertical), 1080 tall accepted."""
    files = [f for f in video.get("video_files", [])
             if f.get("link") and f.get("width") and f.get("height")
             and "mp4" in (f.get("file_type") or "mp4")]
    if not files:
        return None, 0
    portrait = video.get("height", 0) > video.get("width", 0)
    if portrait:
        good = [f for f in files if f["width"] >= 1080]
        score = 2
    else:
        good = [f for f in files if f["height"] >= 2160]
        score = 2
        if not good:
            good = [f for f in files if f["height"] >= 1080]
            score = 1
    if not good:
        return None, 0
    return min(good, key=lambda f: f["width"] * f["height"]), score


def _candidates(theme: str):
    """{shot_type: [candidate dicts]} — deduped, long enough, sharp enough."""
    seen, pool, per_user = set(), {}, {}
    # ingredient-specific shots first, so they get searched even if the
    # Pexels hourly limit is close
    for shot_type in ("close", "detail", "wide", "aerial"):
        queries = THEMES[theme]["shots"][shot_type]
        pool[shot_type] = []
        for q in queries:
            for orientation in ("portrait", "landscape"):
                for v in _search(q, orientation):
                    if v.get("id") in seen or (v.get("duration") or 0) < 6:
                        continue
                    uid = (v.get("user") or {}).get("id")
                    if uid and per_user.get(uid, 0) >= 2:
                        continue  # avoids near-identical takes from one shoot
                    f, sharp = _best_file(v)
                    if not f:
                        continue
                    seen.add(v["id"])
                    if uid:
                        per_user[uid] = per_user.get(uid, 0) + 1
                    thumb = (v.get("image") or
                             (v.get("video_pictures") or [{}])[0].get("picture"))
                    pool[shot_type].append({
                        "id": v["id"], "duration": v["duration"], "file": f,
                        "sharp": sharp, "portrait": orientation == "portrait",
                        "thumb": thumb, "query": q, "page": v.get("url", ""),
                    })
    return pool


def _thumb_b64(url: str):
    try:
        from PIL import Image
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        im = Image.open(io.BytesIO(r.content)).convert("RGB")
        im.thumbnail((320, 320))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"[nature] thumbnail fetch failed: {e}")
        return None


def _screen(theme: str, pool: dict) -> dict:
    """Claude looks at every candidate's thumbnail and keeps only footage
    that is on-topic, natural, and cinematic. Returns the pool filtered and
    ranked best-first. If screening fails, falls back to the unscreened
    pool (sharpest first) rather than blocking the post."""
    for shot_type in pool:
        pool[shot_type].sort(key=lambda c: (-c["sharp"], -c["portrait"]))
    # an even share of every shot type, so close-ups aren't crowded out
    flat = [c for shot_type in pool for c in pool[shot_type][:16]]
    if not os.environ.get("ANTHROPIC_API_KEY") or not flat:
        return pool
    try:
        from anthropic import Anthropic
        blocks = [{"type": "text", "text": (
            f"You are picking b-roll for a calm, cinematic, documentary-style "
            f"vertical video about where a whole-food ice cream brand's ingredients "
            f"come from. This video's theme: {THEMES[theme]['label']}. Captions "
            f"will sit in the middle of the frame.\n\n"
            f"Below are {len(flat)} numbered video thumbnails, each labeled with the "
            f"subject it is supposed to show. KEEP a clip only if ALL are true: it "
            f"actually shows that subject (e.g. cows must really be cows, a cacao pod "
            f"must really be a cacao pod, bees must really be bees; coffee cherries, coffee "
            f"beans and palm trees are NOT cacao; generic forest, river or waterfall shots "
            f"are fine only for aerial/wide establishing shots); beautiful, natural, real-looking "
            f"(nature-documentary quality, the kind of shot you'd see in a premium brand "
            f"film: lush, healthy, idyllic, golden-hour or soft daylight); well lit and in "
            f"focus; animals look healthy, free and content (reject tethered or penned "
            f"animals, dirt lots, mud, feed buckets, barns interiors); no visible text, "
            f"logos, watermarks, brand names or packaged products; not a factory, "
            f"supermarket, plastic containers, sacks, tractors or machinery, kitchen, lab, or processed food; no person's face as the "
            f"main subject (hands or a distant farmer are fine); not CGI, cartoon, "
            f"stock-photo staged, or heavily filtered.\n\n"
            f"Reply with ONLY a JSON list of the kept numbers, best first, e.g. [4, 1, 9]."
        )}]
        kept_map = []
        for i, c in enumerate(flat, 1):
            b64 = _thumb_b64(c["thumb"]) if c["thumb"] else None
            if not b64:
                continue
            kept_map.append((i, c))
            blocks.append({"type": "text", "text": f"#{i} (should show: {c['query']})"})
            blocks.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg", "data": b64}})
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(model="claude-sonnet-5", max_tokens=4000,
                                      messages=[{"role": "user", "content": blocks}])
        text = "".join(b.text for b in resp.content if b.type == "text")
        print(f"[nature] screened {len(kept_map)} thumbnails; stop={resp.stop_reason} "
              f"blocks={[b.type for b in resp.content]} usage={resp.usage} reply: {text[:300]!r}")
        if not text.strip():
            raise RuntimeError("empty screening reply")
        m = re.search(r"\[[\d,\s]*\]", text)
        keep = [int(x) for x in re.findall(r"\d+", m.group(0) if m else text)]
        by_num = dict(kept_map)
        rank = {by_num[n]["id"]: r for r, n in enumerate(keep) if n in by_num}
        screened = {st: sorted([c for c in cs if c["id"] in rank], key=lambda c: rank[c["id"]])
                    for st, cs in pool.items()}
        total = sum(len(v) for v in screened.values())
        print(f"[nature] screening kept {total}/{len(flat)} clips for '{theme}'")
        return screened
    except Exception as e:
        print(f"[nature] screening failed ({e}) — using unscreened footage")
        return pool


def _download(c) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"pexels_{c['id']}_{c['file']['height']}.mp4"
    if not path.exists():
        r = requests.get(c["file"]["link"], timeout=300)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path


# ---------- ffmpeg ----------

def _duration(path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _caption_band() -> Path:
    """Soft, feathered darkening behind the caption area (middle of the
    frame): invisible as a shape, but keeps cream text readable on skies."""
    from PIL import Image
    import math
    path = WORK_DIR / "caption_band.png"
    if path.exists():
        return path
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    col = Image.new("L", (1, H))
    for y in range(H):
        a = 0.40 * math.exp(-((y - H * 0.5) ** 2) / (2 * 340 ** 2))
        col.putpixel((0, y), int(255 * a))
    alpha = col.resize((W, H))
    band = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    band.putalpha(alpha)
    band.save(path)
    return path


GRADE = ("scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
         "fps={fps},eq=contrast=1.03:saturation=1.07,"
         "vignette=angle=PI/10,format=yuv420p").format(w=W, h=H, fps=FPS)


def _cut_shot(raw: Path, length: float, out: Path):
    """One graded shot of exactly `length` seconds, taken from the steadiest
    middle part of the clip (skips the first/last half second, where stock
    clips often have camera jolts or fades)."""
    src_len = _duration(raw)
    usable = src_len - 1.0
    if usable >= length:
        start = 0.5 + random.uniform(0, max(0.0, usable - length))
        pre = ["-ss", f"{start:.2f}"]
    else:
        pre = ["-stream_loop", "-1"]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *pre, "-i", str(raw),
                    "-t", f"{length:.3f}", "-vf", GRADE, "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(out)],
                   check=True)


def _assemble(shots: list, total: float, out: Path):
    """Chains the shots with short crossfades, lays the caption band on
    top, and caps the bitrate so the file stays small enough to host."""
    inputs, filt, last = [], [], "[0:v]"
    offset = 0.0
    for i, s in enumerate(shots):
        inputs += ["-i", str(s)]
    band_idx = len(shots)
    inputs += ["-loop", "1", "-i", str(_caption_band())]
    for i in range(1, len(shots)):
        offset += _duration(shots[i - 1]) - XFADE
        tag = f"[x{i}]"
        filt.append(f"{last}[{i}:v]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}{tag}")
        last = tag
    filt.append(f"{last}[{band_idx}:v]overlay=0:0:shortest=1,format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs,
                    "-filter_complex", ";".join(filt), "-map", "[v]",
                    "-t", f"{total:.3f}", "-r", str(FPS), "-an",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                    "-maxrate", "2800k", "-bufsize", "5600k",
                    "-movflags", "+faststart", str(out)], check=True)


def build_nature_background(scene_audio_paths: list, topic_text: str = ""):
    """Returns (path_to_background_video, theme) or (None, theme)."""
    theme = pick_theme(topic_text)
    try:
        total = sum(_duration(a) for a in scene_audio_paths) + 0.3
        n_shots = max(4, round(total / SHOT_SECONDS))
        shot_len = (total + XFADE * (n_shots - 1)) / n_shots

        pool = _screen(theme, _candidates(theme))
        order = [SHOT_PATTERN[i % len(SHOT_PATTERN)] for i in range(n_shots)]
        used, picks = set(), []
        for shot_type in order:
            options = [c for c in pool.get(shot_type, []) if c["id"] not in used]
            if not options:  # that shot type ran dry: borrow from the others
                options = [c for st in ("close", "detail", "wide", "aerial")
                           for c in pool.get(st, []) if c["id"] not in used]
            if not options:
                print(f"[nature] ran out of approved '{theme}' footage")
                return None, theme
            pick = options[0] if random.random() < 0.7 else random.choice(options[:4])
            used.add(pick["id"])
            picks.append(pick)

        WORK_DIR.mkdir(parents=True, exist_ok=True)
        tag = random.randint(100000, 999999)
        shots = []
        for i, c in enumerate(picks):
            out = WORK_DIR / f"shot_{tag}_{i:02d}.mp4"
            _cut_shot(_download(c), shot_len, out)
            shots.append(out)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        final = OUT_DIR / f"nature_{theme}_{tag}.mp4"
        _assemble(shots, total, final)
        print(f"[nature] built {theme} background: {n_shots} shots, {total:.1f}s, "
              f"{final.stat().st_size / 1e6:.1f} MB — clips: "
              + ", ".join(str(c["id"]) for c in picks))
        return final, theme
    except Exception as e:
        print(f"[nature] background build failed ({e}) — falling back to poster")
        return None, theme
