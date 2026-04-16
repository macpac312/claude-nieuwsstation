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
                             "/kruisverband-visual"):
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

        # ── /kruisverband-visual ──────────────────────────────────────────
        if self.path == "/kruisverband-visual":
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

            top_lines = []
            for t in topnieuws[:7]:
                titel = str(t.get("titel", ""))[:90]
                sectie = str(t.get("sectie", ""))[:20]
                if titel:
                    top_lines.append(f"- [{sectie}] {titel}")
            top_block = "\n".join(top_lines) if top_lines else "(geen top-artikelen)"

            # Claude levert ALLEEN JSON-data — D3-code zit in de template
            kv_prompt = f"""Analyseer onderstaande kruisverband-tekst en top-artikelen van de dagkrant.
Geef UITSLUITEND een JSON-object terug met nodes en links voor een interactief verbanden-diagram.

KRUISVERBAND-ANALYSE:
{kv_md[:2500]}

TOP-ARTIKELEN:
{top_block}

REGELS:
- 5-8 nodes: de belangrijkste thema's/actoren van vandaag
- 5-10 links: de verbanden tussen die thema's
- node.id: lowercase, geen spaties, uniek (bijv. "ecb-rente", "huizenprijzen")
- node.label: max 3 woorden, begrijpelijk als knooppunt-label
- node.group: één van: nederland, wereld, financieel, regulatoir, huizenmarkt, sport, aitech, default
- node.desc: max 20 woorden — wat dit thema vandaag betekent
- link.label: max 3 woorden — hoe source het target beïnvloedt (bijv. "verhoogt druk op", "versnelt", "blokkeert")
- link.directed: true als causaliteit duidelijk is, false bij tweerichting/correlatie
- Kies thema's die écht in verbinding staan — geen losse nodes zonder links

FORMAAT — alleen dit JSON, geen uitleg, geen markdown:
{{"nodes":[{{"id":"voorbeeld","label":"Voorbeeld thema","group":"financieel","desc":"Beschrijving van de rol vandaag"}}],"links":[{{"source":"id1","target":"id2","label":"beïnvloedt","directed":true}}]}}"""

            try:
                import uuid as _uuid2
                import json as _json2
                uid = _uuid2.uuid4().hex[:8]

                t0 = time.time()
                print(f"  [API] Kruisverband D3-data genereren…", file=sys.stderr)
                result = subprocess.run(
                    ["claude", "-p", kv_prompt, "--model", BACKGROUND_MODEL,
                     "--dangerously-skip-permissions"],
                    capture_output=True, text=True, timeout=90,
                    stdin=subprocess.DEVNULL,
                    cwd=str(Path.home() / "nieuwsstation"),
                )
                elapsed = time.time() - t0
                print(f"  [API] D3-data klaar in {elapsed:.0f}s (code {result.returncode})", file=sys.stderr)

                if result.returncode != 0:
                    self.send_json(500, {"error": result.stderr[:300] or "Claude mislukt"})
                    return

                raw = result.stdout.strip()
                for fence in ("```json", "```"):
                    if raw.startswith(fence): raw = raw[len(fence):]
                if raw.endswith("```"): raw = raw[:-3]
                raw = raw.strip()

                # Extraheer JSON
                m = re.search(r'\{[\s\S]+\}', raw)
                if not m:
                    self.send_json(500, {"error": "Geen JSON in response"})
                    return
                graph = _json2.loads(m.group(0))
                nodes_json = _json2.dumps(graph.get("nodes", []), ensure_ascii=False)
                links_json = _json2.dumps(graph.get("links", []), ensure_ascii=False)

                # D3 force-graph template — volledig self-contained
                visual = f"""<div class="ns-viz">
<div class="ns-viz-title">🕸 Verbanden van vandaag — klik of sleep knooppunten</div>
<div class="ns-viz-d3" id="kv-wrap-{uid}">
  <svg id="kv-svg-{uid}"></svg>
  <div class="ns-viz-d3-tooltip" id="kv-tip-{uid}"></div>
</div>
<script>(function(){{
  if(typeof d3==='undefined'){{
    document.getElementById('kv-wrap-{uid}').innerHTML='<p style="padding:1rem;color:var(--t3)">D3.js niet geladen — herlaad de pagina.</p>';
    return;
  }}
  var nodes={nodes_json};
  var links={links_json};
  // Kleurmap per sectie
  var cm={{'nederland':'#ea580c','wereld':'#2563eb','financieel':'#d97706',
           'regulatoir':'#3b5bdb','huizenmarkt':'#2f9e44','sport':'#16a34a',
           'aitech':'#7c3aed','ai':'#7c3aed','tech':'#7c3aed','default':'#7c3aed'}};

  var wrap=document.getElementById('kv-wrap-{uid}');
  var W=wrap.clientWidth||680, H=370;
  var tip=document.getElementById('kv-tip-{uid}');

  var svg=d3.select('#kv-svg-{uid}')
    .attr('width',W).attr('height',H)
    .attr('viewBox','0 0 '+W+' '+H)
    .style('opacity',0);

  // Arrow markers — één per kleur
  var defs=svg.append('defs');
  Object.entries(cm).forEach(function(e){{
    defs.append('marker').attr('id','arr-{uid}-'+e[0])
      .attr('viewBox','0 0 10 10').attr('refX',28).attr('refY',5)
      .attr('markerWidth',6).attr('markerHeight',6).attr('orient','auto')
      .append('path').attr('d','M0,0 L10,5 L0,10 z').attr('fill',e[1]).attr('opacity',.7);
  }});

  var sim=d3.forceSimulation(nodes)
    .force('link',d3.forceLink(links).id(function(d){{return d.id;}}).distance(140))
    .force('charge',d3.forceManyBody().strength(-420))
    .force('center',d3.forceCenter(W/2,H/2))
    .force('collision',d3.forceCollide(52));

  // Links
  var linkSel=svg.append('g').selectAll('line').data(links).join('line')
    .attr('stroke',function(d){{
      var src=nodes.find(function(n){{return n.id===(d.source.id||d.source);}});
      return (src&&cm[src.group])||cm.default;
    }})
    .attr('stroke-opacity',.45).attr('stroke-width',2)
    .attr('marker-end',function(d){{
      if(!d.directed)return null;
      var src=nodes.find(function(n){{return n.id===(d.source.id||d.source);}});
      var g=(src&&src.group)||'default';
      return 'url(#arr-{uid}-'+g+')';
    }});

  // Link labels
  var linkLbl=svg.append('g').selectAll('text').data(links).join('text')
    .text(function(d){{return d.label||'';}})
    .attr('font-size',9).attr('fill','#78716c').attr('text-anchor','middle')
    .attr('dy',-4).style('pointer-events','none');

  // Node groups
  var nodeSel=svg.append('g').selectAll('g').data(nodes).join('g')
    .style('cursor','grab')
    .call(d3.drag()
      .on('start',function(ev,d){{if(!ev.active)sim.alphaTarget(.3).restart();d.fx=d.x;d.fy=d.y;d3.select(this).style('cursor','grabbing');}})
      .on('drag',function(ev,d){{d.fx=ev.x;d.fy=ev.y;}})
      .on('end',function(ev,d){{if(!ev.active)sim.alphaTarget(0);d.fx=null;d.fy=null;d3.select(this).style('cursor','grab');}})
    );

  // Pulserende achtergrondcirkel
  nodeSel.append('circle').attr('r',42)
    .attr('fill',function(d){{return (cm[d.group]||cm.default)+'11';}})
    .attr('stroke','none');

  // Hoofd-cirkel
  nodeSel.append('circle').attr('class','node-circle').attr('r',36)
    .attr('fill',function(d){{return (cm[d.group]||cm.default)+'1e';}})
    .attr('stroke',function(d){{return cm[d.group]||cm.default;}})
    .attr('stroke-width',2.2)
    .style('transition','r .2s,stroke-width .2s');

  // Label — meerdere regels
  nodeSel.each(function(d){{
    var el=d3.select(this);
    var words=(d.label||d.id).split(' ');
    var lh=14, oy=-(words.length-1)*lh/2;
    words.forEach(function(w,i){{
      el.append('text')
        .attr('text-anchor','middle').attr('dy',oy+i*lh+'.35em')
        .attr('font-size',11).attr('font-weight',700)
        .attr('fill',function(d2){{return cm[d2.group]||cm.default;}})
        .style('pointer-events','none').text(w);
    }});
  }});

  // Hover
  nodeSel
    .on('mouseenter',function(ev,d){{
      // Tooltip
      tip.style.opacity='1';
      tip.innerHTML='<strong>'+d.label+'</strong><br>'+(d.desc||'');
      // Dim niet-verbonden
      var conn=new Set([d.id]);
      links.forEach(function(l){{
        var sid=l.source.id||l.source, tid=l.target.id||l.target;
        if(sid===d.id)conn.add(tid);
        if(tid===d.id)conn.add(sid);
      }});
      nodeSel.style('opacity',function(n){{return conn.has(n.id)?1:.18;}});
      linkSel.style('opacity',function(l){{
        var sid=l.source.id||l.source,tid=l.target.id||l.target;
        return(sid===d.id||tid===d.id)?.9:.06;
      }});
      linkLbl.style('opacity',function(l){{
        var sid=l.source.id||l.source,tid=l.target.id||l.target;
        return(sid===d.id||tid===d.id)?1:0;
      }});
      d3.select(this).select('.node-circle').attr('r',42).attr('stroke-width',3);
    }})
    .on('mousemove',function(ev){{
      var r=wrap.getBoundingClientRect();
      var tx=ev.clientX-r.left+14, ty=ev.clientY-r.top-10;
      if(tx+240>W)tx=tx-240-28;
      tip.style.left=tx+'px'; tip.style.top=ty+'px';
    }})
    .on('mouseleave',function(){{
      tip.style.opacity='0';
      nodeSel.style('opacity',1);
      linkSel.style('opacity',.45);
      linkLbl.style('opacity',1);
      d3.select(this).select('.node-circle').attr('r',36).attr('stroke-width',2.2);
    }});

  var pad=55;
  sim.on('tick',function(){{
    linkSel
      .attr('x1',function(d){{return Math.max(pad,Math.min(W-pad,d.source.x));}})
      .attr('y1',function(d){{return Math.max(pad,Math.min(H-pad,d.source.y));}})
      .attr('x2',function(d){{return Math.max(pad,Math.min(W-pad,d.target.x));}})
      .attr('y2',function(d){{return Math.max(pad,Math.min(H-pad,d.target.y));}});
    linkLbl
      .attr('x',function(d){{return (d.source.x+d.target.x)/2;}})
      .attr('y',function(d){{return (d.source.y+d.target.y)/2;}});
    nodeSel.attr('transform',function(d){{
      return 'translate('+Math.max(pad,Math.min(W-pad,d.x))+','+Math.max(pad,Math.min(H-pad,d.y))+')';
    }});
  }});

  // Fade in na initieel settlement
  setTimeout(function(){{svg.transition().duration(700).style('opacity',1);}},500);

  // Responsive resize
  window.addEventListener('resize',function(){{
    var nw=wrap.clientWidth;
    if(Math.abs(nw-W)>20){{W=nw;svg.attr('width',W).attr('viewBox','0 0 '+W+' '+H);sim.force('center',d3.forceCenter(W/2,H/2)).alpha(.3).restart();}}
  }});
}})();
</script></div>"""

                CACHE[cache_key] = visual
                self.send_json(200, {"visual_html": visual, "cached": False})
                return
            except _json2.JSONDecodeError as e:
                self.send_json(500, {"error": f"JSON parse fout: {e}"})
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
