#!/usr/bin/env python3
"""RSS Feed Fetcher voor het Nieuwsstation.

Haalt nieuwsitems op uit geconfigureerde RSS feeds, filtert op recency
en optioneel op keywords per topic.

Gebruik:
    python rss_fetcher.py --topics regulatoir huizenmarkt --hours 24
    python rss_fetcher.py --all --hours 48 --output /tmp/rss.json
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import mktime

import feedparser
import requests
import yaml

CONFIG_PATH = Path(__file__).parent / "config" / "sources.yaml"


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    """Laad de sources configuratie."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def parse_feed(feed_url: str, source_name: str, source_type: str,
               topic: str, max_age_hours: int = 24,
               keywords: list[str] | None = None) -> list[dict]:
    """Parse een enkele RSS feed en retourneer gefilterde items."""
    try:
        # Sommige feeds (EBA, DNB, BIS) leveren HTML of broken XML.
        # Eerst als raw text ophalen, dan feedparser erop loslaten.
        resp = requests.get(feed_url, timeout=15, headers={
            "User-Agent": "Nieuwsstation/1.0 (RSS Reader)",
        })
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except requests.RequestException as e:
        print(f"  [WARN] Kon feed niet ophalen: {source_name} ({e})", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  [WARN] Kon feed niet parsen: {source_name} ({e})", file=sys.stderr)
        return []

    if feed.bozo and not feed.entries:
        print(f"  [WARN] Feed error voor {source_name}: {feed.bozo_exception}", file=sys.stderr)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    items = []

    for entry in feed.entries:
        # Publicatiedatum bepalen
        published = None
        for date_field in ("published_parsed", "updated_parsed", "created_parsed"):
            parsed_time = getattr(entry, date_field, None)
            if parsed_time:
                published = datetime.fromtimestamp(mktime(parsed_time), tz=timezone.utc)
                break

        # Als geen datum gevonden, neem item mee (kan recenter zijn dan we denken)
        if published and published < cutoff:
            continue

        title = getattr(entry, "title", "Geen titel")
        summary = getattr(entry, "summary", getattr(entry, "description", ""))
        link = getattr(entry, "link", "")

        # Strip HTML tags uit summary
        summary_clean = re.sub(r"<[^>]+>", "", summary).strip()
        # Beperk summary lengte
        if len(summary_clean) > 500:
            summary_clean = summary_clean[:497] + "..."

        # Keyword filtering (optioneel)
        if keywords:
            text = f"{title} {summary_clean}".lower()
            if not any(kw.lower() in text for kw in keywords):
                continue

        # Probeer afbeelding URL te extraheren
        image_url = ""
        if hasattr(entry, "media_content") and entry.media_content:
            image_url = entry.media_content[0].get("url", "")
        elif hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            image_url = entry.media_thumbnail[0].get("url", "")
        elif hasattr(entry, "enclosures") and entry.enclosures:
            for enc in entry.enclosures:
                if enc.get("type", "").startswith("image/"):
                    image_url = enc.get("href", enc.get("url", ""))
                    break
        if not image_url:
            # Zoek in de summary naar img tags
            img_match = re.search(r'<img[^>]+src=["\']([^"\']+)', summary)
            if img_match:
                image_url = img_match.group(1)

        items.append({
            "title": title,
            "link": link,
            "summary": summary_clean,
            "published": published.isoformat() if published else None,
            "source_name": source_name,
            "source_type": source_type,
            "topic": topic,
            "feed_url": feed_url,
            "image_url": image_url,
        })

    return items


def fetch_topics(topics: list[str] | None = None, hours: int = 24,
                 filter_keywords: bool = True,
                 config_path: Path = CONFIG_PATH) -> dict:
    """Haal items op voor de opgegeven topics (of alle topics).

    Returns:
        Dict met metadata en items per topic.
    """
    config = load_config(config_path)
    all_topics = config.get("topics", {})

    if topics:
        selected = {t: all_topics[t] for t in topics if t in all_topics}
        unknown = [t for t in topics if t not in all_topics]
        if unknown:
            print(f"[WARN] Onbekende topics: {', '.join(unknown)}", file=sys.stderr)
            print(f"  Beschikbaar: {', '.join(all_topics.keys())}", file=sys.stderr)
    else:
        selected = all_topics

    results = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "hours": hours,
        "topics_requested": list(selected.keys()),
        "total_items": 0,
        "topics": {},
    }

    for topic_name, topic_config in selected.items():
        print(f"[INFO] Ophalen: {topic_name} ({len(topic_config.get('feeds', []))} feeds)...",
              file=sys.stderr)

        keywords = topic_config.get("keywords", []) if filter_keywords else None
        topic_items = []

        for feed in topic_config.get("feeds", []):
            print(f"  → {feed['name']}...", file=sys.stderr)
            items = parse_feed(
                feed_url=feed["url"],
                source_name=feed["name"],
                source_type=feed.get("type", "article"),
                topic=topic_name,
                max_age_hours=hours,
                keywords=keywords,
            )
            topic_items.extend(items)
            print(f"    {len(items)} items gevonden", file=sys.stderr)

        # Sorteer op publicatiedatum (nieuwste eerst)
        topic_items.sort(
            key=lambda x: x.get("published") or "",
            reverse=True,
        )

        # Deduplicatie op titel
        seen_titles = set()
        unique_items = []
        for item in topic_items:
            title_key = item["title"].lower().strip()
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique_items.append(item)

        results["topics"][topic_name] = {
            "icon": topic_config.get("icon", ""),
            "color": topic_config.get("color", ""),
            "item_count": len(unique_items),
            "items": unique_items,
        }
        results["total_items"] += len(unique_items)

    return results


def main():
    parser = argparse.ArgumentParser(description="Nieuwsstation RSS Fetcher")
    parser.add_argument("--topics", nargs="+",
                        help="Topics om op te halen (bijv. regulatoir huizenmarkt)")
    parser.add_argument("--all", action="store_true",
                        help="Alle topics ophalen")
    parser.add_argument("--hours", type=int, default=24,
                        help="Maximale leeftijd van items in uren (default: 24)")
    parser.add_argument("--no-filter", action="store_true",
                        help="Keyword filtering uitschakelen")
    parser.add_argument("--output", type=str,
                        help="Output naar bestand (default: stdout)")
    parser.add_argument("--config", type=str,
                        help="Pad naar sources.yaml (default: src/config/sources.yaml)")

    args = parser.parse_args()

    config_path = Path(args.config) if args.config else CONFIG_PATH

    if not config_path.exists():
        print(f"[ERROR] Config niet gevonden: {config_path}", file=sys.stderr)
        sys.exit(1)

    topics = None if args.all else args.topics
    if not topics and not args.all:
        # Default: alle topics
        topics = None

    results = fetch_topics(
        topics=topics,
        hours=args.hours,
        filter_keywords=not args.no_filter,
        config_path=config_path,
    )

    output_json = json.dumps(results, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(output_json)
        print(f"\n[OK] {results['total_items']} items opgeslagen naar {args.output}",
              file=sys.stderr)
    else:
        print(output_json)

    print(f"\n[OK] Totaal: {results['total_items']} items uit "
          f"{len(results['topics'])} topics", file=sys.stderr)


if __name__ == "__main__":
    main()
