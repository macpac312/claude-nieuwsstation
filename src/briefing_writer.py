#!/usr/bin/env python3
"""Briefing Writer voor het Nieuwsstation.

Combineert RSS data en vault context tot een gestructureerd JSON-bestand
dat door de Obsidian plugin gerenderd wordt als interactieve briefing view.

Gebruik:
    python briefing_writer.py --rss /tmp/rss.json --vault /tmp/vault.json --output ~/Documents/WorkMvMOBS/Briefings/data/2026-03-21.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT_PATH = Path.home() / "Documents" / "WorkMvMOBS"
BRIEFINGS_PATH = VAULT_PATH / "Briefings"


def build_briefing(rss_data: dict, vault_data: dict | None = None,
                   focus: str | None = None) -> dict:
    """Bouw een gestructureerd briefing object."""

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    months_nl = ["januari", "februari", "maart", "april", "mei", "juni",
                 "juli", "augustus", "september", "oktober", "november", "december"]
    date_nl = f"{now.day} {months_nl[now.month - 1]} {now.year}"

    briefing = {
        "version": 1,
        "date": date_str,
        "date_nl": date_nl,
        "generated": now.isoformat(),
        "focus": focus,
        "total_sources": rss_data.get("total_items", 0),
        "topics": [],
        "vault_notes": [],
        "cross_analysis": "",
    }

    # Topics met artikelen
    topic_meta = {
        "regulatoir": {"icon": "📋", "color": "#89b4fa", "label": "Regulatoir"},
        "huizenmarkt": {"icon": "🏠", "color": "#a6e3a1", "label": "Huizenmarkt"},
        "financieel": {"icon": "📊", "color": "#fab387", "label": "Financieel"},
        "tech": {"icon": "⚡", "color": "#cba6f7", "label": "Tech & AI"},
        "sport": {"icon": "⚽", "color": "#a6e3a1", "label": "Sport"},
        "ai_nieuws": {"icon": "🤖", "color": "#cba6f7", "label": "AI Nieuws"},
    }

    for topic_id, topic_data in rss_data.get("topics", {}).items():
        items = topic_data.get("items", [])
        if not items:
            continue

        meta = topic_meta.get(topic_id, {"icon": "📰", "color": "#cdd6f4", "label": topic_id})

        articles = []
        for item in items[:10]:  # Max 10 per topic
            article = {
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "link": item.get("link", ""),
                "published": item.get("published", ""),
                "source_name": item.get("source_name", ""),
                "source_type": item.get("source_type", "article"),
                "source_url": _extract_domain(item.get("link", "")),
                # Placeholders voor Claude-gegenereerde content
                "extended_summary": "",
                "impact_analysis": "",
                "action_items": [],
                "vault_links": [],
                "tags": [],
            }
            articles.append(article)

        briefing["topics"].append({
            "id": topic_id,
            "label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "article_count": len(articles),
            "articles": articles,
        })

    # Vault context
    if vault_data:
        for note in vault_data.get("notes", [])[:10]:
            briefing["vault_notes"].append({
                "title": note.get("title", ""),
                "path": note.get("path", ""),
                "score": note.get("score", 0),
                "excerpt": note.get("excerpt", ""),
                "tags": note.get("tags", []),
            })

    return briefing


def _extract_domain(url: str) -> str:
    """Extraheer domein uit URL."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc.replace("www.", "")
    except Exception:
        return ""


def save_briefing(briefing: dict, output_path: Path | None = None) -> Path:
    """Sla briefing op als JSON."""
    if not output_path:
        data_dir = BRIEFINGS_PATH / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        output_path = data_dir / f"{briefing['date']}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(briefing, ensure_ascii=False, indent=2))
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Nieuwsstation Briefing Writer")
    parser.add_argument("--rss", required=True, help="Pad naar RSS fetcher output JSON")
    parser.add_argument("--vault", help="Pad naar vault search output JSON")
    parser.add_argument("--focus", help="Focus prompt")
    parser.add_argument("--output", help="Output pad voor briefing JSON")

    args = parser.parse_args()

    rss_data = json.loads(Path(args.rss).read_text())
    vault_data = json.loads(Path(args.vault).read_text()) if args.vault else None

    briefing = build_briefing(rss_data, vault_data, args.focus)

    output_path = Path(args.output) if args.output else None
    saved_path = save_briefing(briefing, output_path)

    print(json.dumps(briefing, ensure_ascii=False, indent=2))
    print(f"\n[OK] Briefing opgeslagen: {saved_path}", file=sys.stderr)
    print(f"[OK] {len(briefing['topics'])} topics, "
          f"{sum(t['article_count'] for t in briefing['topics'])} artikelen",
          file=sys.stderr)


if __name__ == "__main__":
    main()
