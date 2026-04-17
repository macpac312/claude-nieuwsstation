#!/usr/bin/env python3
"""
Nieuwsstation Achtergrond API
Genereert on-demand achtergrond-artikelen voor de dagkrant via Claude.

Gebruik:
    python3 ~/nieuwsstation/src/api_server.py
    python3 ~/nieuwsstation/src/api_server.py --port 7432

Endpoints:
    GET  /status            — server alive check
    POST /background        — genereer achtergrond-artikel (JSON body)
    GET  /background/cache  — bekijk cache-inhoud
    POST /save-note         — sla artikel + analyse op als Obsidian .md notitie
    GET  /vault-note        — lees een vault-notitie en geef terug als HTML
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import quote as url_quote

import requests as req
from bs4 import BeautifulSoup

try:
    import anthropic as _anthropic_sdk
    _ANTHROPIC_CLIENT = _anthropic_sdk.Anthropic()
except Exception:
    _ANTHROPIC_CLIENT = None

# ─── Argos Translate (lokaal, offline EN→NL) ───────────────────────────────
def _init_google():
    """Initialiseer Google Translate via deep-translator (geen warmup nodig)."""
    try:
        from deep_translator import GoogleTranslator
        t = GoogleTranslator(source="en", target="nl")
        print("[API] Google Translate gereed (EN→NL, deep-translator)", file=sys.stderr)
        return t
    except Exception as e:
        print(f"[API] Google Translate niet beschikbaar: {e}", file=sys.stderr)
        return None

def _init_argos():
    """Laad Argos EN→NL model bij serverstart — fallback als Google niet bereikbaar is."""
    try:
        from argostranslate import translate as _at
        _at.translate("test", "en", "nl")   # warmup
        print("[API] Argos Translate gereed als fallback (EN→NL)", file=sys.stderr)
        return _at
    except Exception as e:
        print(f"[API] Argos Translate niet beschikbaar: {e}", file=sys.stderr)
        return None

_GOOGLE = _init_google()
_ARGOS  = _init_argos()

# ─── Config ───────────────────────────────────────────────────────────────────

DEFAULT_PORT = 7432
CLAUDE_MODEL = "claude-sonnet-4-6"
BACKGROUND_MODEL = "claude-opus-4-7"
SOURCES_YAML = Path.home() / "nieuwsstation/src/config/sources.yaml"
FOCUS_MD = Path.home() / "nieuwsstation/focus.md"
TRANSLATE_CACHE_FILE = Path.home() / "nieuwsstation/.translate-cache.json"

# In-memory cache: title_key → generated html
CACHE: dict[str, str] = {}

# Kruisverband Q&A context cache: datum_iso → {kruisverband_md, archief, werk, graph}
KV_CONTEXT_CACHE: dict[str, dict] = {}

# Persistente vertaalcache (overleeft server-herstart)
def _load_translate_cache() -> dict[str, str]:
    try:
        if TRANSLATE_CACHE_FILE.exists():
            return json.loads(TRANSLATE_CACHE_FILE.read_text())
    except Exception:
        pass
    return {}

def _save_translate_cache(cache: dict) -> None:
    try:
        TRANSLATE_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False))
    except Exception:
        pass

TRANSLATE_CACHE: dict[str, str] = _load_translate_cache()


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

PAYWALLED = ('ft.com', 'nrc.nl', 'nrc.nl/nieuws', 'telegraaf.nl')

FETCH_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'nl-NL,nl;q=0.9,en;q=0.8',
}


# ─── Background generation ────────────────────────────────────────────────────

VAULT_SEARCH = Path.home() / "nieuwsstation/src/vault_search.py"
VAULT_PATH   = Path.home() / "Documents/WorkMvMOBS"


def _search_vault_archive(query: str, max_snippets: int = 4) -> str:
    """
    Doorzoek het Obsidian-archief (Briefings/*.md) op het onderwerp.
    Retourneert een blok met relevante passages (max ~2000 tekens).
    """
    if not VAULT_SEARCH.exists():
        return ""
    try:
        briefings_path = str(VAULT_PATH / "Briefings")
        result = subprocess.run(
            ["python3", str(VAULT_SEARCH), "--query", query,
             "--top", str(max_snippets), "--min-score", "1.5",
             "--vault", briefings_path],
            capture_output=True, text=True, timeout=8,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""
        data = json.loads(result.stdout)
        notes = data.get("notes", [])
        if not notes:
            return ""
        parts = []
        for note in notes[:max_snippets]:
            title   = note.get("title", "")
            snippet = note.get("excerpt", note.get("content", ""))[:400]
            date    = note.get("date", "")
            src     = f"[Archief: {title}" + (f" — {date}" if date else "") + "]"
            parts.append(f"{src}\n{snippet}")
        block = "\n\n".join(parts)
        print(f"  [API] Archief: {len(notes)} relevante notes gevonden voor '{query[:40]}'",
              file=sys.stderr)
        return block
    except Exception as e:
        print(f"  [API] Archief zoeken mislukt: {e}", file=sys.stderr)
        return ""


def _search_vault_werk(query: str, max_snippets: int = 3) -> str:
    """Doorzoek de werk-vault (Calcasa, IRB, huizenprijzen) — slaat dagkrant-digests over."""
    if not VAULT_SEARCH.exists():
        return ""
    try:
        result = subprocess.run(
            ["python3", str(VAULT_SEARCH), "--query", query,
             "--top", str(max_snippets + 4), "--min-score", "1.0",
             "--vault", str(VAULT_PATH)],
            capture_output=True, text=True, timeout=10,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""
        data = json.loads(result.stdout)
        notes = data.get("notes", [])
        parts = []
        for note in notes:
            title = note.get("title", "")
            if "dagkrant" in title.lower() or re.match(r"^\d{4}-\d{2}-\d{2}", title):
                continue
            snippet = note.get("excerpt", note.get("content", ""))[:350]
            parts.append(f"[Vault: {title}]\n{snippet}")
            if len(parts) >= max_snippets:
                break
        block = "\n\n".join(parts)
        if block:
            print(f"  [API] Werk-vault: {len(parts)} notes voor '{query[:40]}'", file=sys.stderr)
        return block
    except Exception as e:
        print(f"  [API] Werk-vault zoeken mislukt: {e}", file=sys.stderr)
        return ""


def load_focus() -> str:
    """Laad actieve focus-onderwerpen als context."""
    if FOCUS_MD.exists():
        lines = [l.strip() for l in FOCUS_MD.read_text().split("\n")
                 if l.strip().startswith("- ")]
        return ", ".join(l[2:].split(":")[0].strip() for l in lines[:6])
    return ""


def _fetch_source_text(url: str, max_chars: int = 2500) -> str:
    """Haal artikeltekst op van een URL voor achtergrondanalyse."""
    try:
        for pw in PAYWALLED:
            if pw in url:
                return ""
        s = req.Session()
        s.headers.update(FETCH_HEADERS)
        resp = s.get(url, timeout=12, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "footer", "header",
                                   "aside", "form", "iframe", "noscript"]):
            tag.decompose()
        candidates = [
            soup.find("article"),
            soup.find(class_=re.compile(r"article[_-]?(body|content|text)", re.I)),
            soup.find("main"),
        ]
        container = next((c for c in candidates if c), soup.body or soup)
        parts = []
        for el in container.find_all(["h1", "h2", "h3", "p"]):
            t = el.get_text(" ", strip=True)
            if len(t) > 40:
                parts.append(t)
        return " ".join(parts)[:max_chars]
    except Exception:
        return ""


def _search_web_extra(query: str, exclude_domains: set,
                      num: int = 4) -> list[dict]:
    """
    Zoek aanvullende bronnen via DuckDuckGo.
    Returns list van {url, domain, title}.
    """
    from urllib.parse import unquote
    try:
        r = req.get(
            f"https://html.duckduckgo.com/html/?q={url_quote(query)}&kl=nl-nl",
            headers=FETCH_HEADERS, timeout=12
        )
        soup = BeautifulSoup(r.text, "html.parser")
        skip = {"youtube.com", "facebook.com", "twitter.com", "x.com",
                "instagram.com", "reddit.com"} | exclude_domains
        results = []
        for a in soup.select("a.result__a"):
            raw = a.get("href", "")
            m = re.search(r"uddg=([^&]+)", raw)
            url = unquote(m.group(1)) if m else raw
            if not url.startswith("http"):
                continue
            domain = url.split("/")[2].replace("www.", "")
            if any(s in domain for s in skip):
                continue
            results.append({"url": url, "domain": domain,
                            "title": a.get_text(strip=True)})
            if len(results) >= num:
                break
        print(f"  [API] DDG gevonden: {[r['domain'] for r in results]}",
              file=sys.stderr)
        return results
    except Exception as e:
        print(f"  [API] DDG zoeken mislukt: {e}", file=sys.stderr)
        return []


def _search_youtube(query: str) -> tuple[str, str]:
    """
    Zoek een YouTube-video via de zoekpagina.
    Returns (video_id, video_title) or ("", "")
    """
    try:
        r = req.get(
            f"https://www.youtube.com/results?search_query={url_quote(query)}&hl=nl",
            headers=FETCH_HEADERS, timeout=10
        )
        text = r.text
        # Haal unieke video-IDs op (YouTube herhaalt ze; eerste unieke = meest relevant)
        ids = list(dict.fromkeys(re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', text)))
        if not ids:
            return "", ""
        vid = ids[0]
        # Zoek titel in de 600 tekens ná het eerste videoId-voorkomen
        idx = text.find(f'"videoId":"{vid}"')
        titles = re.findall(r'"text":"([^"]{10,120})"', text[idx: idx + 600])
        yt_title = titles[0] if titles else query
        print(f"  [API] YouTube: {vid} — {yt_title[:60]}", file=sys.stderr)
        return vid, yt_title
    except Exception as e:
        print(f"  [API] YouTube zoeken mislukt: {e}", file=sys.stderr)
        return "", ""


def generate_background(title: str, summary: str, sources: list[str],
                        topic: str = "", extra: str = "",
                        related_articles: list[dict] | None = None) -> tuple[str, str | None, int]:
    """
    Genereer een diepgaand achtergrond-artikel via Claude Opus.
    Zoekt aanvullende bronnen via DuckDuckGo, fetcht teksten parallel,
    zoekt YouTube, analyseert met modelkennis.
    Returns (html_content, error_or_None)
    """
    import concurrent.futures

    focus_ctx = load_focus()

    # ── Stap 1: Bestaande bronnen + web-zoeken naar extra bronnen ──────────────
    existing_urls = [u for u in sources if u.startswith("http")]
    existing_domains = {u.split("/")[2].replace("www.", "") for u in existing_urls}

    # Zoek parallel: web-extra + YouTube + vault-archief
    ddg_query = f"{title} analyse achtergrond"
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        f_ddg     = pool.submit(_search_web_extra, ddg_query, existing_domains, 4)
        f_yt      = pool.submit(_search_youtube, f"{title} 2026")
        f_archive = pool.submit(_search_vault_archive, title, 4)
        extra_results = f_ddg.result()
        yt_id, yt_title = f_yt.result()
        archive_block = f_archive.result()

    # Bouw volledige bronnenlijst: bestaande + DDG-aanvulling (max 7 total)
    all_sources = [{"url": u, "domain": u.split("/")[2].replace("www.", ""),
                    "title": ""} for u in existing_urls]
    all_sources += extra_results
    all_sources = all_sources[:7]  # cap

    # ── Stap 2: Bronnen parallel ophalen ──────────────────────────────────────
    def fetch_one(src: dict) -> tuple[str, str, str]:
        """Returns (domain, url, text)"""
        text = _fetch_source_text(src["url"])
        return src["domain"], src["url"], text

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        fetched = list(pool.map(fetch_one, all_sources))

    # Filter lege resultaten
    source_texts = []
    used_sources = []  # [{url, domain}] — voor bronnenlijst onderaan
    for domain, url, text in fetched:
        if text:
            source_texts.append(f"[{domain}]\n{text}")
            used_sources.append({"url": url, "domain": domain})

    print(f"  [API] Bronnen geladen: {[s['domain'] for s in used_sources]}",
          file=sys.stderr)

    sources_block = ("\n\n---\n\n".join(source_texts)
                     if source_texts else "(geen bronnen opgehaald)")

    # Verwante artikelen uit dezelfde dagkrant-editie
    related_block = ""
    if related_articles:
        rel_items = []
        for r in related_articles[:5]:
            rt = r.get("title", "").strip()
            rs = r.get("summary", "").strip()[:200]
            if rt:
                rel_items.append(f'- "{rt}"{(" — " + rs) if rs else ""}')
        if rel_items:
            related_block = (
                "\n\nVERWANTE ARTIKELEN IN DEZELFDE DAGKRANT (combineer deze in je analyse):\n"
                + "\n".join(rel_items)
            )

    # ── Stap 3: Prompt bouwen ──────────────────────────────────────────────────
    archive_section = ""
    if archive_block:
        archive_section = f"\n\nARCHIEF — EERDERE ANALYSES (gebruik voor historische context en trendanalyse):\n{archive_block}"

    prompt = f"""Je bent een diepgravende nieuwsanalist voor De Dagkrant. Schrijf een achtergrond-artikel van 550-700 woorden in het Nederlands.

ONDERWERP: {title}
INITIËLE CONTEXT: {summary}
{f"THEMA: {topic}" if topic else ""}
{f"ACTIEVE FOCUS-VERHALEN: {focus_ctx}" if focus_ctx else ""}
{f"EXTRA: {extra}" if extra else ""}
{related_block}
{archive_section}
BRONMATERIAAL ({len(source_texts)} bronnen opgehaald):
{sources_block}

INSTRUCTIES:
- Gebruik het bronmateriaal ÉN je eigen modelkennis en analytische inzichten
- Als er verwante artikelen zijn: verwerk deze actief in de analyse, leg verbanden en behandel het als één samenhangende analyse
- Als er archief-passages zijn: gebruik deze om te laten zien hoe het onderwerp zich ontwikkeld heeft over tijd ("begin maart was X, nu is Y") — echte longitudinale analyse
- Geef historische context, vergelijkingsmateriaal, internationale vergelijkingen
- Kom tot duidelijke, onderbouwde conclusies over gevolgen en betekenis
- Leg verbanden met andere lopende verhalen (geopolitiek, economie, tech, regelgeving)
- Schrijf voor een intelligent publiek — NRC / Financial Times kwaliteit
- Analytisch, niet sensationeel; geen opsommingen maar lopende tekst
- Gebruik meerdere bronperspektieven; vermeld wanneer bronnen van mening verschillen

VISUALS — voeg 1-2 GEANIMEERDE visuals toe die het artikel verduidelijken.
Kies per onderwerp het meest passende type. Animaties zijn ingebouwd via CSS-klassen.

TYPE 1 — TIJDLIJN met slide-in animatie (bij: conflict-verloop, beleidshistorie, reeks events):
<div class="ns-viz"><div class="ns-viz-title">⏱ Tijdlijn</div>
<div class="ns-viz-timeline">
  <div class="ns-viz-timeline-item"><div class="ns-viz-timeline-date">jul 2022</div><div>Beschrijving (max 12 woorden)</div></div>
  <div class="ns-viz-timeline-item"><div class="ns-viz-timeline-date">mrt 2024</div><div>Volgende mijlpaal</div></div>
  <div class="ns-viz-timeline-item"><div class="ns-viz-timeline-date">apr 2026</div><div>Huidige situatie</div></div>
</div></div>
(Items schuiven automatisch na elkaar in beeld — geen extra code nodig)

TYPE 2 — SVG-FLOWCHART met draw-on pijlen (bij: transmissie, oorzaak-gevolg, beleidsproces):
Voeg class="anim-node" toe aan elke <rect> en class="anim-line" aan elke <line>/<path>:
<div class="ns-viz"><div class="ns-viz-title">⚡ Transmissie-mechanisme</div>
<div class="ns-viz-flow"><svg viewBox="0 0 720 130" xmlns="http://www.w3.org/2000/svg">
  <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#7c3aed"/></marker></defs>
  <rect class="anim-node" x="10" y="35" width="130" height="60" rx="9" fill="#7c3aed" fill-opacity=".13" stroke="#7c3aed" stroke-width="1.8"/>
  <text x="75" y="62" text-anchor="middle" font-size="12" font-weight="700" fill="#7c3aed">ECB</text>
  <text x="75" y="78" text-anchor="middle" font-size="11" fill="#44403c">verlaagt rente</text>
  <line class="anim-line" x1="143" y1="65" x2="173" y2="65" stroke="#7c3aed" stroke-width="2.5" marker-end="url(#arr)"/>
  <rect class="anim-node" x="176" y="35" width="130" height="60" rx="9" fill="#a78bfa" fill-opacity=".13" stroke="#a78bfa" stroke-width="1.8"/>
  <text x="241" y="62" text-anchor="middle" font-size="12" font-weight="700" fill="#7c3aed">Hypotheekrente</text>
  <text x="241" y="78" text-anchor="middle" font-size="11" fill="#44403c">daalt mee</text>
  <line class="anim-line" x1="309" y1="65" x2="339" y2="65" stroke="#7c3aed" stroke-width="2.5" marker-end="url(#arr)"/>
  <rect class="anim-node" x="342" y="35" width="130" height="60" rx="9" fill="#a78bfa" fill-opacity=".13" stroke="#a78bfa" stroke-width="1.8"/>
  <text x="407" y="69" text-anchor="middle" font-size="12" font-weight="700" fill="#7c3aed">Meer kopers</text>
  <!-- Herhaal voor max 5 stappen totaal -->
</svg></div></div>

TYPE 3 — STAT-CARDS met tel-animatie (bij: kerncijfers, percentages, aantallen):
Gebruik data-target voor de cijferwaarde, data-suffix voor symbool, data-prefix voor valuta:
<div class="ns-viz"><div class="ns-viz-title">📊 Kerncijfers</div>
<div class="ns-viz-stats">
  <div class="ns-viz-stat"><div class="ns-viz-stat-value ns-viz-count" data-target="8.2" data-suffix="%">8.2%</div><div class="ns-viz-stat-label">Prijsstijging Q1</div></div>
  <div class="ns-viz-stat"><div class="ns-viz-stat-value ns-viz-count" data-prefix="€" data-target="487000">€487000</div><div class="ns-viz-stat-label">Gem. prijs</div></div>
  <div class="ns-viz-stat"><div class="ns-viz-stat-value ns-viz-count" data-target="42">42</div><div class="ns-viz-stat-label">Duizend verkopen</div></div>
</div></div>
(Getallen tellen automatisch omhoog wanneer ze in beeld komen)

TYPE 4 — CHART.JS interactief (bij: koersontwikkeling, vergelijking regio's/landen/partijen):
Met hover-tooltips en load-animatie ingebouwd. Gebruik id="chart-bg-1":
<div class="ns-viz"><div class="ns-viz-title">📈 Ontwikkeling 2022–2026</div>
<div class="ns-viz-chart"><canvas id="chart-bg-1"></canvas></div>
<script>(function(){{
  if(typeof Chart==='undefined')return;
  new Chart(document.getElementById('chart-bg-1'),{{
    type:'line',
    data:{{
      labels:['2022','2023','2024','2025','2026'],
      datasets:[{{
        label:'Nederland',data:[3.2,5.1,4.8,6.3,8.2],
        borderColor:'#7c3aed',backgroundColor:'rgba(124,58,237,.08)',
        tension:.4,fill:true,pointRadius:5,pointHoverRadius:7,pointBackgroundColor:'#7c3aed'
      }}]
    }},
    options:{{
      animation:{{duration:900,easing:'easeOutQuart'}},
      plugins:{{
        legend:{{display:false}},
        tooltip:{{backgroundColor:'rgba(28,25,23,.9)',titleColor:'#fafaf9',bodyColor:'#d4d0cb',
                  cornerRadius:8,padding:10}}
      }},
      scales:{{
        y:{{grid:{{color:'rgba(148,163,184,.15)'}},ticks:{{color:'#78716c'}}}},
        x:{{grid:{{display:false}},ticks:{{color:'#78716c'}}}}
      }},
      responsive:true,maintainAspectRatio:false
    }}
  }});
}})();</script></div>

TYPE 4B — CHART.JS met annotatie (bij: grafiek met markering van specifiek event):
Voeg toe aan options.plugins:
annotations:{{event1:{{type:'line',xMin:'2024',xMax:'2024',borderColor:'#dc2626',
  borderWidth:1.5,borderDash:[4,3],label:{{content:'ECB-besluit',display:true,
  backgroundColor:'#dc2626',color:'#fff',font:{{size:10}}}}}}}}

REGELS:
- Max 2 visuals per artikel; altijd NA de bullets
- Cijfers ALLEEN uit bronnen of realistische kennis — geen verzonnen data
- SVG: max 5 knooppunten; gebruik #7c3aed primair, #a78bfa secundair
- Chart.js canvas altijd id="chart-bg-1" (wordt automatisch uniek gemaakt)
- Voorkeur per type: geopolitiek/conflict → tijdlijn | beleid/rente/keten → flowchart | vergelijkende cijfers → Chart.js | kerncijfers → stat-cards
- Twijfel? → tijdlijn of stat-cards (robuuster dan Chart.js)

FORMAAT — geef UITSLUITEND de volgende HTML-fragmenten terug, geen uitleg, geen markdown:

<ul class="bg-bullets">
<li>[Kernpunt 1: belangrijkste feit of ontwikkeling, max 15 woorden]</li>
<li>[Kernpunt 2: oorzaak of mechanisme, max 15 woorden]</li>
<li>[Kernpunt 3: gevolg of impact, max 15 woorden]</li>
<li>[Kernpunt 4: conclusie of vooruitzicht, max 15 woorden — alleen als er een scherp vierde punt is]</li>
</ul>
[VISUAL 1 HIER — zie TYPE 1-4 hierboven, kies wat past]
<h5>[Sectietitel: situatie en context]</h5>
<p>[Eerste alinea: wat speelt er, met historische context. 110-140 woorden.]</p>
<h5>[Sectietitel: diepere analyse]</h5>
<p>[Tweede alinea: mechanismen, oorzaken, vergelijkingen. 120-150 woorden.]</p>
<blockquote>[Kernbevinding, opvallend citaat of analytische stelling uit de bronnen]</blockquote>
[VISUAL 2 HIER — optioneel, alleen als tweede type echt waarde toevoegt]
<h5>[Sectietitel: gevolgen en perspectieven]</h5>
<p>[Derde alinea: concrete gevolgen voor Nederland/Europa/de sector. Uiteenlopende perspectieven. 110-140 woorden.]</p>
<h5>Conclusie</h5>
<p>[Scherpe afsluitende analyse. Eigen oordeel. 70-90 woorden. Geen samenvatting maar een standpunt.]</p>"""

    # ── Stap 4a: Hero-foto van primaire bron ──────────────────────────────────
    hero_img_html = ""
    primary_url = existing_urls[0] if existing_urls else ""
    if primary_url:
        try:
            from urllib.request import urlopen, Request as UReq
            import html as html_mod
            req_img = UReq(primary_url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120",
                "Accept": "text/html,application/xhtml+xml",
            })
            with urlopen(req_img, timeout=8) as r:
                chunk = r.read(65536).decode("utf-8", errors="ignore")
            og_patterns = [
                r'property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                r'content=["\']([^"\']+)["\'][^>]*property=["\']og:image',
                r'name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
            ]
            for pat in og_patterns:
                m = re.search(pat, chunk, re.I)
                if m:
                    img_url = html_mod.unescape(m.group(1).strip())
                    if img_url.startswith("http"):
                        safe_img = img_url.replace('"', '&quot;').replace("'", "&#39;")
                        primary_domain = primary_url.split("/")[2].replace("www.", "")
                        hero_img_html = (
                            f'<div style="margin:-1.5rem -2rem 1.5rem;overflow:hidden;'
                            f'max-height:220px;position:relative">'
                            f'<img src="{safe_img}" alt="" loading="lazy"'
                            f' style="width:100%;object-fit:cover;display:block"'
                            f' onerror="this.parentElement.style.display=\'none\'">'
                            f'<div style="position:absolute;bottom:.4rem;right:.6rem;'
                            f'font-size:.55rem;background:rgba(0,0,0,.6);color:#fff;'
                            f'padding:2px 8px;border-radius:3px">© {primary_domain}</div>'
                            f'</div>'
                        )
                        break
        except Exception:
            pass

    # ── Stap 4b: YouTube-kaart HTML ────────────────────────────────────────────
    yt_html = ""
    if yt_id:
        safe_yt = yt_title.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        yt_html = (
            '<div style="margin:1.4rem 0 .8rem;border-radius:8px;overflow:hidden;'
            'background:var(--bg2);border:1px solid var(--border)">'
            f'<a href="https://www.youtube.com/watch?v={yt_id}" target="_blank"'
            ' style="display:flex;align-items:center;gap:.8rem;padding:.7rem;'
            'text-decoration:none;color:inherit">'
            f'<img src="https://img.youtube.com/vi/{yt_id}/mqdefault.jpg"'
            ' style="width:120px;height:68px;object-fit:cover;border-radius:4px;flex-shrink:0"'
            ' onerror="this.parentElement.parentElement.style.display=\'none\'">'
            '<div><div style="font-size:.65rem;color:var(--t3);margin-bottom:.25rem">'
            '&#9654; YouTube</div>'
            f'<div style="font-size:.85rem;font-weight:600;line-height:1.3">{safe_yt}</div>'
            '</div></a></div>'
        )

    # ── Stap 5: Bronnenlijst HTML ──────────────────────────────────────────────
    bronnen_html = ""
    if used_sources:
        links = " &bull; ".join(
            f'<a href="{s["url"]}" target="_blank" style="color:var(--accent)">'
            f'{s["domain"]} ↗</a>'
            for s in used_sources
        )
        bronnen_html = (
            '<div class="bg-footer" style="margin-top:1.5rem;padding-top:.8rem;'
            'border-top:1px solid var(--border)">'
            f'<strong>Bronnen:</strong> {links}'
            '</div>'
        )

    # ── Stap 6: Claude Opus aanroepen ──────────────────────────────────────────
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", BACKGROUND_MODEL,
             "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=180,
            stdin=subprocess.DEVNULL,
            cwd=str(Path.home() / "nieuwsstation"),
        )
        if result.returncode != 0:
            return "", result.stderr or "Claude aanroep mislukt"

        html = result.stdout.strip()
        if html.startswith("```html"):
            html = html[7:]
        if html.startswith("```"):
            html = html[3:]
        if html.endswith("```"):
            html = html[:-3]
        html = html.strip()

        # Unieke canvas-ID's om botsingen tussen meerdere achtergrondartikelen te voorkomen
        import uuid as _uuid
        suffix = _uuid.uuid4().hex[:8]
        def _rewrite_chart_ids(m):
            orig = m.group(1)
            return f'{orig}-{suffix}'
        html = re.sub(r"id=[\"'](chart-[a-zA-Z0-9_-]+)[\"']",
                      lambda m: f'id="{m.group(1)}-{suffix}"', html)
        html = re.sub(r"getElementById\([\"'](chart-[a-zA-Z0-9_-]+)[\"']\)",
                      lambda m: f"getElementById('{m.group(1)}-{suffix}')", html)

        archive_hits = archive_block.count("[Archief:") if archive_block else 0
        return hero_img_html + html + yt_html + bronnen_html, None, archive_hits

    except subprocess.TimeoutExpired:
        return "", "Timeout: Claude reageerde niet binnen 180 seconden", 0
    except Exception as e:
        return "", str(e), 0


# ─── Article fetching ─────────────────────────────────────────────────────────

_FD_SESSION_CACHE: req.Session | None = None
_FD_SESSION_TIME: float = 0

def _fd_session():
    """Maak een geauthenticeerde FD-sessie via Keycloak OIDC login.

    FD gebruikt login.fdmg.nl (Keycloak) als identity provider. De flow is:
      1. GET fd.nl/login  → redirect naar Keycloak login pagina
      2. POST username    → krijg password-formulier terug
      3. POST username + password → redirect terug naar fd.nl met sessie-cookies

    Sessie wordt gecached (max 30 min) om herhaald inloggen te voorkomen.
    """
    global _FD_SESSION_CACHE, _FD_SESSION_TIME

    # Hergebruik bestaande sessie (max 30 minuten)
    if _FD_SESSION_CACHE and (time.time() - _FD_SESSION_TIME) < 1800:
        return _FD_SESSION_CACHE

    env_path = Path.home() / "nieuwsstation/.env"
    email = password = ""
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("FD_EMAIL="):
                email = line.split("=", 1)[1].strip()
            elif line.startswith("FD_PASSWORD="):
                password = line.split("=", 1)[1].strip()
    if not email:
        return None
    try:
        session = req.Session()
        session.headers.update(FETCH_HEADERS)

        # Stap 1: Haal Keycloak login pagina op (fd.nl/login redirectt)
        r1 = session.get("https://fd.nl/login", timeout=15)
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

        # Stap 3: POST username + password → redirect naar fd.nl
        r3 = session.post(action2, data={"username": email, "password": password},
                          timeout=15, allow_redirects=True)

        if "Uitloggen" in r3.text:
            print("[OK] FD login succesvol (Keycloak OIDC)", file=sys.stderr)
        else:
            print("[INFO] FD login status onzeker, doorgaan...", file=sys.stderr)

        _FD_SESSION_CACHE = session
        _FD_SESSION_TIME = time.time()
        return session

    except Exception as e:
        print(f"[WARN] FD login mislukt: {e}", file=sys.stderr)
        return None


def _extract_article_html(html: str, url: str) -> str:
    """Extraheer leesbare artikel-HTML uit een pagina."""
    soup = BeautifulSoup(html, "html.parser")

    # Extraheer og:image / twitter:image vóór we tags verwijderen
    hero_img = ""
    for selector in [
        {"property": "og:image"},
        {"name": "twitter:image"},
        {"name": "twitter:image:src"},
    ]:
        tag = soup.find("meta", attrs=selector)
        if tag:
            hero_img = tag.get("content", "").strip()
            if hero_img:
                break

    # Verwijder ruis
    for tag in soup.find_all(["script", "style", "nav", "footer", "header",
                               "aside", "form", "iframe", "noscript",
                               "figure", "img", "svg"]):
        tag.decompose()

    # Probeer article-containers in volgorde van specificiteit
    candidates = [
        soup.find("article"),
        soup.find(class_=re.compile(r"article[_-]?(body|content|text|detail)", re.I)),
        soup.find(class_=re.compile(r"(body|content)[_-]?text", re.I)),
        soup.find("main"),
    ]
    container = next((c for c in candidates if c), soup.body or soup)

    # Bouw schone HTML op
    parts = []
    for el in container.find_all(["h1", "h2", "h3", "h4", "h5", "p", "blockquote", "li"]):
        text = el.get_text(" ", strip=True)
        if len(text) < 30:
            continue
        tag = el.name
        if tag in ("h1", "h2", "h3"):
            parts.append(f"<h5>{text}</h5>")
        elif tag == "blockquote":
            parts.append(f"<blockquote>{text}</blockquote>")
        elif tag == "li":
            parts.append(f"<p>• {text}</p>")
        else:
            parts.append(f"<p>{text}</p>")
        if len(parts) > 40:  # max ~40 paragrafen
            break

    if not parts:
        return "<p><em>Kon geen artikeltekst extraheren van deze pagina.</em></p>"

    content = "\n".join(parts)
    if hero_img:
        img_tag = (
            f'<img src="{hero_img}" '
            f'style="width:100%;max-height:220px;object-fit:cover;'
            f'border-radius:6px;margin-bottom:1.2rem;display:block" '
            f'loading="lazy" onerror="this.style.display=\'none\'">'
        )
        return img_tag + "\n" + content
    return content


def fetch_article(url: str) -> tuple[str, str | None]:
    """
    Haal artikel op van URL.
    Returns (html_content, error_or_None)
    """
    # Paywall check
    for pw in PAYWALLED:
        if pw in url:
            return (
                f'<p>Dit artikel staat achter een betaalmuur ({pw}).</p>'
                f'<p><a href="{url}" target="_blank" '
                f'style="color:var(--accent)">Open in browser ↗</a></p>',
                None
            )

    session = None
    if "fd.nl" in url:
        session = _fd_session()

    try:
        fetcher = session or req.Session()
        if not session:
            fetcher.headers.update(FETCH_HEADERS)
        time.sleep(0.3)
        resp = fetcher.get(url, timeout=15, allow_redirects=True)
        resp.raise_for_status()

        content = _extract_article_html(resp.text, url)
        source_domain = url.split("/")[2].replace("www.", "")
        footer = (f'<div class="bg-footer">Bron: '
                  f'<a href="{url}" target="_blank" '
                  f'style="color:var(--accent)">{source_domain} ↗</a></div>')
        return content + footer, None

    except req.exceptions.HTTPError as e:
        return "", f"HTTP {e.response.status_code}: {url}"
    except Exception as e:
        return "", str(e)


# ─── Vault markdown renderer ─────────────────────────���───────────────────────

def _render_vault_markdown(text: str) -> str:
    """
    Zet Obsidian-markdown om naar HTML voor weergave in het side-panel.
    Verwerkt front matter, koppen, lijsten, bold/italic, wikilinks, codeblokken.
    """
    import html as html_mod

    # Verwijder YAML front matter
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:].lstrip("\n")

    parts = []
    lines = text.split("\n")
    i = 0
    in_code = False
    code_lines: list[str] = []

    def inline(s: str) -> str:
        s = html_mod.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*(.+?)\*",     r"<em>\1</em>", s)
        s = re.sub(r"`(.+?)`",        r"<code>\1</code>", s)
        # Wikilinks [[Note]] → klikbare link
        s = re.sub(
            r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]",
            lambda m: (
                f'<a href="#" class="vault-link" style="font-size:.85em" '
                f'onclick="openVaultNote(\'{m.group(1).replace(chr(39), "")}\','
                f'\'{m.group(1).replace(chr(39), "")}.md\',event)">'
                f'{m.group(2) or m.group(1)}</a>'
            ),
            s,
        )
        # Externe links [text](url)
        s = re.sub(r'\[([^\]]+?)\]\((https?://[^\)]+?)\)',
                   r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
        return s

    while i < len(lines):
        line = lines[i]

        # Code fence
        if line.startswith("```"):
            if not in_code:
                in_code = True
                lang = html_mod.escape(line[3:].strip())
                code_lines = []
            else:
                in_code = False
                code_body = html_mod.escape("\n".join(code_lines))
                parts.append(f'<pre class="vault-code"><code>{code_body}</code></pre>')
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue

        # Koppen
        if line.startswith("### "):
            parts.append(f"<h5>{inline(line[4:])}</h5>")
        elif line.startswith("## "):
            parts.append(f"<h4>{inline(line[3:])}</h4>")
        elif line.startswith("# "):
            parts.append(f'<h3 style="font-family:\'Playfair Display\',serif;margin-bottom:.3rem">{inline(line[2:])}</h3>')
        # Lijstitems
        elif re.match(r"^[-*] ", line):
            # Verzamel aaneengesloten lijst
            ul_items = []
            while i < len(lines) and re.match(r"^[-*] ", lines[i]):
                ul_items.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            parts.append("<ul>" + "".join(ul_items) + "</ul>")
            continue
        # Genummerde lijst
        elif re.match(r"^\d+\. ", line):
            ol_items = []
            while i < len(lines) and re.match(r"^\d+\. ", lines[i]):
                ol_items.append(f"<li>{inline(re.sub(r'^\d+\. ', '', lines[i]))}</li>")
                i += 1
            parts.append("<ol>" + "".join(ol_items) + "</ol>")
            continue
        # Horizontale lijn
        elif re.match(r"^---+$", line.strip()):
            parts.append("<hr>")
        # Blockquote
        elif line.startswith("> "):
            parts.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        # Lege regel → paragraph break
        elif line.strip() == "":
            parts.append("")
        # Gewone tekst
        else:
            parts.append(f"<p>{inline(line)}</p>")

        i += 1

    raw_html = "\n".join(parts)
    # Meerdere lege regels samenvoegen
    raw_html = re.sub(r"(\n\s*){3,}", "\n\n", raw_html)
    return raw_html


# ─── HTTP Server ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        print(f"  [API] {self.address_string()} - {format % args}", file=sys.stderr)

    def send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # CORS — Obsidian mag aanroepen
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # Pre-flight CORS
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path == "/status":
            self.send_json(200, {
                "status": "ok",
                "model": CLAUDE_MODEL,
                "background_model": BACKGROUND_MODEL,
                "cached": len(CACHE),
            })
        elif self.path == "/background/cache":
            self.send_json(200, {"cache": list(CACHE.keys())})
        elif self.path.startswith("/vault-note"):
            from urllib.parse import urlparse, parse_qs, unquote
            qs        = parse_qs(urlparse(self.path).query)
            file_path = unquote(qs.get("path", [""])[0]).strip()
            if not file_path:
                self.send_json(400, {"error": "Parameter 'path' is verplicht"})
                return
            vault_root = Path.home() / "Documents/WorkMvMOBS"
            # Beveiligingscheck: pad moet binnen de vault blijven
            note_path = (vault_root / file_path).resolve()
            if not str(note_path).startswith(str(vault_root.resolve())):
                self.send_json(403, {"error": "Pad buiten vault niet toegestaan"})
                return
            if not note_path.exists():
                # Probeer met .md extensie als die er nog niet op zit
                note_path = note_path.with_suffix(".md")
            if not note_path.exists():
                self.send_json(404, {"error": f"Notitie niet gevonden: {file_path}"})
                return
            try:
                raw = note_path.read_text(encoding="utf-8")
                html = _render_vault_markdown(raw)
                title = note_path.stem
                self.send_json(200, {"html": html, "title": title, "path": file_path})
            except Exception as e:
                self.send_json(500, {"error": str(e)})
            return
        elif self.path.startswith("/podcast-focus"):
            # Lees podcast .md voor opgegeven datum (of meest recent) en extraheer focus-suggestie
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            req_date = (qs.get("date", [""])[0]).strip()
            podcast_dir = Path.home() / "Documents/WorkMvMOBS/Briefings/podcast"
            if req_date:
                specific = podcast_dir / f"{req_date}.md"
                files = [specific] if specific.exists() else []
            else:
                files = sorted(podcast_dir.glob("*.md"), reverse=True) if podcast_dir.exists() else []
            if not files:
                self.send_json(200, {"focus": ""})
                return
            try:
                text = files[0].read_text(encoding="utf-8")
                # Extraheer alleen ## niveau koppen (niet de hoofdtitel of generieke woorden)
                skip_exact = {"overzicht", "samenvatting", "inleiding", "conclusie",
                              "synthese", "bronnen", "context", "achtergrond"}
                headings = []
                for l in text.split("\n"):
                    if l.startswith("## "):
                        h = l[3:].strip()
                        # Strip "Blok N: " prefix zodat het echte onderwerp overblijft
                        h = re.sub(r"^Blok\s+\d+:\s*", "", h, flags=re.I).strip()
                        # Filter generieke koppen
                        if len(h) > 8 and h.lower() not in skip_exact:
                            headings.append(h)
                    if len(headings) >= 3:
                        break

                if headings:
                    topics = ", ".join(headings[:3])
                    focus = (f"Bespreek de volgende thema's en hun onderlinge verbanden: {topics}. "
                             f"Wat is de rode draad en wat betekent dit voor Nederlandse burgers en professionals?")
                else:
                    focus = ("Bespreek de belangrijkste nieuwsthema's van vandaag en hun onderlinge verbanden. "
                             "Wat is de rode draad?")
                self.send_json(200, {"focus": focus})
            except Exception as e:
                self.send_json(200, {"focus": ""})
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path not in ("/background", "/article", "/translate",
                             "/notebooklm", "/generate-podcast", "/save-note",
                             "/kruisverband-visual", "/kruisverband-chat",
                             "/vault-digest"):
            self.send_json(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            self.send_json(400, {"error": "Ongeldige JSON"})
            return

        title   = body.get("title", "").strip()
        summary = body.get("summary", "").strip()
        sources = body.get("sources", [])
        topic   = body.get("topic", "").strip()
        extra   = body.get("extra", "").strip()

        # ── /article ──────────────────────────────────────────────────────
        if self.path == "/article":
            url   = body.get("url", "").strip()
            atitle = body.get("title", "").strip()
            if not url:
                self.send_json(400, {"error": "Veld 'url' is verplicht"})
                return
            cache_key = url.lower()
            if cache_key in CACHE:
                self.send_json(200, {"html": CACHE[cache_key], "cached": True})
                return
            print(f"  [API] Artikel ophalen: {url[:70]}…", file=sys.stderr)
            html, error = fetch_article(url)
            if error:
                self.send_json(500, {"error": error, "success": False})
                return
            full = (f"<h4>{atitle}</h4>" if atitle else "") + html
            CACHE[cache_key] = full
            self.send_json(200, {"html": full, "success": True})
            return

        # ── /translate ────────────────────────────────────────────────────
        if self.path == "/translate":
            src_html = body.get("html", "").strip()
            if not src_html:
                self.send_json(400, {"error": "Veld 'html' is verplicht"})
                return

            # 1. Persistente cache (overleeft herstart)
            cache_key = "t:" + hashlib.md5(src_html.encode()).hexdigest()[:16]
            if cache_key in TRANSLATE_CACHE:
                print(f"  [API] Vertaling: cache hit", file=sys.stderr)
                self.send_json(200, {"html": TRANSLATE_CACHE[cache_key], "cached": True})
                return

            # 2. Taaldetectie — al Nederlands?
            text_sample = re.sub(r"<[^>]+>", " ", src_html[:800])
            nl_words = len(re.findall(
                r'\b(de|het|een|van|in|op|is|zijn|heeft|niet|met|voor|ook|maar|'
                r'als|er|al|aan|om|bij|dat|dit|die|ze|hij|we|ik|je)\b',
                text_sample, re.I))
            if nl_words >= 12:
                self.send_json(200, {"html": src_html, "already_dutch": True})
                return

            # 3. Extraheer alleen tekst-nodes — stuur compacte payload naar Haiku
            #    We vervangen tekst-content met placeholders, vertalen, injecteren terug
            soup_t = BeautifulSoup(src_html, "html.parser")
            # Verwijder zware elementen die niet vertaald hoeven
            for tag in soup_t.find_all(["img", "figure", "svg", "script", "style",
                                         "iframe", "video", "audio", "noscript"]):
                tag.decompose()
            # Verzamel unieke tekst-segmenten
            segments: list[str] = []
            seg_map: dict[str, int] = {}
            for el in soup_t.find_all(string=True):
                txt = el.strip()
                if len(txt) < 4 or txt.isdigit():
                    continue
                if txt not in seg_map:
                    seg_map[txt] = len(segments)
                    segments.append(txt)

            if not segments:
                self.send_json(200, {"html": src_html, "already_dutch": True})
                return

            print(f"  [API] Vertalen: {len(segments)} segmenten…", file=sys.stderr)

            def _inject_translations(src: str, trans_map: dict[str, str]) -> str:
                soup_r = BeautifulSoup(src, "html.parser")
                for el in soup_r.find_all(string=True):
                    txt = el.strip()
                    if txt in trans_map:
                        el.replace_with(el.replace(txt, trans_map[txt]))
                return str(soup_r)

            try:
                # Primair: Google Translate — één batch-aanroep voor alle segmenten
                if _GOOGLE is None:
                    raise RuntimeError("Google Translate niet beschikbaar")
                t0 = time.time()
                results = _GOOGLE.translate_batch(segments)
                elapsed = time.time() - t0
                translations = {seg: res for seg, res in zip(segments, results) if res}
                print(f"  [API] Google Translate klaar in {elapsed:.1f}s", file=sys.stderr)
                translated = _inject_translations(src_html, translations)

            except Exception as google_err:
                print(f"  [API] Google mislukt ({google_err}), fallback Argos…", file=sys.stderr)
                try:
                    if _ARGOS is None:
                        raise RuntimeError("Argos Translate niet beschikbaar")
                    t0 = time.time()
                    translations = {seg: _ARGOS.translate(seg, "en", "nl") for seg in segments}
                    elapsed = time.time() - t0
                    print(f"  [API] Argos vertaling klaar in {elapsed:.1f}s", file=sys.stderr)
                    translated = _inject_translations(src_html, translations)
                except Exception as argos_err:
                    print(f"  [API] Argos mislukt ({argos_err}), fallback Haiku…",
                          file=sys.stderr)
                    if _ANTHROPIC_CLIENT is None:
                        self.send_json(500, {"error": "Vertaling niet beschikbaar (Google + Argos + Haiku alle drie niet beschikbaar)"})
                        return
                    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(segments))
                    msg = _ANTHROPIC_CLIENT.messages.create(
                        model="claude-haiku-4-5-20251001",
                        max_tokens=4096,
                        system=(
                            "Vertaal elke genummerde zin naar vloeiend Nederlands. "
                            "Geef ALLEEN de vertaalde zinnen terug in hetzelfde genummerde formaat. "
                            "Geen uitleg, geen andere tekst."
                        ),
                        messages=[{"role": "user", "content": numbered}],
                    )
                    raw = msg.content[0].text.strip()
                    translations = {}
                    for line in raw.splitlines():
                        m_haiku = re.match(r'^(\d+)\.\s*(.*)', line.strip())
                        if m_haiku:
                            idx = int(m_haiku.group(1)) - 1
                            if 0 <= idx < len(segments):
                                translations[segments[idx]] = m_haiku.group(2).strip()
                    translated = _inject_translations(src_html, translations)

            TRANSLATE_CACHE[cache_key] = translated.strip()
            _save_translate_cache(TRANSLATE_CACHE)
            self.send_json(200, {"html": TRANSLATE_CACHE[cache_key], "cached": False})
            return

        # ── /generate-podcast ─────────────────────────────────────────────
        if self.path == "/generate-podcast":
            from datetime import date as _date
            podcast_dir = Path.home() / "Documents/WorkMvMOBS/Briefings/podcast"
            podcast_dir.mkdir(parents=True, exist_ok=True)
            today = _date.today().isoformat()
            out_file = podcast_dir / f"{today}.md"

            if out_file.exists():
                self.send_json(200, {"file": str(out_file), "already_exists": True})
                return

            # Laad fetched data als context
            data_file = Path("/tmp/dagkrant-ready.json")
            context = ""
            if data_file.exists():
                try:
                    raw = json.loads(data_file.read_text())
                    items = []
                    for topic_data in raw.get("topics", {}).values():
                        for art in topic_data.get("items", topic_data.get("articles", []))[:3]:
                            t = art.get("title", "")
                            s = art.get("summary", "")[:200]
                            if t:
                                items.append(f"- {t}: {s}")
                    context = "\n".join(items[:30])
                except Exception:
                    pass

            prompt = f"""Schrijf een podcast paper van 2000-2500 woorden in lopend Nederlands.
Dit is input voor NotebookLM Audio Overview — twee hosts bespreken het nieuws van vandaag ({today}).

Vereis:
- Geen wikilinks, geen markdown opmaak behalve # voor koppen
- Verdeel in 3-4 blokken met een duidelijke kop per blok
- Elk blok: context, analyse, verbanden tussen onderwerpen
- Eindig met een synthese: wat is de rode draad van vandaag?
- Schrijf voor een intelligent publiek dat niet in de nieuwsbranche werkt

Nieuws van vandaag:
{context if context else "(gebruik je algemene kennis over actuele gebeurtenissen)"}

Sla op als plain tekst, geen code blocks."""

            print(f"  [API] Podcast script genereren voor {today}…", file=sys.stderr)
            result = subprocess.run(
                ["claude", "-p", prompt, "--model", CLAUDE_MODEL],
                capture_output=True, text=True, timeout=600,
                cwd=str(Path.home() / "nieuwsstation"),
            )
            if result.returncode != 0:
                self.send_json(500, {"error": result.stderr or "Claude aanroep mislukt"})
                return

            content = result.stdout.strip()
            # Strip eventuele markdown code fences
            if content.startswith("```"):
                content = "\n".join(content.split("\n")[1:])
            if content.endswith("```"):
                content = "\n".join(content.split("\n")[:-1])

            out_file.write_text(content.strip(), encoding="utf-8")
            print(f"  [API] Podcast script opgeslagen: {out_file}", file=sys.stderr)
            self.send_json(200, {"file": str(out_file), "already_exists": False})
            return

        # ── /notebooklm ───────────────────────────────────────────────────
        if self.path == "/notebooklm":
            podcast_dir = Path.home() / "Documents/WorkMvMOBS/Briefings/podcast"
            req_date = body.get("date", "").strip()

            # Zoek het juiste bestand
            if req_date:
                file_path = podcast_dir / f"{req_date}.md"
            else:
                # Meest recente .md
                files = sorted(podcast_dir.glob("*.md"), reverse=True) if podcast_dir.exists() else []
                file_path = files[0] if files else None

            if not file_path or not file_path.exists():
                self.send_json(404, {"error": f"Geen podcast paper gevonden in {podcast_dir}"})
                return

            # Cache op bestandsdatum zodat dubbel klikken geen tweede notebook aanmaakt
            cache_key = f"notebooklm:{file_path.stem}"
            if cache_key in CACHE:
                cached = json.loads(CACHE[cache_key])
                self.send_json(200, {**cached, "cached": True})
                return

            focus = body.get("focus", "").strip()
            print(f"  [API] NotebookLM upload: {file_path.name}", file=sys.stderr)

            uploader = Path(__file__).parent / "notebooklm_uploader.py"
            cmd = [sys.executable, str(uploader), "--file", str(file_path)]
            if focus:
                cmd += ["--focus", focus]
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode != 0:
                err = result.stdout.strip() or result.stderr.strip()
                try:
                    err_data = json.loads(err)
                    error_msg = err_data.get("error", err)
                except Exception:
                    error_msg = err or "Uploader mislukt"
                self.send_json(500, {"error": error_msg, "success": False})
                return

            try:
                data = json.loads(result.stdout.strip())
            except Exception:
                self.send_json(500, {"error": "Ongeldige output van uploader", "success": False})
                return

            if "error" in data:
                self.send_json(500, {**data, "success": False})
                return

            CACHE[cache_key] = json.dumps(data)
            self.send_json(200, {**data, "success": True, "cached": False})
            return

        # ── /save-note ────────────────────────────────────────────────────
        if self.path == "/save-note":
            note_title  = body.get("title", "").strip()
            note_url    = body.get("url", "").strip()
            note_topic  = body.get("topic", "").strip()
            note_source = body.get("source", "").strip()
            note_teaser = body.get("teaser", "").strip()
            bg_html     = body.get("bg_html", "").strip()

            if not note_title:
                self.send_json(400, {"error": "Veld 'title' is verplicht"})
                return

            # HTML → plain tekst voor achtergrondanalyse
            bg_text = ""
            if bg_html:
                try:
                    soup = BeautifulSoup(bg_html, "html.parser")
                    # Verwijder byline
                    for el in soup.select(".bg-byline"):
                        el.decompose()
                    bg_text = soup.get_text("\n", strip=True)
                    # Haal eerste h4 (titel) weg — staat al in front matter
                    lines = bg_text.split("\n")
                    if lines and lines[0].strip() == note_title.strip():
                        lines = lines[1:]
                    bg_text = "\n".join(l for l in lines if l.strip()).strip()
                except Exception:
                    bg_text = ""

            # Bestandsnaam: datum + slug van titel
            from datetime import datetime
            datum_iso = datetime.now().strftime("%Y-%m-%d")
            slug = re.sub(r"[^a-z0-9]+", "-", note_title.lower())[:50].strip("-")
            topic_labels = {
                "regulatoir": "regulatoir", "huizenmarkt": "huizenmarkt",
                "financieel": "financieel", "nederland": "nederland",
                "wereld": "wereld", "sport": "sport", "aitech": "ai-tech",
                "voetbal": "voetbal",
            }
            topic_tag = topic_labels.get(note_topic, note_topic or "dagkrant")

            knipsels_dir = Path.home() / "Documents/WorkMvMOBS/Briefings/knipsels"
            knipsels_dir.mkdir(parents=True, exist_ok=True)
            note_path = knipsels_dir / f"{datum_iso}-{slug}.md"

            # Markdown opbouwen
            lines_md = [
                "---",
                f"date: {datum_iso}",
                f"source: {note_source}",
                f"url: {note_url}",
                f"topic: {topic_tag}",
                f"tags: [dagkrant, knipsel, {topic_tag}]",
                "---",
                "",
                f"# {note_title}",
                "",
            ]
            if note_teaser:
                lines_md += [f"> {note_teaser}", ""]
            if note_url:
                lines_md += [f"[Lees artikel op {note_source or 'bron'}]({note_url})", ""]
            if bg_text:
                lines_md += ["## Achtergrondanalyse", "", bg_text, ""]

            note_path.write_text("\n".join(lines_md), encoding="utf-8")
            obsidian_path = f"Briefings/knipsels/{note_path.name}"
            print(f"  [API] Notitie opgeslagen: {note_path.name}", file=sys.stderr)
            self.send_json(200, {
                "success": True,
                "note_path": obsidian_path,
                "wikilink": f"[[{note_path.stem}]]",
            })
            return

        # ── /vault-digest ─────────────────────────────────────────────────
        if self.path == "/vault-digest":
            digest_name = (body.get("digest") or "").strip()
            if not digest_name:
                self.send_json(400, {"error": "Veld 'digest' is verplicht"})
                return
            if not digest_name.endswith(".md"):
                digest_name += ".md"
            digest_file = VAULT_PATH / "Briefings" / digest_name
            if not digest_file.exists():
                self.send_json(404, {"error": f"Digest niet gevonden: {digest_name}"})
                return
            try:
                content = digest_file.read_text(encoding="utf-8")
                datum = digest_name[:10]
                # Strip YAML frontmatter
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end > 0:
                        content = content[end + 3:].strip()
                # Eenvoudige markdown → HTML conversie voor digest
                lines = content.split("\n")
                html_lines = []
                in_list = False
                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        if in_list:
                            html_lines.append("</ul>"); in_list = False
                        html_lines.append("")
                        continue
                    if stripped.startswith("## "):
                        if in_list: html_lines.append("</ul>"); in_list = False
                        html_lines.append(f'<h5>{stripped[3:]}</h5>')
                    elif stripped.startswith("### "):
                        if in_list: html_lines.append("</ul>"); in_list = False
                        html_lines.append(f'<h5 style="font-size:.9rem">{stripped[4:]}</h5>')
                    elif stripped.startswith("# "):
                        if in_list: html_lines.append("</ul>"); in_list = False
                        html_lines.append(f'<h4>{stripped[2:]}</h4>')
                    elif stripped.startswith("- ") or stripped.startswith("* "):
                        if not in_list:
                            html_lines.append("<ul>"); in_list = True
                        html_lines.append(f'<li>{stripped[2:]}</li>')
                    elif stripped.startswith("**") and stripped.endswith("**"):
                        if in_list: html_lines.append("</ul>"); in_list = False
                        html_lines.append(f'<p><strong>{stripped[2:-2]}</strong></p>')
                    else:
                        if in_list: html_lines.append("</ul>"); in_list = False
                        html_lines.append(f'<p>{stripped}</p>')
                if in_list:
                    html_lines.append("</ul>")
                digest_html = (
                    f'<div class="bg-byline">Dagkrant archief — {datum}</div>'
                    + "\n".join(html_lines)
                )
                self.send_json(200, {"html": digest_html, "datum": datum})
                return
            except Exception as e:
                self.send_json(500, {"error": str(e)[:200]})
                return

        # ── /kruisverband-visual ──────────────────────────────────────────
        if self.path == "/kruisverband-visual":
            import uuid as _uuid2
            import json as _json2
            import concurrent.futures as _cf

            kv_md = (body.get("kruisverband_md") or "").strip()
            topnieuws = body.get("topnieuws") or []
            datum_iso = (body.get("datum_iso") or "").strip()

            if not kv_md:
                self.send_json(400, {"error": "Veld 'kruisverband_md' is verplicht"})
                return

            cache_key = f"kruisverband_visual:{datum_iso or kv_md[:40]}"
            if cache_key in CACHE:
                self.send_json(200, {"visual_html": CACHE[cache_key], "cached": True})
                return

            uid = _uuid2.uuid4().hex[:8]

            # ── Vault searches parallel ───────────────────────────────────
            top_themas = " ".join(str(t.get("titel", ""))[:40] for t in topnieuws[:3])
            archief_query = kv_md[:200] + " " + top_themas

            def _get_archief():
                return _search_vault_archive(archief_query, max_snippets=5)
            def _get_werk():
                return _search_vault_werk(
                    "IRB AVM Rabobank hypotheek rente model Basel credit risk validatie",
                    max_snippets=3)

            with _cf.ThreadPoolExecutor(max_workers=2) as pool:
                f_arch = pool.submit(_get_archief)
                f_werk = pool.submit(_get_werk)
                archief_block = f_arch.result()
                werk_block = f_werk.result()

            # ── Topnieuws voor prompt ─────────────────────────────────────
            top_lines = []
            for t in topnieuws[:8]:
                titel = str(t.get("titel", ""))[:90]
                sectie = str(t.get("sectie", ""))[:20]
                if titel:
                    top_lines.append(f"- [{sectie}] {titel}")
            top_block = "\n".join(top_lines) if top_lines else "(geen top-artikelen)"

            archief_section = (f"\n\nARCHIEF — EERDERE DAGKRANTEN (gebruik voor historische context):\n{archief_block}"
                               if archief_block else "")
            werk_section = (f"\n\nVAULT — WERK-CONTEXT (Rabobank/IRB/AVM notities):\n{werk_block}"
                            if werk_block else "")

            kv_prompt = f"""Je maakt een uitgebreide kruisverband-analyse voor Marc van Marrewijk.
Marc werkt als model validator bij Rabobank Utrecht (IRB/credit risk: CRR3, EBA, ECB EGIM, PD/LGD/CCF, Calcasa AVM).
Interesses: AI/Claude, Formule 1 (Verstappen), schaken, huizenmarkt Nederland.

KRUISVERBAND-ANALYSE VAN VANDAAG ({datum_iso}):
{kv_md[:3000]}

TOP-ARTIKELEN:
{top_block}
{archief_section}
{werk_section}

Geef UITSLUITEND dit JSON-object (geen uitleg, geen markdown):

{{"rode_draad":"2-3 zinnen die de verbindende lijn van vandaag samenvatten","persoonlijke_duiding":"1-2 zinnen specifiek voor Marc: wat betekent dit voor zijn werk bij Rabobank of IRB-validatie","nodes":[{{"id":"lowercase-geen-spaties","label":"Max 3 woorden","group":"nederland|wereld|financieel|regulatoir|huizenmarkt|sport|aitech","desc":"Max 25 woorden wat dit thema vandaag betekent","weight":3,"relevance":["rabobank|irb|avm|ai|persoonlijk"],"articles":["sectie-scroll-id"],"history":["YYYY-MM-DD: korte eerdere verschijning uit archief"]}}],"links":[{{"source":"node-id","target":"node-id","label":"Max 3 woorden","strength":3,"directed":true,"history":"optioneel: hoe lang dit verband zichtbaar is"}}],"timeline":[{{"datum":"YYYY-MM-DD","thema_id":"node-id","event":"Korte beschrijving","digest":"YYYY-MM-DD-dagkrant"}}]}}

REGELS:
- 5-8 nodes, 5-10 links — alleen echte verbanden van vandaag
- weight 1-5: belang van dit thema vandaag (5=dominant)
- strength 1-5: kracht van het verband (5=directe causaliteit, 1=zwakke correlatie)
- relevance: lege array [] als niet relevant voor werk of interesses
- articles: gebruik de sectie-ID als scroll-target (bijv. "nederland", "financieel", "aitech", "regulatoir", "huizenmarkt")
- history/timeline: vul in vanuit het archief — lege array als geen historische data beschikbaar
- timeline digests: gebruik formaat "YYYY-MM-DD-dagkrant" als de datum bekend is uit het archief"""

            try:
                t0 = time.time()
                print(f"  [API] Kruisverband analyse (archief:{bool(archief_block)}, werk:{bool(werk_block)})…",
                      file=sys.stderr)
                result = subprocess.run(
                    ["claude", "-p", kv_prompt, "--model", BACKGROUND_MODEL,
                     "--dangerously-skip-permissions"],
                    capture_output=True, text=True, timeout=150,
                    stdin=subprocess.DEVNULL,
                    cwd=str(Path.home() / "nieuwsstation"),
                )
                elapsed = time.time() - t0
                print(f"  [API] Kruisverband klaar in {elapsed:.0f}s", file=sys.stderr)

                if result.returncode != 0:
                    self.send_json(500, {"error": result.stderr[:300] or "Claude mislukt"})
                    return

                raw = result.stdout.strip()
                for fence in ("```json", "```"):
                    if raw.startswith(fence): raw = raw[len(fence):]
                if raw.endswith("```"): raw = raw[:-3]
                raw = raw.strip()

                m = re.search(r'\{[\s\S]+\}', raw)
                if not m:
                    self.send_json(500, {"error": "Geen JSON in response"})
                    return

                graph = _json2.loads(m.group(0))

                # Sla context op voor Q&A
                KV_CONTEXT_CACHE[datum_iso or "latest"] = {
                    "kruisverband_md": kv_md,
                    "archief": archief_block,
                    "werk": werk_block,
                    "graph": graph,
                    "datum_iso": datum_iso,
                }

                nodes_json  = _json2.dumps(graph.get("nodes", []),    ensure_ascii=False)
                links_json  = _json2.dumps(graph.get("links", []),    ensure_ascii=False)
                tl_json     = _json2.dumps(graph.get("timeline", []), ensure_ascii=False)
                rode_draad  = _json2.dumps(graph.get("rode_draad", ""),           ensure_ascii=False)
                pers_duiding = _json2.dumps(graph.get("persoonlijke_duiding", ""), ensure_ascii=False)

                # Relevantie-badges
                all_rel: set = set()
                for n in graph.get("nodes", []):
                    for r in (n.get("relevance") or []):
                        all_rel.add(r)
                badges = ""
                if all_rel & {"rabobank", "irb", "avm"}:
                    badges += '<span class="kv-badge kv-badge-werk">💼 Rabobank-relevant</span>'
                if "ai" in all_rel:
                    badges += '<span class="kv-badge kv-badge-ai">🤖 AI-relevant</span>'
                if "persoonlijk" in all_rel:
                    badges += '<span class="kv-badge kv-badge-pers">⭐ Persoonlijk</span>'

                visual = f"""<style>
.kv-container{{font-family:inherit;margin:.3rem 0}}
.kv-rode-draad{{display:flex;gap:.8rem;align-items:flex-start;background:var(--card,#1e1e2e);border-radius:10px;padding:.75rem 1rem;margin-bottom:.65rem;border-left:4px solid #ef4444}}
.kv-rd-label{{font-size:.68rem;font-weight:700;color:#ef4444;text-transform:uppercase;letter-spacing:.05em;display:block;margin-bottom:.2rem}}
.kv-rd-text{{margin:0;font-size:.86rem;color:var(--t1,#e2e8f0);line-height:1.5}}
.kv-duiding{{background:var(--card,#1e1e2e);border-radius:10px;padding:.65rem 1rem;margin-bottom:.65rem;border-left:4px solid #f59e0b}}
.kv-duiding-badges{{display:flex;gap:.35rem;flex-wrap:wrap;margin-bottom:.35rem}}
.kv-badge{{font-size:.68rem;padding:2px 8px;border-radius:12px;font-weight:600}}
.kv-badge-werk{{background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b55}}
.kv-badge-ai{{background:#a855f722;color:#a855f7;border:1px solid #a855f755}}
.kv-badge-pers{{background:#06b6d422;color:#06b6d4;border:1px solid #06b6d455}}
.kv-duiding-text{{margin:0;font-size:.83rem;color:var(--t2,#94a3b8);line-height:1.5}}
.kv-filters{{display:flex;gap:.35rem;flex-wrap:wrap;margin-bottom:.5rem}}
.kv-filter{{font-size:.7rem;padding:3px 10px;border-radius:20px;border:1px solid var(--border,#334155);background:transparent;color:var(--t2,#94a3b8);cursor:pointer;transition:all .15s}}
.kv-filter:hover,.kv-filter-active{{border-color:var(--accent,#3b82f6);color:var(--accent,#3b82f6);background:rgba(59,130,246,.08)}}
.kv-filter-active{{font-weight:600}}
.kv-tl-wrap{{margin:.5rem 0 .3rem}}
.kv-tl-title{{font-size:.68rem;font-weight:700;color:var(--t3,#64748b);text-transform:uppercase;letter-spacing:.05em;margin-bottom:.35rem}}
.kv-tl-events{{display:flex;flex-direction:column;gap:.22rem}}
.kv-tl-event{{display:flex;align-items:baseline;gap:.5rem;font-size:.76rem}}
.kv-tl-dot{{width:7px;height:7px;border-radius:50%;flex-shrink:0;display:inline-block;margin-bottom:-1px}}
.kv-tl-date{{color:var(--t3,#64748b);font-size:.7rem;flex-shrink:0;min-width:2.8rem;font-variant-numeric:tabular-nums}}
.kv-tl-evt{{color:var(--t2,#94a3b8);flex:1}}
.kv-tl-link{{color:var(--accent,#3b82f6);text-decoration:none;font-size:.7rem;margin-left:.2rem}}
.kv-tl-clickable{{border-radius:4px;padding:1px 3px;margin:-1px -3px;transition:background .15s}}
.kv-tl-clickable:hover{{background:rgba(59,130,246,.1)}}
.kv-chat{{margin-top:.7rem;border:1px solid var(--border,#334155);border-radius:10px;overflow:hidden}}
.kv-chat-toggle{{width:100%;text-align:left;padding:.55rem 1rem;background:var(--card,#1e1e2e);border:none;cursor:pointer;color:var(--t1,#e2e8f0);font-size:.83rem;display:flex;justify-content:space-between;align-items:center}}
.kv-chat-toggle:hover{{background:var(--card2,#26263a)}}
.kv-chat-arr{{font-size:.7rem;color:var(--t3,#64748b)}}
.kv-chat-body{{padding:.7rem 1rem;background:var(--card,#1e1e2e);border-top:1px solid var(--border,#334155)}}
.kv-quick-btns{{display:flex;gap:.35rem;flex-wrap:wrap;margin-bottom:.55rem}}
.kv-quick-btns button{{font-size:.7rem;padding:3px 9px;border-radius:20px;border:1px solid var(--border,#334155);background:transparent;color:var(--t2,#94a3b8);cursor:pointer;transition:all .15s}}
.kv-quick-btns button:hover{{border-color:var(--accent,#3b82f6);color:var(--accent,#3b82f6)}}
.kv-ask-row{{display:flex;gap:.35rem;margin-bottom:.5rem}}
.kv-input{{flex:1;padding:.38rem .65rem;border-radius:6px;border:1px solid var(--border,#334155);background:var(--bg,#0f1117);color:var(--t1,#e2e8f0);font-size:.8rem}}
.kv-ask-btn{{padding:.38rem .75rem;border-radius:6px;border:none;background:var(--accent,#3b82f6);color:#fff;cursor:pointer;font-size:.8rem;font-weight:600;white-space:nowrap}}
.kv-ask-btn:hover{{opacity:.85}}
.kv-answer{{font-size:.82rem;line-height:1.55}}
.kv-answer-text{{color:var(--t1,#e2e8f0);padding:.4rem 0;white-space:pre-wrap}}
.kv-loading{{color:var(--t3,#64748b);font-style:italic;padding:.35rem 0}}
.kv-error{{color:#ef4444;font-size:.78rem;padding:.35rem 0}}
</style>
<div class="kv-container">
<div class="kv-rode-draad">
  <div>
    <span class="kv-rd-label">🔴 Rode draad</span>
    <p class="kv-rd-text" id="kv-rd-{uid}"></p>
  </div>
</div>
<div class="kv-duiding" id="kv-duiding-{uid}">
  <div class="kv-duiding-badges">{badges}</div>
  <p class="kv-duiding-text" id="kv-pd-{uid}"></p>
</div>
<div class="kv-filters" id="kv-filters-{uid}">
  <button class="kv-filter kv-filter-active" data-filter="all">Alles</button>
  <button class="kv-filter" data-filter="rabobank">💼 Werk</button>
  <button class="kv-filter" data-filter="ai">🤖 AI</button>
  <button class="kv-filter" data-filter="financieel">📊 Financieel</button>
  <button class="kv-filter" data-filter="wereld">🌍 Wereld</button>
  <button class="kv-filter" data-filter="nederland">🇳🇱 NL</button>
</div>
<div class="ns-viz-d3" id="kv-wrap-{uid}">
  <svg id="kv-svg-{uid}"></svg>
  <div class="ns-viz-d3-tooltip" id="kv-tip-{uid}"></div>
</div>
<div class="kv-tl-wrap" id="kv-tl-{uid}"></div>
<div class="kv-chat" id="kv-chat-{uid}">
  <button class="kv-chat-toggle" onclick="(function(){{var b=document.getElementById('kv-cbody-{uid}');var a=document.querySelector('#kv-chat-{uid} .kv-chat-arr');if(b.style.display==='none'){{b.style.display='block';if(a)a.textContent='▴';}}else{{b.style.display='none';if(a)a.textContent='▾';}}}})()">
    💬 Vraag Claude over deze verbanden <span class="kv-chat-arr">▾</span>
  </button>
  <div class="kv-chat-body" id="kv-cbody-{uid}" style="display:none">
    <div class="kv-quick-btns">
      <button onclick="kvAsk_{uid}('Wat betekent dit voor mijn werk bij Rabobank en IRB-validatie?')">💼 Rabobank-impact</button>
      <button onclick="kvAsk_{uid}('Hoe heeft dit thema zich de afgelopen weken ontwikkeld?')">📅 Historisch</button>
      <button onclick="kvAsk_{uid}('Wat zijn de IRB- en regulatoire implicaties van vandaag?')">📋 Regulatoir</button>
      <button onclick="kvAsk_{uid}('Wat is de samenhang tussen het AI-nieuws en de andere verbanden?')">🤖 AI-samenhang</button>
    </div>
    <div class="kv-ask-row">
      <input type="text" id="kv-inp-{uid}" class="kv-input" placeholder="Stel een vraag over de verbanden van vandaag..."
             onkeydown="if(event.key==='Enter')kvAsk_{uid}(this.value)">
      <button class="kv-ask-btn" onclick="kvAsk_{uid}(document.getElementById('kv-inp-{uid}').value)">Vraag →</button>
    </div>
    <div class="kv-answer" id="kv-ans-{uid}"></div>
  </div>
</div>
</div>
<script>(function(){{
  var rd=document.getElementById('kv-rd-{uid}');
  var pd=document.getElementById('kv-pd-{uid}');
  if(rd)rd.textContent={rode_draad};
  if(pd)pd.textContent={pers_duiding};

  if(typeof d3==='undefined'){{
    document.getElementById('kv-wrap-{uid}').innerHTML='<p style="padding:1rem;color:var(--t3)">D3.js niet geladen.</p>';
    return;
  }}
  var nodes={nodes_json};
  var links={links_json};
  var timeline={tl_json};
  var cm={{'nederland':'#ea580c','wereld':'#2563eb','financieel':'#d97706',
           'regulatoir':'#3b5bdb','huizenmarkt':'#2f9e44','sport':'#16a34a',
           'aitech':'#7c3aed','ai':'#7c3aed','tech':'#7c3aed','default':'#64748b'}};
  var relC={{'rabobank':'#f59e0b','irb':'#f59e0b','avm':'#f59e0b','ai':'#a855f7','persoonlijk':'#06b6d4'}};

  function nodeR(d){{return 22+(d.weight||3)*3.5;}}
  function getRelColor(d){{
    var rel=d.relevance||[];
    var ord=['rabobank','irb','avm','ai','persoonlijk'];
    for(var i=0;i<ord.length;i++){{if(rel.indexOf(ord[i])>=0)return relC[ord[i]];}}
    return null;
  }}

  var wrap=document.getElementById('kv-wrap-{uid}');
  var W=wrap.clientWidth||700,H=420;
  var tip=document.getElementById('kv-tip-{uid}');

  var svg=d3.select('#kv-svg-{uid}')
    .attr('width',W).attr('height',H)
    .attr('viewBox','0 0 '+W+' '+H)
    .style('opacity',0);

  var defs=svg.append('defs');
  Object.keys(cm).forEach(function(k){{
    defs.append('marker').attr('id','arr-{uid}-'+k)
      .attr('viewBox','0 0 10 10').attr('refX',46).attr('refY',5)
      .attr('markerWidth',6).attr('markerHeight',6).attr('orient','auto')
      .append('path').attr('d','M0,0 L10,5 L0,10 z').attr('fill',cm[k]).attr('opacity',.75);
  }});

  var sim=d3.forceSimulation(nodes)
    .force('link',d3.forceLink(links).id(function(d){{return d.id;}})
      .distance(function(d){{return 180-(d.strength||3)*12;}}))
    .force('charge',d3.forceManyBody().strength(-580))
    .force('center',d3.forceCenter(W/2,H/2))
    .force('collision',d3.forceCollide(function(d){{return nodeR(d)+14;}}));

  var linkSel=svg.append('g').selectAll('line').data(links).join('line')
    .attr('stroke',function(d){{
      var src=nodes.find(function(n){{return n.id===(d.source.id||d.source);}});
      return(src&&cm[src.group])||cm.default;
    }})
    .attr('stroke-opacity',.55)
    .attr('stroke-width',function(d){{return Math.max(1,Math.min(5,d.strength||2));}} )
    .attr('marker-end',function(d){{
      if(!d.directed)return null;
      var src=nodes.find(function(n){{return n.id===(d.source.id||d.source);}});
      return'url(#arr-{uid}-'+((src&&src.group)||'default')+')';
    }});

  var linkLbl=svg.append('g').selectAll('text').data(links).join('text')
    .text(function(d){{return d.label||'';}})
    .attr('font-size',9).attr('fill','#78716c').attr('text-anchor','middle')
    .attr('dy',-5).style('pointer-events','none');

  var nodeSel=svg.append('g').selectAll('g').data(nodes).join('g')
    .style('cursor','pointer')
    .call(d3.drag()
      .on('start',function(ev,d){{if(!ev.active)sim.alphaTarget(.3).restart();d.fx=d.x;d.fy=d.y;d3.select(this).style('cursor','grabbing');}})
      .on('drag',function(ev,d){{d.fx=ev.x;d.fy=ev.y;}})
      .on('end',function(ev,d){{if(!ev.active)sim.alphaTarget(0);d.fx=null;d.fy=null;d3.select(this).style('cursor','pointer');}}));

  nodeSel.append('circle').attr('r',function(d){{return nodeR(d)+10;}})
    .attr('fill',function(d){{return(cm[d.group]||cm.default)+'11';}}).attr('stroke','none');

  nodeSel.each(function(d){{
    var rc=getRelColor(d);
    if(rc)d3.select(this).append('circle')
      .attr('r',function(d2){{return nodeR(d2)+4;}})
      .attr('fill','none').attr('stroke',rc).attr('stroke-width',2.5).attr('stroke-dasharray','5,3');
  }});

  nodeSel.append('circle').attr('class','node-circle')
    .attr('r',nodeR)
    .attr('fill',function(d){{return(cm[d.group]||cm.default)+'22';}})
    .attr('stroke',function(d){{return cm[d.group]||cm.default;}})
    .attr('stroke-width',2.5);

  nodeSel.each(function(d){{
    var el=d3.select(this);
    var words=(d.label||d.id).split(' ');
    var lh=13,oy=-(words.length-1)*lh/2;
    words.forEach(function(w,i){{
      el.append('text').attr('text-anchor','middle')
        .attr('dy',(oy+i*lh)+'px').attr('font-size',10).attr('font-weight',700)
        .attr('fill',function(d2){{return cm[d2.group]||cm.default;}})
        .style('pointer-events','none').text(w);
    }});
  }});

  // Klik → open linker panel met node-context
  nodeSel.on('click',function(ev,d){{
    ev.stopPropagation();
    var histHtml=d.history&&d.history.length
      ?'<h5 style="margin:1.2rem 0 .4rem">📅 Historisch</h5><ul style="padding-left:1.2rem;line-height:1.8">'
        +d.history.map(function(h){{return'<li>'+h+'</li>';}}).join('')+'</ul>'
      :'';
    var tgt=(d.articles&&d.articles.length)?d.articles[0]:d.group;
    var navHtml='<p style="margin-top:1.2rem"><a href="#" onclick="(function(){{closeKvLeftPanel();setTimeout(function(){{var e=document.getElementById(\''+tgt+'\');if(e)e.scrollIntoView({{behavior:\'smooth\',block:\'start\'}});}},380);}})();return false;" style="color:var(--accent,#3b82f6)">→ Ga naar sectie in dagkrant</a></p>';
    var relBadge=(d.relevance&&d.relevance.length)
      ?'<p style="margin:.4rem 0 .8rem"><span style="font-size:.7rem;padding:2px 8px;border-radius:12px;background:rgba(100,116,139,.15);color:var(--t3)">'+d.relevance.join(' · ')+'</span></p>'
      :'';
    var html='<h4 style="margin:0 0 .4rem">'+d.label+'</h4>'
      +relBadge
      +'<p style="color:var(--t2,#94a3b8);line-height:1.6">'+( d.desc||'')+'</p>'
      +histHtml+navHtml;
    if(typeof openKvLeftPanel==='function'){{
      openKvLeftPanel(d.label, d.group+' · verbanden', html);
    }}else{{
      // Fallback: scroll
      var el=document.getElementById(tgt);
      if(el)el.scrollIntoView({{behavior:'smooth',block:'start'}});
    }}
  }});

  nodeSel
    .on('mouseenter',function(ev,d){{
      var hist=d.history&&d.history.length
        ?'<br><small style="color:#94a3b8;line-height:1.6">'+d.history.slice(0,3).join('<br>')+'</small>':'';
      tip.style.opacity='1';
      tip.innerHTML='<strong>'+d.label+'</strong><br>'+(d.desc||'')+hist;
      var conn=new Set([d.id]);
      links.forEach(function(l){{
        var s=l.source.id||l.source,t=l.target.id||l.target;
        if(s===d.id)conn.add(t);if(t===d.id)conn.add(s);
      }});
      nodeSel.style('opacity',function(n){{return conn.has(n.id)?1:.1;}});
      linkSel.style('opacity',function(l){{
        var s=l.source.id||l.source,t=l.target.id||l.target;
        return(s===d.id||t===d.id)?1:.04;
      }});
      linkLbl.style('opacity',function(l){{
        var s=l.source.id||l.source,t=l.target.id||l.target;
        return(s===d.id||t===d.id)?1:0;
      }});
      var r=nodeR(d);
      d3.select(this).select('.node-circle').attr('r',r+7).attr('stroke-width',3.5);
    }})
    .on('mousemove',function(ev){{
      var r=wrap.getBoundingClientRect();
      var tx=ev.clientX-r.left+14,ty=ev.clientY-r.top-10;
      if(tx+265>W)tx=tx-265-28;
      tip.style.left=tx+'px';tip.style.top=ty+'px';
    }})
    .on('mouseleave',function(ev,d){{
      tip.style.opacity='0';
      nodeSel.style('opacity',1);
      linkSel.style('opacity',.55);
      linkLbl.style('opacity',1);
      d3.select(this).select('.node-circle').attr('r',nodeR(d)).attr('stroke-width',2.5);
    }});

  var pad=65;
  sim.on('tick',function(){{
    linkSel
      .attr('x1',function(d){{return Math.max(pad,Math.min(W-pad,d.source.x));}})
      .attr('y1',function(d){{return Math.max(pad,Math.min(H-pad,d.source.y));}})
      .attr('x2',function(d){{return Math.max(pad,Math.min(W-pad,d.target.x));}})
      .attr('y2',function(d){{return Math.max(pad,Math.min(H-pad,d.target.y));}});
    linkLbl
      .attr('x',function(d){{return(d.source.x+d.target.x)/2;}})
      .attr('y',function(d){{return(d.source.y+d.target.y)/2;}});
    nodeSel.attr('transform',function(d){{
      return'translate('+Math.max(pad,Math.min(W-pad,d.x))+','+Math.max(pad,Math.min(H-pad,d.y))+')';
    }});
  }});

  setTimeout(function(){{svg.transition().duration(700).style('opacity',1);}},500);

  window.addEventListener('resize',function(){{
    var nw=wrap.clientWidth;
    if(Math.abs(nw-W)>20){{
      W=nw;svg.attr('width',W).attr('viewBox','0 0 '+W+' '+H);
      sim.force('center',d3.forceCenter(W/2,H/2)).alpha(.3).restart();
    }}
  }});

  // Filter knoppen
  document.querySelectorAll('#kv-filters-{uid} .kv-filter').forEach(function(btn){{
    btn.addEventListener('click',function(){{
      document.querySelectorAll('#kv-filters-{uid} .kv-filter')
        .forEach(function(b){{b.classList.remove('kv-filter-active');}});
      btn.classList.add('kv-filter-active');
      var f=btn.getAttribute('data-filter');
      nodeSel.style('opacity',function(d){{
        if(f==='all')return 1;
        var rel=d.relevance||[];
        if(f==='rabobank'&&(rel.indexOf('rabobank')>=0||rel.indexOf('irb')>=0||rel.indexOf('avm')>=0))return 1;
        if(f==='ai'&&(rel.indexOf('ai')>=0||d.group==='aitech'))return 1;
        if(f===d.group)return 1;
        return.08;
      }});
      linkSel.style('opacity',function(l){{
        if(f==='all')return.55;
        var s=nodes.find(function(n){{return n.id===(l.source.id||l.source);}});
        var t=nodes.find(function(n){{return n.id===(l.target.id||l.target);}});
        if(!s||!t)return.08;
        var sv=f==='rabobank'?(s.relevance||[]).some(function(r){{return['rabobank','irb','avm'].indexOf(r)>=0;}}):
               f==='ai'?((s.relevance||[]).indexOf('ai')>=0||s.group==='aitech'):s.group===f;
        var tv=f==='rabobank'?(t.relevance||[]).some(function(r){{return['rabobank','irb','avm'].indexOf(r)>=0;}}):
               f==='ai'?((t.relevance||[]).indexOf('ai')>=0||t.group==='aitech'):t.group===f;
        return(sv||tv)?.55:.04;
      }});
    }});
  }});

  // Tijdlijn opbouwen
  (function(){{
    var tl=timeline||[];
    var tlEl=document.getElementById('kv-tl-{uid}');
    if(!tl.length||!tlEl)return;
    tl.sort(function(a,b){{return a.datum.localeCompare(b.datum);}});
    var html='<div class="kv-tl-title">📅 Historische tijdlijn — klik voor volledige dagkrant</div><div class="kv-tl-events">';
    tl.forEach(function(ev){{
      var nd=nodes.find(function(n){{return n.id===ev.thema_id;}});
      var color=(nd&&cm[nd.group])||cm.default;
      var dd=ev.datum?ev.datum.slice(5):'';
      var evtTxt=(ev.event||'');
      var digestAttr=ev.digest?'data-digest="'+ev.digest+'" data-title="'+evtTxt.replace(/"/g,'&quot;')+'"':'';
      var cursor=ev.digest?'cursor:pointer;':'';
      var hoverCls=ev.digest?'kv-tl-event kv-tl-clickable':'kv-tl-event';
      html+='<div class="'+hoverCls+'" '+digestAttr+' style="'+cursor+'">'
        +'<span class="kv-tl-dot" style="background:'+color+'"></span>'
        +'<span class="kv-tl-date">'+dd+'</span>'
        +'<span class="kv-tl-evt">'+evtTxt+'</span>'
        +(ev.digest?'<span class="kv-tl-link" title="Open archief">↗</span>':'')
        +'</div>';
    }});
    html+='</div>';
    tlEl.innerHTML=html;
    // Klik-handler voor tijdlijn-items
    tlEl.querySelectorAll('.kv-tl-clickable').forEach(function(el){{
      el.addEventListener('click',function(){{
        var d=el.getAttribute('data-digest');
        var t=el.getAttribute('data-title');
        if(d&&typeof openKvDigest==='function')openKvDigest(d,t);
      }});
    }});
  }})();
}})();

function kvAsk_{uid}(q){{
  if(!q||!q.trim())return;
  var ans=document.getElementById('kv-ans-{uid}');
  var inp=document.getElementById('kv-inp-{uid}');
  var body=document.getElementById('kv-cbody-{uid}');
  if(body)body.style.display='block';
  var arr=document.querySelector('#kv-chat-{uid} .kv-chat-arr');
  if(arr)arr.textContent='▴';
  ans.innerHTML='<div class="kv-loading">⏳ Claude analyseert...</div>';
  if(inp)inp.value='';
  fetch('http://127.0.0.1:7432/kruisverband-chat',{{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{vraag:q.trim(),datum_iso:'{datum_iso}'}})
  }}).then(function(r){{return r.json();}})
  .then(function(data){{
    if(data.antwoord){{
      ans.innerHTML='<div class="kv-answer-text"><strong>Claude:</strong><br>'+data.antwoord+'</div>';
    }}else{{
      ans.innerHTML='<div class="kv-error">Fout: '+(data.error||'onbekend')+'</div>';
    }}
  }}).catch(function(){{
    ans.innerHTML='<div class="kv-error">API niet bereikbaar — start api_server.py</div>';
  }});
}}
</script>"""

                CACHE[cache_key] = visual
                self.send_json(200, {"visual_html": visual, "cached": False})
                return
            except _json2.JSONDecodeError as e:
                self.send_json(500, {"error": f"JSON parse fout: {e}"})
                return
            except subprocess.TimeoutExpired:
                self.send_json(500, {"error": "Timeout (150s)"})
                return
            except Exception as e:
                self.send_json(500, {"error": str(e)[:200]})
                return

        # ── /kruisverband-chat ────────────────────────────────────────────
        if self.path == "/kruisverband-chat":
            import json as _json3
            vraag = (body.get("vraag") or "").strip()
            datum_q = (body.get("datum_iso") or "").strip()

            if not vraag:
                self.send_json(400, {"error": "Veld 'vraag' is verplicht"})
                return

            ctx = KV_CONTEXT_CACHE.get(datum_q) or KV_CONTEXT_CACHE.get("latest") or {}
            if not ctx:
                self.send_json(400, {"error": "Geen kruisverband-context beschikbaar. Genereer eerst de visualisatie."})
                return

            graph_str = _json3.dumps(ctx.get("graph", {}), ensure_ascii=False)[:3000]
            archief_str = (ctx.get("archief") or "")[:1200]
            werk_str    = (ctx.get("werk") or "")[:600]
            kv_str      = (ctx.get("kruisverband_md") or "")[:1500]
            ctx_datum   = ctx.get("datum_iso", datum_q)

            chat_prompt = f"""Je bent een nieuwsanalist voor Marc van Marrewijk (model validator bij Rabobank Utrecht: IRB/credit risk, CRR3, EBA, ECB EGIM, PD/LGD/CCF, Calcasa AVM). Interesses: AI/Claude, Formule 1, schaken.

KRUISVERBAND-ANALYSE ({ctx_datum}):
{kv_str}

VERBANDEN-DIAGRAM (JSON):
{graph_str}

HISTORISCHE CONTEXT UIT ARCHIEF:
{archief_str if archief_str else "(geen historische data beschikbaar)"}

RABOBANK/IRB VAULT-CONTEXT:
{werk_str if werk_str else "(geen werk-context beschikbaar)"}

VRAAG VAN MARC:
{vraag}

Beantwoord in max 300 woorden in vloeiend Nederlands. Verwijs specifiek naar de verbanden en historische context. Wees analytisch en praktisch — Marc is expert in IRB/credit risk."""

            try:
                t0 = time.time()
                print(f"  [API] KV-chat: '{vraag[:50]}…'", file=sys.stderr)
                result = subprocess.run(
                    ["claude", "-p", chat_prompt, "--model", CLAUDE_MODEL,
                     "--dangerously-skip-permissions"],
                    capture_output=True, text=True, timeout=90,
                    stdin=subprocess.DEVNULL,
                    cwd=str(Path.home() / "nieuwsstation"),
                )
                elapsed = time.time() - t0
                print(f"  [API] KV-chat klaar in {elapsed:.0f}s", file=sys.stderr)

                if result.returncode != 0:
                    self.send_json(500, {"error": result.stderr[:200] or "Claude mislukt"})
                    return

                self.send_json(200, {"antwoord": result.stdout.strip(), "model": CLAUDE_MODEL})
                return
            except subprocess.TimeoutExpired:
                self.send_json(500, {"error": "Timeout (90s)"})
                return
            except Exception as e:
                self.send_json(500, {"error": str(e)[:200]})
                return

        # ── /background ───────────────────────────────────────────────────
        if not title:
            self.send_json(400, {"error": "Veld 'title' is verplicht"})
            return

        cache_key = title[:60].lower()
        if cache_key in CACHE:
            print(f"  [API] Cache hit: {cache_key[:40]}…", file=sys.stderr)
            self.send_json(200, {"html": CACHE[cache_key], "cached": True})
            return

        related_articles = body.get("related_articles", [])
        print(f"  [API] Genereren: {title[:60]}… ({len(related_articles)} verwante)", file=sys.stderr)
        html, error, archive_hits = generate_background(title, summary, sources, topic, extra, related_articles)

        if error:
            self.send_json(500, {"error": error, "success": False})
            return

        CACHE[cache_key] = html
        self.send_json(200, {"html": html, "success": True, "cached": False,
                             "archive_hits": archive_hits})


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Nieuwsstation Achtergrond API")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Poort (default: {DEFAULT_PORT})")
    args = parser.parse_args()

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[Nieuwsstation API] Luistert op http://127.0.0.1:{args.port}", file=sys.stderr)
    print(f"[Nieuwsstation API] Model (planner): {CLAUDE_MODEL}", file=sys.stderr)
    print(f"[Nieuwsstation API] Model (achtergrond): {BACKGROUND_MODEL}", file=sys.stderr)
    print(f"[Nieuwsstation API] Stop met Ctrl+C", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Nieuwsstation API] Gestopt.", file=sys.stderr)


if __name__ == "__main__":
    main()
