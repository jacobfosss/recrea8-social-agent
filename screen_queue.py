"""
One-time cleanup: re-screens every unused item in data/research_queue.json
with the stricter relevance rules and pulls anything that isn't really about
food/diet/nutrition, or whose caption is a refusal instead of a post.
Rejected items are kept in the file (marked "rejected") so they're never
re-added, but they'll never be posted.

Run from the project folder:  python3 screen_queue.py
"""
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")

from src.research_agent import QUEUE_PATH, _client, MODEL, looks_like_refusal


def is_about_food(item: dict) -> bool:
    prompt = f"""A nutrition brand wants to post about this study. Is a FOOD,
DRINK, DIET, EATING PATTERN, NUTRIENT, or FOOD INGREDIENT the main thing
being studied? Medication, drug, inhaler, surgery, device, or disease-
treatment studies are NO even if they measure blood sugar or weight.

Study title: {item.get('source_title', '')}
Draft caption: {item.get('caption', '')[:500]}

Answer with exactly one word: YES or NO."""
    resp = _client().messages.create(model=MODEL, max_tokens=10,
                                     messages=[{"role": "user", "content": prompt}])
    answer = "".join(b.text for b in resp.content if b.type == "text").strip().upper()
    return answer.startswith("Y")


def main():
    queue = json.loads(Path(QUEUE_PATH).read_text())
    checked = rejected = 0
    for item in queue:
        if item.get("used") or item.get("rejected"):
            continue
        checked += 1
        reason = None
        if looks_like_refusal(item.get("caption", "")) or looks_like_refusal(item.get("card_text", "")):
            reason = "caption is a refusal, not a post"
        elif not is_about_food(item):
            reason = "study is not about food/nutrition"
        if reason:
            item["rejected"] = reason
            rejected += 1
            print(f"REJECTED: {item.get('source_title', '')[:90]}  ({reason})")
    Path(QUEUE_PATH).write_text(json.dumps(queue, indent=2))
    remaining = sum(1 for i in queue if not i.get("used") and not i.get("rejected"))
    print(f"\nChecked {checked} unused item(s), rejected {rejected}. Good items left: {remaining}")


if __name__ == "__main__":
    main()
