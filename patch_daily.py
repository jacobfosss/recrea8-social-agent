import re
from pathlib import Path

def save(p, s, label):
    Path(p).write_text(s); print(f"✓ {label}")

# 1) main.py — hashtags, claim the day's slot up front, don't let a logging bug skip timing
p = Path("src/main.py"); s = p.read_text()
if "_tiktok_caption" not in s:
    s = s.replace("def load_config():", '''EDU_HASHTAGS = "#Recrea8 #nutrition #nutritionscience #healthyeating #wholefoods"


def _tiktok_caption(content):
    cap = content["caption"]
    if content.get("source") == "educational" and "#" not in cap:
        cap = f"{cap}\\n\\n{EDU_HASHTAGS}"
    return cap


def load_config():''', 1)
    s = re.sub(r'(tiktok_poster\.post_video\([^,\n]+,\s*)content\["caption"\]\)', r'\1_tiktok_caption(content))', s)
    # claim today's slot as soon as the scheduler says go, so a failed render can't retry all day
    s = s.replace('''        print(f"[scheduler] posting educational now (hour={current_hour} UTC)")''',
'''        print(f"[scheduler] posting educational now (hour={current_hour} UTC)")
        time_optimizer.record_scheduled_post("educational", current_hour)''', 1)
    lines = s.split("\n")
    for i, line in enumerate(lines):
        if 'post_history.record_post("tiktok"' in line and not line.strip().startswith("try"):
            ind = line[:len(line) - len(line.lstrip())]
            lines[i] = (f"{ind}try:\n{ind}    {line.strip()}\n{ind}except Exception as e:\n"
                        f"{ind}    print(f\"[history] couldn't log post ({{e}}) — not critical\")")
    s = "\n".join(lines)
    assert "_tiktok_caption(content))" in s, "couldn't find the TikTok post_video call"
    assert 'record_scheduled_post("educational", current_hour)' in s, "couldn't find scheduler line"
    save(p, s, "main.py")

# 2) time_optimizer — 1 post per day
p = Path("src/time_optimizer.py"); s = p.read_text()
s = re.sub(r"^POSTS_PER_DAY = \d+", "POSTS_PER_DAY = 1", s, flags=re.M)
save(p, s, "time_optimizer.py (1 post/day)")

# 3) tiktok_poster — send caption to a GitHub issue so it reaches your phone
p = Path("src/tiktok_poster.py"); s = p.read_text()
if "_notify_caption" not in s:
    s = s.replace('''        print("-------------------")
    return publish_id''', '''        print("-------------------")
        _notify_caption(caption)
    return publish_id''', 1)
    assert "_notify_caption(caption)" in s, "couldn't find the caption print block"
    s += '''

def _notify_caption(caption):
    """Opens a GitHub issue with the caption, so it reaches your phone via
    the GitHub app when the draft is made by the scheduled (cloud) run."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPO")
    if not token or not repo:
        return
    try:
        first = caption.strip().splitlines()[0][:60]
        body = ("A new video is in your TikTok inbox. Tap the TikTok notification, "
                "then Next, paste this caption, and Post:\\n\\n```\\n" + caption +
                "\\n```\\n\\nClose this issue once it's posted.")
        r = requests.post(f"https://api.github.com/repos/{repo}/issues",
                          headers={"Authorization": f"Bearer {token}",
                                   "Accept": "application/vnd.github+json"},
                          json={"title": f"TikTok draft ready: {first}", "body": body}, timeout=20)
        r.raise_for_status()
        print(f"[tiktok] caption sent to GitHub: {r.json().get('html_url')}")
    except Exception as e:
        print(f"[tiktok] couldn't create caption issue ({e}) — caption is in the log above")
'''
    save(p, s, "tiktok_poster.py (caption -> GitHub issue)")

# 4) workflow — daily schedule back on
p = Path(".github/workflows/post_schedule.yml"); s = p.read_text()
if "schedule:" in s:
    print("✓ post_schedule.yml already patched"); print("\nAll patched."); raise SystemExit
start = s.index("on:"); end = s.index("  workflow_dispatch:")
s = s[:start] + '''on:
  # Checks in every 2 hours, 7am-7pm New York time (EDT); time_optimizer picks
  # ONE of these per day to make the TikTok draft.
  schedule:
    - cron: "5 11,13,15,17,19,21,23 * * *"
''' + s[end:]
s = s.replace("permissions:", "concurrency:\n  group: social-posting\n  cancel-in-progress: false\n\npermissions:", 1)
s = s.replace("--check-hours 8,10,12,14,16,18,20,22", "--check-hours 11,13,15,17,19,21,23")
s = s.replace('''          git add content/posted/ 2>/dev/null || true
          git add content/generated/ 2>/dev/null || true''', '''          git add data/research_queue.json 2>/dev/null || true
          git add data/educational_style.json 2>/dev/null || true
          git add data/post_history.json 2>/dev/null || true''')
s = s.replace("      - name: Commit updated state\n", "      - name: Commit updated state\n        if: always()  # save state even if the run failed, so it doesn't retry all day\n", 1)
assert "schedule:" in s and "research_queue.json" in s
save(p, s, "post_schedule.yml (daily schedule on)")
print("\nAll patched.")
