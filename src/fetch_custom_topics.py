#!/usr/bin/env python3
"""
Haal nieuwsartikelen op voor custom dagkrant-secties.

Strategie (in volgorde):
  1. Filter de al-opgehaalde Nederlandse RSS-data (dagkrant-ready.json) op keywords
  2. Zoek via The Guardian API (Engels; directe URLs, 2000 req/dag gratis)

Leest DAGKRANT_CUSTOM_TOPICS env var (JSON-array van TopicConfig-objecten).
Merget resultaten in /tmp/dagkrant-ready.json.

Gebruik:
    DAGKRANT_CUSTOM_TOPICS='[{"id":"wetenschap","label":"Wetenschap",
        "desc":"CERN, ruimtevaart, klimaat"}]' python3 fetch_custom_topics.py
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

READY        = Path("/tmp/dagkrant-ready.json")
GUARDIAN_KEY = Path.home() / ".config/nieuwsstation/guardian_api_key"
GUARDIAN_API = "https://content.guardianapis.com/search"
DEFAULT_HOURS = 48


# ── Guardian helpers ──────────────────────────────────────────────────────────

def _guardian_key() -> str:
    if GUARDIAN_KEY.exists():
        return GUARDIAN_KEY.read_text().strip()
    return os.environ.get("GUARDIAN_API_KEY", "")


def _fetch_guardian(query: str, api_key: str, topic_id: str,
                    hours: int = DEFAULT_HOURS, page_size: int = 6) -> list[dict]:
    """Zoek The Guardian op en geef artikelen terug als dicts (directe URLs)."""
    from urllib.request import urlopen, Request
    from urllib.parse import urlencode
    from urllib.error import HTTPError, URLError

    from_date = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d")
    params = {
        "q":           query,
        "from-date":   from_date,
        "show-fields": "trailText,thumbnail",
        "page-size":   min(page_size, 20),
        "order-by":    "relevance",
        "api-key":     api_key,
    }
    url = f"{GUARDIAN_API}?{urlencode(params)}"
    try:
        req = Request(url, headers={"User-Agent": "nieuwsstation/1.0"})
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except (HTTPError, URLError) as e:
        print(f"[custom] WARN Guardian '{query[:40]}': {e}", file=sys.stderr)
        return []

    items = []
    for art in data.get("response", {}).get("results", []):
        fields    = art.get("fields", {})
        trail     = re.sub(r"<[^>]+>", "", fields.get("trailText", "")).strip()
        pub_str   = art.get("webPublicationDate", "")
        try:
            pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00")).isoformat()
        except Exception:
            pub = ""
        items.append({
            "title":     art.get("webTitle", ""),
            "link":      art.get("webUrl", ""),
            "summary":   trail[:400],
            "source":    "The Guardian",
            "published": pub,
            "topic":     topic_id,
        })
    return items


# ── Dutch RSS filter ──────────────────────────────────────────────────────────

def _filter_existing(data: dict, keywords: list[str], topic_id: str,
                     max_results: int = 8) -> list[dict]:
    """
    Zoek door al-opgehaalde RSS-artikelen op keywords.
    Geeft artikelen terug die minstens één keyword bevatten in titel of summary.
    """
    if not keywords:
        return []

    patterns = [re.compile(re.escape(kw), re.IGNORECASE) for kw in keywords]
    found: list[dict] = []
    seen_links: set[str] = set()

    for tid, tdata in data.get("topics", {}).items():
        if tid == topic_id:
            continue  # skip eigen topic
        for art in tdata.get("items", []):
            link  = art.get("link", "")
            title = art.get("title", "")
            desc  = art.get("summary", art.get("description", ""))
            text  = f"{title} {desc}"
            if link in seen_links:
                continue
            if "news.google.com" in link:
                continue  # skip Google News redirect-URLs
            for pat in patterns:
                if pat.search(text):
                    seen_links.add(link)
                    found.append({
                        "title":     title,
                        "link":      link,
                        "summary":   desc[:400],
                        "source":    art.get("source", ""),
                        "published": art.get("published", ""),
                        "topic":     topic_id,
                    })
                    break
            if len(found) >= max_results:
                break
        if len(found) >= max_results:
            break

    return found


_NL_EN: dict[str, str] = {
    "klimaat":          "climate",
    "klimaatverandering": "climate change",
    "ruimtevaart":      "space exploration",
    "ruimte":           "space",
    "wetenschap":       "science",
    "economie":         "economy",
    "politiek":         "politics",
    "gezondheid":       "health",
    "energie":          "energy",
    "oorlog":           "war",
    "conflict":         "conflict",
    "technologie":      "technology",
    "onderwijs":        "education",
    "woningmarkt":      "housing market",
    "hypotheek":        "mortgage",
    "rente":            "interest rate",
    "inflatie":         "inflation",
    "verkiezingen":     "elections",
    "immigratie":       "immigration",
    "milieu":           "environment",
    "duurzaamheid":     "sustainability",
    "voetbal":          "football soccer",
    "schaatsen":        "skating",
    "wielrennen":       "cycling",
    "autorijden":       "driving",
}


def _nl_to_en(keyword: str) -> str:
    """Vertaal een Nederlands zoekwoord naar Engels voor de Guardian query."""
    return _NL_EN.get(keyword.lower().strip(), keyword)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    raw = os.environ.get("DAGKRANT_CUSTOM_TOPICS", "[]")
    try:
        custom_topics = json.loads(raw)
    except Exception:
        custom_topics = []

    if not custom_topics:
        print("[custom] Geen custom topics — klaar.", flush=True)
        sys.exit(0)

    # Laad bestaande ready.json
    if READY.exists():
        try:
            data = json.loads(READY.read_text())
        except Exception:
            data = {"topics": {}, "total_items": 0}
    else:
        data = {"topics": {}, "total_items": 0}

    # Alle al-aanwezige URLs (voor globale deduplicatie binnen één custom topic)
    all_urls: set[str] = {
        it["link"]
        for t in data.get("topics", {}).values()
        for it in t.get("items", [])
        if it.get("link")
    }

    guardian_key = _guardian_key()

    added_total = 0
    for ct in custom_topics:
        cid   = ct.get("id", "").strip()
        label = ct.get("label", cid).strip()
        desc  = ct.get("desc", "").strip()

        if not cid:
            continue

        # Bouw keyword-lijst op uit desc
        keywords = [k.strip() for k in desc.split(",") if k.strip()] if desc else [label]

        # URLs al in dit custom topic (voorkomen echte dubbels)
        topic_urls: set[str] = {
            it["link"]
            for it in data.get("topics", {}).get(cid, {}).get("items", [])
            if it.get("link")
        }
        seen_in_batch: set[str] = set()

        new_items: list[dict] = []

        # ── Stap 1: Filter bestaande RSS-data op keywords ─────────────────
        nl_items = _filter_existing(data, keywords, cid, max_results=6)
        for it in nl_items:
            lnk = it["link"]
            if lnk not in topic_urls and lnk not in seen_in_batch:
                new_items.append(it)
                seen_in_batch.add(lnk)

        print(f"[custom] {label}: {len(nl_items)} Nederlandse artikelen via RSS-filter", flush=True)

        # ── Stap 2: Guardian API (Engels, directe URLs) ───────────────────
        if guardian_key:
            # Guardian werkt met Engelse termen; vertaal veelvoorkomende NL woorden
            en_keywords = [_nl_to_en(kw) for kw in keywords[:4]]
            query = " OR ".join(en_keywords)
            guardian_items = _fetch_guardian(query, guardian_key, cid)
            added_from_guardian = 0
            for it in guardian_items:
                lnk = it["link"]
                if lnk not in topic_urls and lnk not in seen_in_batch:
                    new_items.append(it)
                    seen_in_batch.add(lnk)
                    added_from_guardian += 1
            print(f"[custom] {label}: {added_from_guardian} artikelen via Guardian", flush=True)
        else:
            print(f"[custom] {label}: geen Guardian API key, Guardian overgeslagen", flush=True)

        if new_items:
            existing_in_topic = data.setdefault("topics", {}).get(cid, {}).get("items", [])
            merged = existing_in_topic + new_items
            data["topics"][cid] = {
                "items":      merged,
                "item_count": len(merged),
            }
            data["total_items"] = data.get("total_items", 0) + len(new_items)
            added_total += len(new_items)
            print(f"[custom] {label}: {len(new_items)} artikelen toegevoegd ({len(merged)} totaal)", flush=True)
        else:
            print(f"[custom] {label}: geen nieuwe artikelen gevonden", flush=True)

    READY.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"[custom] Klaar: {added_total} artikelen totaal in dagkrant-ready.json", flush=True)


if __name__ == "__main__":
    main()
