"""Builds nature backgrounds for the given themes with ~55s of silent
stand-in narration and saves contact sheets (no TikTok, no Shotstack)."""
import os, subprocess, sys, io, contextlib
from pathlib import Path
sys.path.insert(0, ".")
from PIL import Image
import src.pasture_backgrounds as pb

OUT = Path("content/nature_test"); OUT.mkdir(parents=True, exist_ok=True)
audio = []
for i, d in enumerate([9, 12, 11, 12, 11]):
    p = OUT / f"silence{i}.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "anullsrc=r=44100:cl=mono", "-t", str(d), str(p)], check=True)
    audio.append(p)
report = []
for theme in os.environ.get("THEMES", "dairy,honey,cacao,vanilla,mint_greens").split(","):
    os.environ["EDU_THEME"] = theme
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        path, _ = pb.build_nature_background(audio, "")
    report.append(f"== {theme}\n{buf.getvalue()}")
    if not path:
        continue
    dur = pb._duration(path)
    frames = []
    for k in range(12):
        f = OUT / f"_{theme}_{k}.png"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{dur*(k+0.5)/12:.2f}",
                        "-i", str(path), "-frames:v", "1", "-vf", "scale=240:-1", str(f)], check=True)
        frames.append(Image.open(f)); f.unlink() if False else None
    w, h = frames[0].size
    sheet = Image.new("RGB", (w * 6, h * 2))
    for k, im in enumerate(frames):
        sheet.paste(im, ((k % 6) * w, (k // 6) * h))
    sheet.save(OUT / f"{theme}.jpg", quality=85)
    for f in OUT.glob(f"_{theme}_*.png"):
        f.unlink()
for p in audio:
    p.unlink()
(OUT / "report.txt").write_text("\n".join(report))
print("\n".join(report))
