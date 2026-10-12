"""
One-time patch: wires the pasture background rotation into src/main.py.
Makes a backup first (src/main.py.bak) and changes nothing if the code
doesn't look the way it expects.

Run from the project folder:  python3 patch_main_pasture.py
"""
import py_compile
import re
import shutil
import sys
from pathlib import Path

MAIN = Path("src/main.py")


def main():
    if not MAIN.exists():
        sys.exit("src/main.py not found. Run this from the recrea8-social-agent folder.")
    s = MAIN.read_text()
    if "pasture_backgrounds" in s:
        sys.exit("Already patched — nothing to do.")

    edu = s.find('content["source"] == "educational"')
    if edu == -1:
        sys.exit("Couldn't find the educational branch in main.py. No changes made.")

    m = re.compile(
        r'(?P<indent>[ \t]*)scene_visuals = \[\]\n.*?'
        r'scene_audio_paths = voiceover_generator\.generate_voiceover_batch\(.*?\n[ \t]*\)\n',
        re.DOTALL,
    ).search(s, edu)
    if not m:
        sys.exit("Couldn't find the background/voiceover block. No changes made.")
    ind = m.group("indent")

    new_block = f'''{ind}scene_audio_paths = voiceover_generator.generate_voiceover_batch(
{ind}    texts=slide_texts,
{ind}    filename_hints=[f"educational_scene{{i}}" for i in range(total_slides)],
{ind})

{ind}# Background style rotates: 3 "Better Informed" poster, then 3 pasture
{ind}# footage, repeat (see src/pasture_backgrounds.py). Falls back to the
{ind}# poster if Pexels doesn't return enough footage.
{ind}from src import pasture_backgrounds
{ind}style = pasture_backgrounds.next_style()
{ind}scene_visuals = None
{ind}caption_palette = "dark_on_light"
{ind}if style == "pasture":
{ind}    scene_visuals = pasture_backgrounds.build_pasture_visuals(scene_audio_paths)
{ind}    if scene_visuals:
{ind}        caption_palette = "light_on_dark"
{ind}if not scene_visuals:
{ind}    style = "poster"
{ind}    scene_visuals = [
{ind}        (content_generator.render_video_background(slide_index=i + 1, total_slides=total_slides), False)
{ind}        for i in range(total_slides)
{ind}    ]
{ind}print(f"[educational] background style: {{style}}")
'''
    s2 = s[:m.start()] + new_block + s[m.end():]

    pal = s2.find('caption_palette="dark_on_light"', m.start())
    if pal == -1:
        sys.exit("Couldn't find caption_palette in the build_video call. No changes made.")
    s2 = s2[:pal] + "caption_palette=caption_palette" + s2[pal + len('caption_palette="dark_on_light"'):]

    shutil.copy(MAIN, MAIN.with_suffix(".py.bak"))
    MAIN.write_text(s2)
    try:
        py_compile.compile(str(MAIN), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy(MAIN.with_suffix(".py.bak"), MAIN)
        sys.exit(f"Patched file didn't compile, restored the original. Error: {e}")
    print("Patched src/main.py (backup at src/main.py.bak).")


if __name__ == "__main__":
    main()
