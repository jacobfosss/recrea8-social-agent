"""
One-time patch: bigger captions on pasture-footage videos (the "Better
Informed" poster videos keep their current size). Also makes the GitHub copy
of the TikTok video optional, if that fix isn't in yet.

Backs up both files first and changes nothing it isn't sure about.
Run from the project folder:  python3 patch_bigger_text.py
"""
import py_compile
import re
import shutil
import sys
from pathlib import Path

PASTURE_CAPTION_SIZE = 60   # poster videos stay at 32

BUILDER = Path("src/shotstack_video_builder.py")
MAIN = Path("src/main.py")


def fail(msg):
    sys.exit(msg + " No changes made.")


def main():
    b, m = BUILDER.read_text(), MAIN.read_text()

    # ---- builder: optional caption_size override ----
    if "caption_size" not in b:
        sig = 'caption_palette: str = "light_on_dark") -> Path:'
        if sig not in b:
            fail("Couldn't find build_video's signature.")
        b = b.replace(sig, 'caption_palette: str = "light_on_dark", caption_size: int = None) -> Path:', 1)
        size_expr = '32 if caption_intensity == "calm" else 38'
        if size_expr not in b:
            fail("Couldn't find the caption size setting.")
        b = b.replace(size_expr, f'caption_size or ({size_expr})')

    # ---- main: pass a bigger size for pasture ----
    if "caption_size" not in m:
        a = 'caption_palette = "dark_on_light"\n'
        c = 'caption_palette = "light_on_dark"\n'
        call = 'caption_palette=caption_palette,'
        if a not in m or c not in m or call not in m:
            fail("main.py doesn't have the pasture patch yet. Run patch_main_pasture.py first.")
        ind_a = re.search(r'([ \t]*)caption_palette = "dark_on_light"\n', m).group(1)
        m = m.replace(a, a + f"{ind_a}caption_size = None\n", 1)
        ind_c = re.search(r'([ \t]*)caption_palette = "light_on_dark"\n', m).group(1)
        m = m.replace(c, c + f"{ind_c}caption_size = {PASTURE_CAPTION_SIZE}\n", 1)
        line = next(l for l in m.splitlines() if l.strip().startswith(call))
        ind = line[:len(line) - len(line.lstrip())]
        m = m.replace(line, line + f"\n{ind}caption_size=caption_size,", 1)

    # ---- main: GitHub copy of the TikTok video is optional ----
    host = "tiktok_public_url = media_host.publish_to_public_url(tiktok_video_path)"
    lines = m.splitlines()
    for i, l in enumerate(lines):
        if l.strip() == host and not lines[i - 1].strip().startswith("try:"):
            ind = l[:len(l) - len(l.lstrip())]
            lines[i] = (f"{ind}try:\n{ind}    {host}\n{ind}except Exception as e:\n"
                        f"{ind}    print(f\"[hosted] skipped GitHub copy of the video ({{e}}) - not needed for TikTok upload\")")
            break
    m = "\n".join(lines) + "\n"

    # TikTok upload must not depend on the GitHub copy succeeding
    gate = 'if platforms.get("tiktok") and tiktok_public_url:'
    if gate in m:
        if "tiktok_local_path" not in m:
            fail("main.py has no tiktok_local_path (FILE_UPLOAD fix missing).")
        m = m.replace(gate, 'if platforms.get("tiktok") and tiktok_local_path:', 1)

    shutil.copy(BUILDER, BUILDER.with_suffix(".py.bak2"))
    shutil.copy(MAIN, MAIN.with_suffix(".py.bak2"))
    BUILDER.write_text(b)
    MAIN.write_text(m)
    for f in (BUILDER, MAIN):
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            shutil.copy(BUILDER.with_suffix(".py.bak2"), BUILDER)
            shutil.copy(MAIN.with_suffix(".py.bak2"), MAIN)
            sys.exit(f"Patched code didn't compile, restored originals. Error: {e}")
    print(f"Done: pasture captions now size {PASTURE_CAPTION_SIZE} (poster unchanged).")


if __name__ == "__main__":
    main()
