import json, re
from pathlib import Path

p = Path(".github/workflows/post_schedule.yml"); s = p.read_text()
s = re.sub(r"          git add content/posted/ 2>/dev/null \|\| true\n          git add content/generated/ 2>/dev/null \|\| true\n",
           "          git add data/research_queue.json 2>/dev/null || true\n"
           "          git add data/educational_style.json 2>/dev/null || true\n", s)
if "if: always()" not in s:
    s = s.replace("      - name: Commit updated state\n",
                  "      - name: Commit updated state\n        if: always()\n", 1)
if "concurrency:" not in s:
    s = s.replace("\npermissions:", "\nconcurrency:\n  group: social-posting\n  cancel-in-progress: false\n\npermissions:", 1)
s = re.sub(r'(    - cron: "0 \d+ \* \* \*"\n)+', '    - cron: "5 11,13,15,17,19,21,23 * * *"\n', s, count=1)
s = s.replace("--check-hours 8,10,12,14,16,18,20,22", "--check-hours 11,13,15,17,19,21,23")
assert "git add data/research_queue.json" in s, "commit step not found"
p.write_text(s); print("✓ workflow now saves the research queue + background rotation")

q = Path("data/research_queue.json"); items = json.loads(q.read_text())
for it in items:
    if str(it.get("pmid")) == "42464261":
        it["used"] = True
q.write_text(json.dumps(items, indent=2))
nxt = [i for i in items if not i.get("used") and not i.get("rejected")]
print(f"✓ retired the repeated study — {len(nxt)} fresh studies left")
print(f"  next up: {nxt[0]['card_text']}")
