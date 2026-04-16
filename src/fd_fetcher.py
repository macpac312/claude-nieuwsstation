#!/usr/bin/env python3
"""FD.nl fetcher met authenticatie, volledige tekst en archief-zoekopdrachten.

Logt in op fd.nl met credentials uit .env. Haalt RSS-feeds op met volledige
artikeltekst, en kan het FD-archief doorzoeken op focus-onderwerpen.

Gebruik:
    python fd_fetcher.py                         # Voorpagina, 24 uur
    python fd_fetcher.py --hours 48 --full-text  # Met volledige tekst
    python fd_fetcher.py --all-sections          # Alle secties
    python fd_fetcher.py --search "IRB modellen" # Archief zoeken
    python fd_fetcher.py --focus ~/nieuwsstation/focus.md  # Focus-zoekopdrachten
    python fd_fetcher.py --output /tmp/fd.json
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import mktime

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Laad .env uit project root
ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_PATH)

FD_BASE = "https://fd.nl"
FD_LOGIN_URL = f"{FD_BASE}/login"
FD_SEARCH_URL = f"{FD_BASE}/zoeken"
FD_RSS_URL = f"{FD_BASE}/?rss"
FD_SECTION_RSS = {
    "voorpagina":        f"{FD_BASE}/?rss",
    "economie":          f"{FD_BASE}/economie?rss",
    "bedrijfsleven":     f"{FD_BASE}/bedrijfsleven?rss",
    "financiele-markten":f"{FD_BASE}/financiele-markten?rss",
    "politiek":          f"{FD_BASE}/politiek?rss",
    "tech-en-innovatie": f"{FD_BASE}/tech-en-innovatie?rss",
    "opinie":            f"{FD_BASE}/opinie?rss",
    "samenleving":       f"{FD_BASE}/samenleving?rss",
}

# Secties die meest relevant zijn voor financieel/regulatoir nieuws
DEFAULT_SECTIONS = ["voorpagina", "economie", "financiele-markten", "bedrijfsleven"]


# ─── Authenticatie ────────────────────────────────────────────────────────────

def create_fd_session() -> requests.Session | None:
    """Log in op fd.nl via Keycloak OIDC en retourneer authenticated session.

    FD gebruikt login.fdmg.nl (Keycloak) als identity provider. De flow is:
      1. GET fd.nl/login  -> redirect naar Keycloak login pagina
      2. POST username    -> krijg password-formulier terug
      3. POST username + password -> redirect terug naar fd.nl met sessie-cookies
    """
    email = os.getenv("FD_EMAIL")
    password = os.getenv("FD_PASSWORD")

    if not email or not password:
        print("[WARN] FD credentials niet geconfigureerd in .env", file=sys.stderr)
        return None

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    })

    try:
        # Stap 1: Haal Keycloak login pagina op (fd.nl/login redirectt)
        r1 = session.get(FD_LOGIN_URL, timeout=15)
        soup1 = BeautifulSoup(r1.text, "html.parser")
        form1 = soup1.find("form")
        if not form1:
            print("[WARN] FD login: geen form gevonden op Keycloak pagina", file=sys.stderr)
            return None
        action1 = form1.get("action", "")

        # Stap 2: POST username (Keycloak toont eerst email, dan password)
        r2 = session.post(action1, data={"username": email},
                          timeout=15, allow_redirects=True)
        soup2 = BeautifulSoup(r2.text, "html.parser")
        form2 = soup2.find("form")
        if not form2:
            print("[WARN] FD login: geen password form na username stap", file=sys.stderr)
            return None
        action2 = form2.get("action", "")

        # Stap 3: POST username + password -> redirect naar fd.nl
        r3 = session.post(action2, data={"username": email, "password": password},
                          timeout=15, allow_redirects=True)

        if "Uitloggen" in r3.text:
            print("[OK] FD login succesvol (Keycloak OIDC)", file=sys.stderr)
        else:
            print("[INFO] FD login status onzeker, doorgaan...", file=sys.stderr)
        return session

    except requests.RequestException as e:
        print(f"[WARN] FD login mislukt: {e}", file=sys.stderr)
        return None


# ─── Volledige artikeltekst ───────────────────────────────────────────────────

def fetch_full_text(url: str, session: requests.Session) -> str:
    """Haal volledige artikeltekst op van een FD-artikel URL.

    Parseert de article body. Geeft lege string bij mislukking.
    """
    try:
        time.sleep(0.5)  # beleefd wachten tussen requests
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # FD artikel-body zit in <article> of specifieke div
        # Probeer meerdere selectors
        patterns = [
            r'<article[^>]*>(.*?)</article>',
            r'class="[^"]*article[_-]body[^"]*"[^>]*>(.*?)</div>',
            r'class="[^"]*article__content[^"]*"[^>]*>(.*?)</div>',
            r'class="[^"]*body-text[^"]*"[^>]*>(.*?)</(?:div|section)>',
        ]

        raw = ""
        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if match:
                raw = match.group(1)
                break

        if not raw:
            # Fallback: extraheer alle <p> tags uit de pagina body
            paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL)
            # Filter navigatie/footer paragrafen (te kort of bevatten links)
            content_paras = [p for p in paragraphs
                             if len(p) > 80 and '<a href' not in p[:50]]
            raw = " ".join(content_paras[:20])

        # Opschonen
        text = re.sub(r'<[^>]+>', ' ', raw)          # HTML tags weg
        text = re.sub(r'&nbsp;', ' ', text)
        text = re.sub(r'&amp;', '&', text)
        text = re.sub(r'&lt;', '<', text)
        text = re.sub(r'&gt;', '>', text)
        text = re.sub(r'&#\d+;', '', text)
        text = re.sub(r'\s+', ' ', text).strip()

        # Minimale lengte check — minder dan 100 woorden = waarschijnlijk paywall-blokker
        if len(text.split()) < 100:
            return ""

        return text

    except requests.RequestException:
        return ""


# ─── RSS feeds ophalen ────────────────────────────────────────────────────────

def fetch_fd_rss(
    session: requests.Session | None = None,
    sections: list[str] | None = None,
    max_age_hours: int = 24,
    full_text: bool = False,
    max_full_text: int = 8,
) -> list[dict]:
    """Haal FD RSS feeds op.

    Args:
        session:       Authenticated session (of None voor anoniem)
        sections:      FD secties (default: DEFAULT_SECTIONS)
        max_age_hours: Maximale leeftijd van items
        full_text:     Volledige artikeltekst ophalen voor elk item
        max_full_text: Max aantal artikelen waarvoor volledige tekst wordt opgehaald
    """
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": "Nieuwsstation/1.0"})

    sections_to_use = sections or DEFAULT_SECTIONS
    urls_to_fetch = {
        sec: FD_SECTION_RSS[sec]
        for sec in sections_to_use
        if sec in FD_SECTION_RSS
    }

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    all_items = []
    seen_titles: set[str] = set()

    for section_name, url in urls_to_fetch.items():
        try:
            resp = session.get(url, timeout=15)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except requests.RequestException as e:
            print(f"  [WARN] FD sectie {section_name}: {e}", file=sys.stderr)
            continue

        for entry in feed.entries:
            published = None
            for date_field in ("published_parsed", "updated_parsed"):
                pt = getattr(entry, date_field, None)
                if pt:
                    published = datetime.fromtimestamp(mktime(pt), tz=timezone.utc)
                    break

            if published and published < cutoff:
                continue

            title = getattr(entry, "title", "").strip()
            if not title or title.lower() in seen_titles:
                continue
            seen_titles.add(title.lower())

            summary = getattr(entry, "summary", getattr(entry, "description", ""))
            summary_clean = re.sub(r"<[^>]+>", "", summary).strip()[:500]

            link = getattr(entry, "link", "")

            image_url = ""
            if hasattr(entry, "media_content") and entry.media_content:
                image_url = entry.media_content[0].get("url", "")
            elif hasattr(entry, "enclosures") and entry.enclosures:
                for enc in entry.enclosures:
                    if enc.get("type", "").startswith("image/"):
                        image_url = enc.get("href", enc.get("url", ""))
                        break

            all_items.append({
                "title": title,
                "link": link,
                "summary": summary_clean,
                "full_text": "",
                "published": published.isoformat() if published else None,
                "source_name": "Financieel Dagblad",
                "source_type": "article",
                "topic": "financieel",
                "section": section_name,
                "has_full_text": False,
                "word_count": 0,
                "image_url": image_url,
            })

    # Sorteer op datum
    all_items.sort(key=lambda x: x.get("published") or "", reverse=True)

    # Volledige tekst ophalen voor top-N artikelen
    if full_text and session and all_items:
        print(f"  [FD] Volledige tekst ophalen voor max {max_full_text} artikelen...",
              file=sys.stderr)
        ft_count = 0
        for item in all_items:
            if ft_count >= max_full_text:
                break
            if not item["link"]:
                continue
            text = fetch_full_text(item["link"], session)
            if text:
                item["full_text"] = text
                item["has_full_text"] = True
                item["word_count"] = len(text.split())
                # Vervang samenvatting door eerste 300 woorden als die beter is
                if len(text) > len(item["summary"]):
                    words = text.split()[:60]
                    item["summary"] = " ".join(words) + ("..." if len(text.split()) > 60 else "")
                ft_count += 1

        print(f"  [FD] {ft_count} artikelen met volledige tekst", file=sys.stderr)

    print(f"[OK] FD: {len(all_items)} artikelen opgehaald", file=sys.stderr)
    return all_items


# ─── Archief zoeken ───────────────────────────────────────────────────────────

def search_fd(
    query: str,
    session: requests.Session,
    days_back: int = 90,
    max_results: int = 5,
) -> list[dict]:
    """Zoek in het FD-archief op een zoekterm.

    Returns: lijst van artikel-dicts (zelfde formaat als fetch_fd_rss).
    """
    # FD.nl geeft 500 op sort=date en dateFrom — gebruik alleen q param
    params = {"q": query}

    results = []
    try:
        resp = session.get(FD_SEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # Extraheer artikel-links uit zoekresultaten
        # FD zoekresultaten: href="/sectie/ID/slug"
        article_pattern = re.findall(
            r'href="(/[a-z-]+/(\d+)/([a-z0-9-]+))"',
            html
        )

        seen_ids: set[str] = set()
        for path, art_id, slug in article_pattern:
            if art_id in seen_ids:
                continue
            seen_ids.add(art_id)

            url = f"{FD_BASE}{path}"
            # Gebruik slug als titel-fallback (leesbaar genoeg voor dagkrant)
            title_clean = slug.replace('-', ' ').title()

            if len(title_clean) < 10:
                continue

            # Haal volledige tekst op
            full_text = fetch_full_text(url, session)

            results.append({
                "title": title_clean,
                "link": url,
                "summary": (full_text[:300] + "...") if full_text else "",
                "full_text": full_text,
                "published": None,
                "source_name": "Financieel Dagblad",
                "source_type": "article",
                "topic": "financieel",
                "section": "zoekresultaat",
                "has_full_text": bool(full_text),
                "word_count": len(full_text.split()) if full_text else 0,
                "search_query": query,
                "image_url": "",
            })

            if len(results) >= max_results:
                break

    except requests.RequestException as e:
        print(f"  [WARN] FD zoeken mislukt voor '{query}': {e}", file=sys.stderr)

    return results


def fetch_focus_articles(
    focus_path: Path,
    session: requests.Session,
    days_back: int = 30,
    max_per_topic: int = 4,
) -> list[dict]:
    """Zoek FD-archief op basis van focus.md onderwerpen.

    Returns: gecombineerde lijst van artikelen voor alle focus-onderwerpen.
    """
    if not focus_path.exists():
        return []

    all_results = []
    seen_urls: set[str] = set()

    for line in focus_path.read_text().split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("##"):
            continue
        if not line.startswith("- "):
            continue

        entry = line[2:].strip()
        if ":" in entry:
            label, keywords_raw = entry.split(":", 1)
            # Gebruik eerste 2 keywords als FD-zoekopdracht
            keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
            query = " ".join(keywords[:2])
            label = label.strip()
        else:
            query = entry
            label = entry

        if not query:
            continue

        print(f"  [FD archief] '{label}': zoeken op '{query}'...", file=sys.stderr)
        results = search_fd(query, session, days_back=days_back, max_results=max_per_topic)
        time.sleep(1.5)  # Rate limiting tussen zoekopdrachten

        for r in results:
            if r["link"] not in seen_urls:
                seen_urls.add(r["link"])
                r["focus_label"] = label
                all_results.append(r)

    return all_results


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FD.nl fetcher met volledige tekst")
    parser.add_argument("--hours", type=int, default=24,
                        help="Maximale leeftijd RSS-items (default: 24)")
    parser.add_argument("--sections", nargs="+", choices=list(FD_SECTION_RSS.keys()),
                        help="FD secties (default: voorpagina + economie + markten + bedrijfsleven)")
    parser.add_argument("--all-sections", action="store_true",
                        help="Alle FD secties ophalen")
    parser.add_argument("--full-text", action="store_true",
                        help="Volledige tekst ophalen per artikel")
    parser.add_argument("--max-full-text", type=int, default=8,
                        help="Max artikelen voor volledige tekst (default: 8)")
    parser.add_argument("--search", type=str,
                        help="Zoek in FD-archief op query")
    parser.add_argument("--days-back", type=int, default=90,
                        help="Archief-zoekopdracht: dagen terug (default: 90)")
    parser.add_argument("--focus", type=str,
                        help="Pad naar focus.md voor archief-zoekopdrachten")
    parser.add_argument("--output", type=str,
                        help="Output naar bestand (default: stdout)")
    args = parser.parse_args()

    session = create_fd_session()

    all_items = []

    # Archief-zoekopdracht (enkelvoudig)
    if args.search:
        if not session:
            print("[ERR] Archief-zoekopdracht vereist ingelogde sessie", file=sys.stderr)
            sys.exit(1)
        print(f"[FD] Archief zoeken: '{args.search}'...", file=sys.stderr)
        results = search_fd(args.search, session, days_back=args.days_back)
        print(f"[OK] FD archief: {len(results)} resultaten", file=sys.stderr)
        for r in results:
            wc = r.get("word_count", 0)
            ft = "✓" if r.get("has_full_text") else "∅"
            print(f"  {ft} {wc}w — {r['title'][:65]}")
        all_items = results

    # Focus-zoekopdrachten
    elif args.focus:
        if not session:
            print("[ERR] Focus-zoekopdrachten vereisen ingelogde sessie", file=sys.stderr)
            sys.exit(1)
        focus_path = Path(args.focus)
        print(f"[FD] Focus-zoekopdrachten uit {focus_path.name}...", file=sys.stderr)
        all_items = fetch_focus_articles(focus_path, session, days_back=args.days_back)
        print(f"[OK] FD archief: {len(all_items)} artikelen", file=sys.stderr)

    # RSS feeds (standaard)
    else:
        sections = (list(FD_SECTION_RSS.keys()) if args.all_sections
                    else args.sections)
        all_items = fetch_fd_rss(
            session=session,
            sections=sections,
            max_age_hours=args.hours,
            full_text=args.full_text,
            max_full_text=args.max_full_text,
        )

    output = json.dumps(all_items, ensure_ascii=False, indent=2)

    if args.output:
        Path(args.output).write_text(output)
        print(f"[OK] {len(all_items)} items → {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
