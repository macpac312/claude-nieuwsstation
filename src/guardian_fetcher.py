#!/usr/bin/env python3
"""Guardian API fetcher voor het Nieuwsstation.

Haalt artikelen op van The Guardian met volledige tekst (gratis API, 2000 req/dag).
Output is compatibel met het JSON-formaat van rss_fetcher.py.

Gebruik:
    python guardian_fetcher.py --output /tmp/guardian.json
    python guardian_fetcher.py --focus ~/nieuwsstation/focus.md --output /tmp/guardian.json
    python guardian_fetcher.py --merge-into /tmp/rss.json
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

CONFIG_DIR = Path.home() / ".config" / "nieuwsstation"
SOURCES_YAML = Path(__file__).parent / "config" / "sources.yaml"
GUARDIAN_API = "https://content.guardianapis.com/search"

# Sectie-mapping: nieuwsstation topic → Guardian secties
SECTION_MAP = {
    "regulatoir": "business,money,politics",
    "financieel":  "business,money",
    "huizenmarkt": "money,business",
    "tech":        "technology",
    "ai_nieuws":   "technology",
    "wereld":      "world",
    "nederland":   "world",
    "sport":       "sport",
}


def load_key(config_dir: Path = CONFIG_DIR) -> str:
    key_file = config_dir / "guardian_api_key"
    if not key_file.exists():
        print("[ERR] Guardian API key niet gevonden: ~/.config/nieuwsstation/guardian_api_key",
              file=sys.stderr)
        sys.exit(1)
    return key_file.read_text().strip()


def load_guardian_config() -> dict:
    """Lees guardian-configuratie uit sources.yaml."""
    try:
        import yaml
        cfg = yaml.safe_load(SOURCES_YAML.read_text())
        return cfg.get("guardian", {})
    except Exception:
        return {}


def load_focus(focus_path: Path) -> list[dict]:
    """Parseer focus.md en extraheer actieve onderwerpen als zoekqueries.

    Elke niet-commentaar regel onder een ## header wordt een query.
    Formaat: "Verhaal-naam: keyword1, keyword2, keyword3"
    Returns: list van {"topic": str, "query": str, "label": str}
    """
    if not focus_path.exists():
        return []

    queries = []
    current_section = "algemeen"

    for line in focus_path.read_text().split("\n"):
        line = line.strip()
        if not line or line.startswith("#") and not line.startswith("##"):
            continue
        if line.startswith("## "):
            current_section = line[3:].strip()
            continue
        if line.startswith("- "):
            entry = line[2:].strip()
            # Formaat: "Label: keyword1, keyword2" → query = "keyword1 keyword2"
            if ":" in entry:
                label, keywords_raw = entry.split(":", 1)
                keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
                # Gebruik de eerste 4 keywords als Guardian-query
                query = " OR ".join(f'"{k}"' if " " in k else k
                                    for k in keywords[:4])
                queries.append({
                    "label": label.strip(),
                    "query": query,
                    "section": current_section,
                })
            else:
                queries.append({
                    "label": entry,
                    "query": entry,
                    "section": current_section,
                })

    return queries


def fetch_guardian(
    query: str,
    api_key: str,
    hours: int = 72,
    page_size: int = 5,
    section: str = "",
    topic: str = "algemeen",
    label: str = "",
) -> list[dict]:
    """Haal artikelen op van The Guardian voor een zoekopdracht.

    Returns: list[dict] compatibel met rss_fetcher output formaat.
    """
    from_date = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d")

    params = {
        "q": query,
        "from-date": from_date,
        "show-fields": "trailText,bodyText,thumbnail",
        "page-size": min(page_size, 50),
        "order-by": "relevance",
        "api-key": api_key,
    }
    if section:
        params["section"] = section

    url = f"{GUARDIAN_API}?{urlencode(params)}"

    try:
        req = Request(url, headers={"User-Agent": "nieuwsstation/1.0"})
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except HTTPError as e:
        print(f"[WARN] Guardian HTTP fout voor '{query}': {e.code}", file=sys.stderr)
        return []
    except URLError as e:
        print(f"[WARN] Guardian verbindingsfout voor '{query}': {e}", file=sys.stderr)
        return []

    results = data.get("response", {}).get("results", [])
    items = []

    for r in results:
        fields = r.get("fields", {})
        body = fields.get("bodyText", "")
        trail = fields.get("trailText", "")

        # Haal HTML-tags weg uit trail/body
        trail_clean = re.sub(r"<[^>]+>", "", trail).strip()
        body_clean = re.sub(r"<[^>]+>", "", body).strip()

        # Summary = trail (kort), of eerste 300 tekens van body
        summary = trail_clean if trail_clean else body_clean[:300]
        if summary and not summary.endswith("."):
            summary = summary.rstrip() + "."

        pub_str = r.get("webPublicationDate", "")
        try:
            published = datetime.fromisoformat(pub_str.replace("Z", "+00:00")).isoformat()
        except Exception:
            published = datetime.now(timezone.utc).isoformat()

        word_count = len(body_clean.split()) if body_clean else 0

        items.append({
            "title": r.get("webTitle", "").strip(),
            "link": r.get("webUrl", ""),
            "summary": summary,
            "full_text": body_clean,          # volledige tekst, voor analyse
            "published": published,
            "source_name": "The Guardian",
            "source_type": "article",
            "topic": topic,
            "focus_label": label,
            "has_full_text": bool(body_clean),
            "word_count": word_count,
            "image_url": fields.get("thumbnail", ""),
        })

    return items


def fetch_all(
    api_key: str,
    guardian_config: dict,
    focus_path: Path | None = None,
    hours: int | None = None,
) -> dict:
    """Haal alle Guardian-artikelen op: vaste topic-queries + focus-queries.

    Returns: dict in rss_fetcher JSON-formaat (topics → items).
    """
    effective_hours = hours or guardian_config.get("hours", 72)
    page_size = guardian_config.get("page_size", 5)

    all_topics: dict[str, list] = {}
    seen_urls: set[str] = set()

    def add_items(topic: str, items: list[dict]) -> None:
        """Voeg items toe, dedupliceer op URL."""
        for item in items:
            url = item["link"]
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_topics.setdefault(topic, []).append(item)

    # 1. Vaste topic-queries uit sources.yaml
    topic_queries: dict = guardian_config.get("topics", {})
    for topic, queries in topic_queries.items():
        section = SECTION_MAP.get(topic, "")
        print(f"  [Guardian] topic={topic} ({len(queries)} queries)...", file=sys.stderr)
        for query in queries:
            items = fetch_guardian(
                query=query,
                api_key=api_key,
                hours=effective_hours,
                page_size=page_size,
                section=section,
                topic=topic,
                label=query,
            )
            add_items(topic, items)

    # 2. Focus-queries uit focus.md
    if focus_path and focus_path.exists():
        focus_queries = load_focus(focus_path)
        print(f"  [Guardian] focus: {len(focus_queries)} actieve onderwerpen...",
              file=sys.stderr)
        for fq in focus_queries:
            # Bepaal topic op basis van sectie-naam
            section_lower = fq["section"].lower()
            if any(w in section_lower for w in ["regulat", "irb", "crr", "Basel"]):
                topic = "regulatoir"
            elif any(w in section_lower for w in ["financ", "markt", "beurs"]):
                topic = "financieel"
            elif any(w in section_lower for w in ["huis", "woning", "vastgoed"]):
                topic = "huizenmarkt"
            elif any(w in section_lower for w in ["tech", "ai", "claude"]):
                topic = "tech"
            elif any(w in section_lower for w in ["sport", "f1", "schaak"]):
                topic = "sport"
            else:
                topic = "wereld"

            items = fetch_guardian(
                query=fq["query"],
                api_key=api_key,
                hours=effective_hours,
                page_size=3,
                topic=topic,
                label=fq["label"],
            )
            add_items(topic, items)

    # Bouw output in rss_fetcher formaat
    total = sum(len(v) for v in all_topics.values())
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "guardian",
        "hours": effective_hours,
        "total_items": total,
        "topics": {
            topic: {
                "item_count": len(items),
                "items": items,
            }
            for topic, items in all_topics.items()
        },
    }


def merge_into(guardian_data: dict, rss_path: Path) -> dict:
    """Voeg Guardian-items samen met bestaand rss.json bestand.

    Dedupliceert op URL. Guardian-items met has_full_text=True krijgen
    prioriteit bij dubbele titels.
    """
    if not rss_path.exists():
        print(f"[WARN] {rss_path} bestaat niet — Guardian data wordt standalone opgeslagen",
              file=sys.stderr)
        return guardian_data

    rss = json.loads(rss_path.read_text())
    existing_urls: set[str] = set()

    # Verzamel bestaande URLs
    for td in rss.get("topics", {}).values():
        for item in td.get("items", []):
            existing_urls.add(item.get("link", ""))

    added = 0
    for topic, gd in guardian_data.get("topics", {}).items():
        g_items = gd.get("items", [])
        new_items = [it for it in g_items if it["link"] not in existing_urls]

        if new_items:
            if topic not in rss["topics"]:
                rss["topics"][topic] = {"item_count": 0, "items": []}
            rss["topics"][topic]["items"].extend(new_items)
            rss["topics"][topic]["item_count"] = len(rss["topics"][topic]["items"])
            existing_urls.update(it["link"] for it in new_items)
            added += len(new_items)

    rss["total_items"] = rss.get("total_items", 0) + added
    rss["guardian_items"] = added

    print(f"[OK] Guardian: {added} nieuwe items samengevoegd in {rss_path}", file=sys.stderr)
    rss_path.write_text(json.dumps(rss, ensure_ascii=False, indent=2))
    return rss


def main():
    p = argparse.ArgumentParser(description="Guardian API fetcher voor Nieuwsstation")
    p.add_argument("--focus", help="Pad naar focus.md")
    p.add_argument("--hours", type=int, help="Tijdvenster in uren (default: uit sources.yaml)")
    p.add_argument("--output", help="Output JSON pad (standalone)")
    p.add_argument("--merge-into", help="Pad naar bestaand rss.json om samen te voegen")
    p.add_argument("--query", help="Enkelvoudige zoekopdracht (test-modus)")
    p.add_argument("--topic", default="algemeen", help="Topic voor enkelvoudige query")
    a = p.parse_args()

    api_key = load_key()
    guardian_config = load_guardian_config()

    # Test-modus: enkelvoudige query
    if a.query:
        items = fetch_guardian(
            query=a.query,
            api_key=api_key,
            hours=a.hours or 72,
            page_size=5,
            topic=a.topic,
        )
        print(f"[OK] {len(items)} items voor query '{a.query}':", file=sys.stderr)
        for it in items:
            wc = it.get("word_count", 0)
            ft = "✓ volledige tekst" if it.get("has_full_text") else "∅"
            print(f"  [{it['published'][:10]}] {ft} ({wc}w) {it['title'][:60]}")
        return

    # Focus-pad
    focus_path = Path(a.focus) if a.focus else Path(__file__).parent.parent / "focus.md"

    # Haal alle data op
    print("[Guardian] Artikelen ophalen...", file=sys.stderr)
    data = fetch_all(api_key, guardian_config, focus_path, a.hours)
    print(f"[OK] Guardian: {data['total_items']} items opgehaald", file=sys.stderr)

    # Output
    if a.merge_into:
        merge_into(data, Path(a.merge_into))
    elif a.output:
        Path(a.output).write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"[OK] Opgeslagen: {a.output}", file=sys.stderr)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
