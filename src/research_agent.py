"""
Searches PubMed (NIH's official, free, keyless E-utilities API — no scraping,
no ToS issue, public-domain metadata) for recent studies on your topics, then
has Claude translate the science into plain-language, brand-voiced content
ideas. Results queue into data/research_queue.json for content_selector to
draw from as an "educational" content type.

PubMed docs: https://www.ncbi.nlm.nih.gov/books/NBK25501/
"""
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent.parent
QUEUE_PATH = ROOT / "data" / "research_queue.json"

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MODEL = "claude-sonnet-5"

DEFAULT_TOPICS = [
    "ultra-processed food inflammation",
    "artificial sweeteners health effects",
    "whole foods gut microbiome",
    "added sugar chronic disease risk",
    "artificial food dye health effects",
    "anti-inflammatory diet clinical trial",
]


def _client():
    import os
    return Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _search_pubmed(topic: str, max_results: int = 5) -> list[str]:
    resp = requests.get(
        f"{EUTILS_BASE}/esearch.fcgi",
        params={
            "db": "pubmed", "term": topic, "retmax": max_results,
            "sort": "pub+date", "retmode": "json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("esearchresult", {}).get("idlist", [])


def _fetch_abstracts(pmids: list[str]) -> list[dict]:
    if not pmids:
        return []
    resp = requests.get(
        f"{EUTILS_BASE}/efetch.fcgi",
        params={"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
        timeout=30,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    articles = []
    for article in root.findall(".//PubmedArticle"):
        title_el = article.find(".//ArticleTitle")
        abstract_el = article.find(".//AbstractText")
        year_el = article.find(".//PubDate/Year")
        journal_el = article.find(".//Journal/Title")
        pmid_el = article.find(".//PMID")

        if title_el is None or abstract_el is None:
            continue

        articles.append({
            "pmid": pmid_el.text if pmid_el is not None else "",
            "title": title_el.text or "",
            "abstract": abstract_el.text or "",
            "year": year_el.text if year_el is not None else "",
            "journal": journal_el.text if journal_el is not None else "",
        })
    return articles


def _simplify_for_social(article: dict, brand_voice: str, brand_context: str) -> dict:
    """Ask Claude to translate one study into an easy-to-digest, brand-voiced
    post idea. Explicitly instructed to paraphrase, never quote the abstract,
    and to be accurate/measured rather than sensational about findings."""
    client = _client()
    prompt = f"""You're writing educational social content for a nutrition-focused
brand. Brand voice: {brand_voice}
Brand context: {brand_context}

Here is a real published study (paraphrase only — never quote it directly):
Title: {article['title']}
Journal/Year: {article['journal']}, {article['year']}
Abstract: {article['abstract']}

Write:
1. A one-line hook (under 12 words) for an image card.
2. A short, accurate, easy-to-understand caption (under 70 words) explaining
   what the study found and why it matters for everyday eating — measured and
   honest about what the study does and doesn't show, no exaggerated claims,
   no medical advice. End with a source mention like "(Journal, Year)" not a
   direct link.

Separate the two parts with "---". No preamble.
"""
    resp = client.messages.create(model=MODEL, max_tokens=400,
                                   messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    parts = text.split("---")
    return {
        "card_text": parts[0].strip(),
        "caption": parts[1].strip() if len(parts) > 1 else parts[0].strip(),
        "source_title": article["title"],
        "source_journal": article["journal"],
        "source_year": article["year"],
        "pmid": article["pmid"],
    }


def refresh_research_queue(topics=None, brand_voice="", brand_context="", per_topic=2):
    topics = topics or DEFAULT_TOPICS
    queue = json.loads(QUEUE_PATH.read_text()) if QUEUE_PATH.exists() else []
    seen_pmids = {item["pmid"] for item in queue}

    added = 0
    for topic in topics:
        try:
            pmids = _search_pubmed(topic, max_results=per_topic + 3)
            articles = _fetch_abstracts(pmids)
            for article in articles:
                if article["pmid"] in seen_pmids or not article["abstract"]:
                    continue
                idea = _simplify_for_social(article, brand_voice, brand_context)
                idea["topic"] = topic
                idea["used"] = False
                queue.append(idea)
                seen_pmids.add(article["pmid"])
                added += 1
                if added % per_topic == 0:
                    break
            time.sleep(0.5)  # be polite to the free API, no key = lower rate limit
        except Exception as e:
            print(f"[research] failed on topic '{topic}': {e}")

    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(queue, indent=2))
    print(f"[research] added {added} new item(s), queue size={len(queue)}")


def get_next_unused_item():
    if not QUEUE_PATH.exists():
        return None
    queue = json.loads(QUEUE_PATH.read_text())
    for item in queue:
        if not item.get("used"):
            return item
    return None


def mark_used(pmid: str):
    if not QUEUE_PATH.exists():
        return
    queue = json.loads(QUEUE_PATH.read_text())
    for item in queue:
        if item["pmid"] == pmid:
            item["used"] = True
    QUEUE_PATH.write_text(json.dumps(queue, indent=2))


if __name__ == "__main__":
    refresh_research_queue()
