#!/usr/bin/env python3
"""News API client voor het Nieuwsstation.

Haalt top headlines en zoekresultaten op via de News API (free tier, 100 req/dag).
API key wordt gelezen uit ~/.config/nieuwsstation/newsapi_key.

Gebruik:
    python news_api.py --query "ECB rate decision" --language nl
    python news_api.py --headlines --country nl
    python news_api.py --query "CRR3 Basel" --language en --output /tmp/news.json
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API_KEY_PATH = Path.home() / ".config" / "nieuwsstation" / "newsapi_key"
BASE_URL = "https://newsapi.org/v2"


def load_api_key(key_path: Path = API_KEY_PATH) -> str | None:
    """Laad de News API key uit het configuratiebestand."""
    if not key_path.exists():
        return None
    return key_path.read_text().strip()


def search_news(query: str, language: str = "nl", hours: int = 24,
                page_size: int = 20, api_key: str | None = None) -> dict:
    """Zoek nieuwsartikelen via de News API /everything endpoint."""
    if not api_key:
        api_key = load_api_key()
    if not api_key:
        return _no_key_response()

    from_date = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")

    params = {
        "q": query,
        "language": language,
        "from": from_date,
        "sortBy": "relevancy",
        "pageSize": page_size,
        "apiKey": api_key,
    }

    try:
        resp = requests.get(f"{BASE_URL}/everything", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return _error_response(str(e))

    return _format_response(data, query=query, language=language)


def get_headlines(country: str = "nl", category: str | None = None,
                  page_size: int = 20, api_key: str | None = None) -> dict:
    """Haal top headlines op via de News API /top-headlines endpoint."""
    if not api_key:
        api_key = load_api_key()
    if not api_key:
        return _no_key_response()

    params = {
        "country": country,
        "pageSize": page_size,
        "apiKey": api_key,
    }
    if category:
        params["category"] = category

    try:
        resp = requests.get(f"{BASE_URL}/top-headlines", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return _error_response(str(e))

    return _format_response(data, country=country, category=category)


def _format_response(data: dict, **meta) -> dict:
    """Formatteer News API response naar Nieuwsstation formaat."""
    articles = []
    for article in data.get("articles", []):
        articles.append({
            "title": article.get("title", ""),
            "link": article.get("url", ""),
            "summary": article.get("description", "") or "",
            "published": article.get("publishedAt", ""),
            "source_name": article.get("source", {}).get("name", "News API"),
            "source_type": "news_api",
            "author": article.get("author", ""),
            "image_url": article.get("urlToImage", ""),
        })

    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "total_results": data.get("totalResults", 0),
        "item_count": len(articles),
        "items": articles,
        **meta,
    }


def _no_key_response() -> dict:
    return {
        "status": "error",
        "error": "Geen API key gevonden",
        "help": f"Sla je News API key op in: {API_KEY_PATH}\n"
                "Registreer gratis op: https://newsapi.org/register",
        "items": [],
    }


def _error_response(error: str) -> dict:
    return {
        "status": "error",
        "error": error,
        "items": [],
    }


def main():
    parser = argparse.ArgumentParser(description="Nieuwsstation News API Client")
    parser.add_argument("--query", type=str,
                        help="Zoekterm voor nieuws")
    parser.add_argument("--headlines", action="store_true",
                        help="Haal top headlines op")
    parser.add_argument("--country", type=str, default="nl",
                        help="Land voor headlines (default: nl)")
    parser.add_argument("--category", type=str,
                        help="Categorie: business, technology, science, health, general")
    parser.add_argument("--language", type=str, default="nl",
                        help="Taal voor zoekresultaten (default: nl)")
    parser.add_argument("--hours", type=int, default=24,
                        help="Maximale leeftijd van items in uren (default: 24)")
    parser.add_argument("--output", type=str,
                        help="Output naar bestand (default: stdout)")

    args = parser.parse_args()

    if not args.query and not args.headlines:
        print("[ERROR] Geef --query of --headlines op", file=sys.stderr)
        sys.exit(1)

    if args.headlines:
        results = get_headlines(
            country=args.country,
            category=args.category,
        )
    else:
        results = search_news(
            query=args.query,
            language=args.language,
            hours=args.hours,
        )

    output_json = json.dumps(results, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(output_json)
        print(f"[OK] {results.get('item_count', 0)} items opgeslagen naar {args.output}",
              file=sys.stderr)
    else:
        print(output_json)

    if results.get("status") == "error":
        print(f"[ERROR] {results['error']}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"[OK] {results.get('item_count', 0)} items opgehaald", file=sys.stderr)


if __name__ == "__main__":
    main()
