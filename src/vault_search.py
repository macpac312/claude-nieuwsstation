#!/usr/bin/env python3
"""Vault Context Engine voor het Nieuwsstation.

Doorzoekt de Obsidian vault op relevante bestaande notes, zodat briefings
context kunnen meenemen uit eerder werk (IRB, AVM, CRR3, etc.).

Gebruik:
    python vault_search.py --query "LGD floors EBA"
    python vault_search.py --query "huizenprijzen CBS" --top 10
    python vault_search.py --keywords IRB CRR3 EGIM --output /tmp/vault.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT_PATH = Path.home() / "Documents" / "WorkMvMOBS"

# Mappen die we overslaan bij het doorzoeken
SKIP_DIRS = {
    ".obsidian", ".git", ".trash", "node_modules",
    "__pycache__", ".venv", "venv",
}

# Bestanden die we overslaan
SKIP_FILES = {
    "CLAUDE.md",
}


def parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter uit een markdown bestand."""
    if not content.startswith("---"):
        return {}

    end = content.find("---", 3)
    if end == -1:
        return {}

    fm_text = content[3:end].strip()
    result = {}

    for line in fm_text.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()

            # Simpele YAML parsing voor tags en lijsten
            if value.startswith("[") and value.endswith("]"):
                value = [v.strip().strip('"').strip("'")
                         for v in value[1:-1].split(",") if v.strip()]
            elif value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]

            result[key] = value

    return result


def extract_tags(content: str) -> list[str]:
    """Extraheer #tags uit markdown content."""
    # Match #tag maar niet #heading
    tags = re.findall(r'(?:^|\s)#([a-zA-Z][\w/\-]*)', content)
    return list(set(tags))


def extract_wikilinks(content: str) -> list[str]:
    """Extraheer [[wikilinks]] uit markdown content."""
    links = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content)
    return list(set(links))


def get_excerpt(content: str, keywords: list[str], context_chars: int = 200) -> str:
    """Geef een excerpt rondom de eerste keyword match."""
    # Strip frontmatter
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].strip()

    content_lower = content.lower()

    for kw in keywords:
        pos = content_lower.find(kw.lower())
        if pos != -1:
            start = max(0, pos - context_chars // 2)
            end = min(len(content), pos + len(kw) + context_chars // 2)

            excerpt = content[start:end].strip()
            if start > 0:
                excerpt = "..." + excerpt
            if end < len(content):
                excerpt = excerpt + "..."

            # Maak het leesbaar (verwijder excessive whitespace)
            excerpt = re.sub(r'\n{3,}', '\n\n', excerpt)
            return excerpt

    # Geen match, geef begin van content
    return content[:context_chars].strip() + "..." if len(content) > context_chars else content


def score_note(content: str, title: str, frontmatter: dict, tags: list[str],
               keywords: list[str]) -> float:
    """Bereken een relevantie-score voor een note."""
    score = 0.0
    text = f"{title} {content}".lower()
    fm_tags = frontmatter.get("tags", [])
    if isinstance(fm_tags, str):
        fm_tags = [fm_tags]

    for kw in keywords:
        kw_lower = kw.lower()

        # Titel match (zwaarst)
        if kw_lower in title.lower():
            score += 10.0

        # Frontmatter tag match
        if any(kw_lower in str(t).lower() for t in fm_tags):
            score += 5.0

        # Content tag match
        if any(kw_lower in t.lower() for t in tags):
            score += 3.0

        # Content match (frequentie)
        count = text.count(kw_lower)
        if count > 0:
            score += min(count * 1.0, 5.0)  # Max 5 punten per keyword

    # Bonus voor recente bestanden (frontmatter date)
    date_str = frontmatter.get("date", "")
    if date_str:
        try:
            note_date = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - note_date).days
            if age_days < 7:
                score *= 1.5
            elif age_days < 30:
                score *= 1.2
        except (ValueError, TypeError):
            pass

    return score


def search_vault(keywords: list[str], vault_path: Path = VAULT_PATH,
                 top_n: int = 10, min_score: float = 1.0) -> list[dict]:
    """Doorzoek de vault op relevante notes.

    Args:
        keywords: Lijst van zoektermen
        vault_path: Pad naar de Obsidian vault
        top_n: Maximum aantal resultaten
        min_score: Minimum score om mee te nemen

    Returns:
        Lijst van note-resultaten, gesorteerd op relevantie
    """
    results = []

    for root, dirs, files in os.walk(vault_path):
        # Skip uitgesloten directories
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for fname in files:
            if not fname.endswith(".md"):
                continue
            if fname in SKIP_FILES:
                continue

            filepath = Path(root) / fname
            try:
                content = filepath.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError):
                continue

            # Lege bestanden overslaan
            if len(content.strip()) < 10:
                continue

            title = fname.replace(".md", "")
            frontmatter = parse_frontmatter(content)
            tags = extract_tags(content)
            wikilinks = extract_wikilinks(content)

            score = score_note(content, title, frontmatter, tags, keywords)

            if score >= min_score:
                rel_path = filepath.relative_to(vault_path)
                excerpt = get_excerpt(content, keywords)

                results.append({
                    "title": title,
                    "path": str(rel_path),
                    "score": round(score, 1),
                    "excerpt": excerpt,
                    "tags": tags[:10],
                    "wikilinks": wikilinks[:10],
                    "frontmatter_tags": frontmatter.get("tags", []),
                    "date": str(frontmatter.get("date", "")),
                    "word_count": len(content.split()),
                })

    # Sorteer op score (hoogste eerst)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


def search_for_news_items(news_items: list[dict], vault_path: Path = VAULT_PATH,
                          top_n: int = 10) -> dict:
    """Doorzoek de vault op basis van nieuwsitems.

    Extraheert keywords uit nieuwstitels en zoekt gerelateerde vault notes.

    Args:
        news_items: Lijst van nieuwsitems (met 'title' en 'topic' keys)
        vault_path: Pad naar de Obsidian vault
        top_n: Maximum aantal resultaten

    Returns:
        Dict met vault resultaten en metadata
    """
    # Verzamel unieke keywords uit nieuwstitels
    all_keywords = set()
    for item in news_items:
        title = item.get("title", "")
        # Extraheer significante woorden (>3 chars, geen stopwoorden)
        stopwords = {"the", "and", "for", "that", "with", "from", "this",
                     "has", "have", "been", "will", "are", "was", "were",
                     "van", "het", "een", "voor", "met", "naar", "bij",
                     "dat", "die", "den", "des"}
        words = re.findall(r'\b[A-Za-z]{4,}\b', title)
        significant = [w for w in words if w.lower() not in stopwords]
        all_keywords.update(significant[:5])  # Max 5 per titel

    keywords = list(all_keywords)
    results = search_vault(keywords, vault_path, top_n)

    return {
        "searched_at": datetime.now(timezone.utc).isoformat(),
        "vault_path": str(vault_path),
        "keywords_used": keywords,
        "notes_found": len(results),
        "notes": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Nieuwsstation Vault Search")
    parser.add_argument("--query", type=str,
                        help="Zoekterm(en), spatie-gescheiden")
    parser.add_argument("--keywords", nargs="+",
                        help="Specifieke keywords om op te zoeken")
    parser.add_argument("--news-json", type=str,
                        help="Pad naar RSS fetcher output JSON (zoekt op basis van nieuwstitels)")
    parser.add_argument("--top", type=int, default=10,
                        help="Maximum aantal resultaten (default: 10)")
    parser.add_argument("--min-score", type=float, default=1.0,
                        help="Minimum relevantie-score (default: 1.0)")
    parser.add_argument("--vault", type=str,
                        help="Pad naar Obsidian vault (default: ~/Documents/WorkMvMOBS)")
    parser.add_argument("--output", type=str,
                        help="Output naar bestand (default: stdout)")

    args = parser.parse_args()

    vault_path = Path(args.vault) if args.vault else VAULT_PATH

    if not vault_path.exists():
        print(f"[ERROR] Vault niet gevonden: {vault_path}", file=sys.stderr)
        sys.exit(1)

    if args.news_json:
        # Zoek op basis van nieuwsitems
        news_data = json.loads(Path(args.news_json).read_text())
        all_items = []
        for topic_data in news_data.get("topics", {}).values():
            all_items.extend(topic_data.get("items", []))

        results = search_for_news_items(all_items, vault_path, args.top)
    elif args.keywords:
        keywords = args.keywords
        notes = search_vault(keywords, vault_path, args.top, args.min_score)
        results = {
            "searched_at": datetime.now(timezone.utc).isoformat(),
            "vault_path": str(vault_path),
            "keywords": keywords,
            "notes_found": len(notes),
            "notes": notes,
        }
    elif args.query:
        keywords = args.query.split()
        notes = search_vault(keywords, vault_path, args.top, args.min_score)
        results = {
            "searched_at": datetime.now(timezone.utc).isoformat(),
            "vault_path": str(vault_path),
            "query": args.query,
            "keywords": keywords,
            "notes_found": len(notes),
            "notes": notes,
        }
    else:
        print("[ERROR] Geef --query, --keywords, of --news-json op", file=sys.stderr)
        sys.exit(1)

    output_json = json.dumps(results, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(output_json)
        print(f"[OK] {results['notes_found']} notes gevonden, opgeslagen naar {args.output}",
              file=sys.stderr)
    else:
        print(output_json)

    print(f"[OK] {results['notes_found']} relevante notes gevonden in vault",
          file=sys.stderr)


if __name__ == "__main__":
    main()
