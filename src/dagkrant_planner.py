#!/usr/bin/env python3
"""
Dagkrant planner v2: Claude selecteert/prioriteert, Python bouwt de HTML.

Stap 1: Stuur ALLEEN titels + bronnen naar Claude (kleine input)
Stap 2: Claude geeft ALLEEN redactionele keuzes terug (kleine output)
Stap 3: Python bouwt het volledige plan uit de brondata

Input:  /tmp/dagkrant-selected.json, /tmp/dagkrant-widgets.json
Output: /tmp/dagkrant-plan.json
"""
import json, sys, subprocess, re, pathlib, time, os
from datetime import datetime, timezone

VAULT_SEARCH = pathlib.Path.home() / "nieuwsstation/src/vault_search.py"
BRIEFINGS    = pathlib.Path.home() / "Documents/WorkMvMOBS/Briefings"
VAULT_PATH   = pathlib.Path.home() / "Documents/WorkMvMOBS"


def search_vault_full(query: str, max_results: int = 5) -> tuple[str, list[str]]:
    """
    Doorzoek de volledige Obsidian vault (niet alleen dagkrant-archief).
    Retourneert (context_tekst, wikilinks_lijst) voor vault-connecties.
    """
    if not VAULT_SEARCH.exists() or not VAULT_PATH.exists():
        return "", []
    try:
        result = subprocess.run(
            ["python3", str(VAULT_SEARCH), "--query", query,
             "--top", str(max_results), "--min-score", "1.5",
             "--vault", str(VAULT_PATH)],
            capture_output=True, text=True, timeout=12,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return "", []
        data = json.loads(result.stdout)
        notes = data.get("notes", [])
        if not notes:
            return "", []
        context_parts = []
        connecties = []
        for note in notes:
            title  = note.get("title", "")
            path   = note.get("path", "")
            excpt  = note.get("excerpt", "")[:200].replace("\n", " ")
            context_parts.append(f"[{title}] {excpt}")
            if title:
                connecties.append({
                    "title":   title,
                    "path":    path,
                    "excerpt": excpt[:120],
                })
        return "\n".join(context_parts), connecties
    except Exception:
        return "", []


def search_archive(query: str, max_results: int = 3) -> str:
    """
    Doorzoek dagkrant-archief (Briefings/*.md) op het onderwerp.
    Retourneert compacte context-tekst voor de planner-prompt.
    """
    if not VAULT_SEARCH.exists() or not BRIEFINGS.exists():
        return ""
    try:
        result = subprocess.run(
            ["python3", str(VAULT_SEARCH), "--query", query,
             "--top", str(max_results), "--min-score", "1.0",
             "--vault", str(BRIEFINGS)],
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
        for note in notes[:max_results]:
            date  = note.get("date", "")[:10]
            excpt = note.get("excerpt", "")[:250].replace("\n", " ")
            parts.append(f"[{date}] {excpt}")
        return "\n".join(parts)
    except Exception:
        return ""

SELECTED  = pathlib.Path("/tmp/dagkrant-selected.json")
WIDGETS   = pathlib.Path("/tmp/dagkrant-widgets.json")
FOCUS_MD  = pathlib.Path.home() / "nieuwsstation/focus.md"
OUTPUT    = pathlib.Path("/tmp/dagkrant-plan.json")

# Topic → HTML-sectie mapping
TOPIC_TO_SECTION = {
    "nederland": "nederland",    "nederland_dk":    "nederland",
    "wereld":    "wereld",       "wereld_dk":       "wereld",
    "economie":  "financieel",   "financieel":      "financieel",
    "financieel_dk": "financieel",
    "regulatoir":    "regulatoir", "regulatoir_dk":  "regulatoir",
    "ai":        "aitech",       "ai_nieuws":       "aitech",
    "tech":      "aitech",       "ai_tech":         "aitech",
    "sport":     "sport",        "sport_dk":        "sport",
    "f1":        "sport",
    "huizen":    "huizenmarkt",  "huizenmarkt":     "huizenmarkt",
    "huizenmarkt_dk": "huizenmarkt",
    "voetbal":   "voetbal",      "voetbal_dk":      "voetbal",
}

# Standaard sectielabels — wordt aangevuld met custom topics vanuit UI
TAG_LABELS = {
    "nederland":   "Nederland",
    "wereld":      "Wereld",
    "financieel":  "Financieel",
    "aitech":      "AI & Tech",
    "sport":       "Sport",
    "voetbal":     "Voetbal",
    "regulatoir":  "Regulatoir",
    "huizenmarkt": "Huizenmarkt",
}

# Lees actieve secties + custom topics vanuit omgevingsvariabelen (gezet door main.ts)
def _load_env_config() -> tuple[list[str], list[dict]]:
    """Lees DAGKRANT_SECTIONS en DAGKRANT_CUSTOM_TOPICS env vars."""
    sections_raw = os.environ.get("DAGKRANT_SECTIONS", "")
    active = [s.strip() for s in sections_raw.split(",") if s.strip()] if sections_raw else []

    custom_raw = os.environ.get("DAGKRANT_CUSTOM_TOPICS", "[]")
    try:
        custom = json.loads(custom_raw)
    except Exception:
        custom = []

    # Voeg custom labels toe aan TAG_LABELS
    for ct in custom:
        cid = ct.get("id", "")
        clabel = ct.get("label", cid.capitalize())
        cicon = ct.get("icon", "")
        if cid and cid not in TAG_LABELS:
            TAG_LABELS[cid] = f"{cicon} {clabel}".strip() if cicon else clabel
        # Voeg ook toe aan TOPIC_TO_SECTION (custom id → zichzelf)
        if cid and cid not in TOPIC_TO_SECTION:
            TOPIC_TO_SECTION[cid] = cid
        # Voeg ook toe met _dk suffix
        if cid and f"{cid}_dk" not in TOPIC_TO_SECTION:
            TOPIC_TO_SECTION[f"{cid}_dk"] = cid

    return active, custom

ACTIVE_SECTIONS, CUSTOM_TOPICS = _load_env_config()
APPEND_MODE = os.environ.get("DAGKRANT_APPEND_MODE", "") == "true"

# Canonieke sectievolgorde (vaste + custom)
STANDARD_SECS = ["nederland", "wereld", "financieel", "sport", "aitech", "voetbal"]

def load_widgets() -> dict:
    if WIDGETS.exists():
        try:
            return json.loads(WIDGETS.read_text())
        except:
            pass
    return {
        "weer_temp": "—", "weer_icon": "🌤️",
        "aex": "—", "aex_pct": "—",
        "sp500": "—", "sp500_pct": "—",
        "brent": "—", "brent_pct": "—",
        "eurusd": "—",
        "verkeer": "A27/A28 — zie ANWB",
        "brent_trend": [80,82,85,83,88,86,84,87,90,88,85,86,84,87,89]
    }

def load_focus() -> str:
    if FOCUS_MD.exists():
        txt = FOCUS_MD.read_text()
        # Alleen de verhalen-lijst
        m = re.search(r'## Lopende verhalen\n(.*?)(?=##|\Z)', txt, re.DOTALL)
        m2 = re.search(r'## Vaste aandachtsgebieden\n(.*?)(?=##|\Z)', txt, re.DOTALL)
        focus_items = []
        if m:  focus_items += [l.strip('- ').strip() for l in m.group(1).strip().split('\n') if l.strip().startswith('-')]
        if m2: focus_items += [l.strip('- ').strip() for l in m2.group(1).strip().split('\n') if l.strip().startswith('-')]
        return ', '.join(focus_items[:8])
    return ""

def normalize_url(url: str) -> str:
    """Strip utm-params en trailing slashes voor vergelijking."""
    try:
        from urllib.parse import urlparse, urlunparse, urlencode, parse_qs
        p = urlparse(url)
        # Strip bekende tracking-params
        qs = {k: v for k, v in parse_qs(p.query).items()
              if not k.startswith(("utm_","ref","source","campaign"))}
        clean = urlunparse((p.scheme, p.netloc, p.path.rstrip('/'), p.params,
                            urlencode(qs, doseq=True), ''))
        return clean.lower()
    except:
        return url.lower().rstrip('/')

def build_article_index(data: dict) -> dict:
    """Bouw een index van alle artikelen met url als key én normalized-url lookup."""
    index = {}         # raw url → article
    norm_index = {}    # normalized url → raw url (voor fuzzy lookup)
    for topic, tdata in data.get("topics", {}).items():
        for a in tdata.get("items", []):
            key = a.get("link") or a.get("url") or a.get("title") or a.get("titel","")
            if key:
                a["_topic"] = topic
                index[key] = a
                norm_index[normalize_url(key)] = key
    index["_norm"] = norm_index  # embed norm_index in index for lookup
    return index

def lookup_article(url: str, index: dict) -> dict | None:
    """Zoek een artikel op via exacte of genormaliseerde URL."""
    norm_index = index.get("_norm", {})
    a = index.get(url)
    if a and not isinstance(a, dict) or (a and "_topic" not in a):
        a = None
    if not a:
        # Probeer normalized lookup
        raw = norm_index.get(normalize_url(url))
        if raw:
            a = index.get(raw)
    if not a:
        # Probeer partial match op path
        from urllib.parse import urlparse
        target_path = urlparse(url).path.rstrip('/')
        for raw_key, art in index.items():
            if raw_key == "_norm": continue
            from urllib.parse import urlparse as up2
            if not isinstance(art, dict): continue
            if up2(raw_key).path.rstrip('/') == target_path:
                return art
    return a

def article_summary(a: dict) -> str:
    """Geef een korte samenvatting voor de prompt."""
    title   = a.get("title") or a.get("titel") or ""
    summary = (a.get("summary") or a.get("description") or "")[:120]
    source  = a.get("source") or ""
    pub     = (a.get("published") or a.get("pub_date") or "")[:10]
    link    = a.get("link") or a.get("url") or ""
    return f'[{source}] "{title}" ({pub}) → {link}'

def build_selection_prompt(index: dict, focus: str, archive_context: str = "", vault_context: str = "") -> str:
    """Kleine prompt — Claude kiest alleen welk artikel waar hoort."""
    now = datetime.now()
    maanden = ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"]
    datum_kort = f"{now.day} {maanden[now.month-1]}"

    # Groepeer per topic
    by_topic = {}
    for key, a in index.items():
        t = a.get("_topic","overig")
        if t not in by_topic: by_topic[t] = []
        by_topic[t].append((key, a))

    lines = [f"Datum: {datum_kort}", f"Focus-onderwerpen: {focus}", ""]
    if archive_context:
        lines.append("ARCHIEF — wat eerder in De Dagkrant stond (gebruik voor kruisverband en trendherkenning):")
        lines.append(archive_context)
        lines.append("")
    if vault_context:
        lines.append("VAULT-NOTITIES — jouw bestaande werknotities over deze onderwerpen:")
        lines.append(vault_context)
        lines.append("(Gebruik deze context om regulatoire en huizenmarkt-artikelen te verrijken met professionele achtergrond)")
        lines.append("")
    lines.append("Beschikbare artikelen per sectie:")
    for topic, items in by_topic.items():
        lines.append(f"\n{topic.upper()}:")
        for key, a in items[:8]:
            lines.append(f"  • {article_summary(a)}")

    articles_text = '\n'.join(lines)

    # Bouw sectie_urls JSON fragment dynamisch op basis van actieve secties
    secs = ACTIVE_SECTIONS if ACTIVE_SECTIONS else ["nederland", "wereld", "financieel", "sport", "aitech"]
    sec_sizes = {"sport": 2}
    sectie_parts = []
    for sec in secs:
        n = sec_sizes.get(sec, 3)
        urls = ", ".join([f'"<url{i+1}>"' for i in range(n)])
        sectie_parts.append(f'    "{sec}": [{urls}]')
    sectie_urls_block = ",\n".join(sectie_parts)

    # Sectie-specifieke regels voor custom topics
    custom_rules = ""
    for ct in CUSTOM_TOPICS:
        cid = ct.get("id", "")
        clabel = ct.get("label", cid)
        keywords_ct = ct.get("keywords", [])
        kw_str = ", ".join(keywords_ct[:5]) if keywords_ct else ""
        if cid:
            kw_part = f" (zoekwoorden: {kw_str})" if kw_str else ""
            custom_rules += f"\n- {clabel}-nieuws plaatsen in sectie '{cid}'{kw_part}"

    prompt = f"""{articles_text}

Taak: selecteer voor de dagkrant de beste artikelen EN schrijf Nederlandse samenvattingen.
Output ALLEEN dit JSON (geen uitleg, geen markdown):
{{
  "breaking": ["3 korte Nederlandse headlines (max 10 woorden elk)"],
  "hero_url": "<url van het beste hero-artikel>",
  "topnieuws_urls": ["<url1>","<url2>","<url3>","<url4>","<url5>"],
  "sectie_urls": {{
{sectie_urls_block}
  }},
  "nl_content": {{
    "<url>": {{"titel": "Nederlandse titel.", "teaser": "1-2 Nederlandse zinnen.", "body": "2-3 Nederlandse zinnen met context."}}
  }},
  "kruisverband_md": "150 woorden Nederlandse analyse van verbanden tussen secties. Als er archief-context beschikbaar is: benoem expliciete trends ('dit thema speelt al X weken') en vergelijk met eerdere berichtgeving."
}}

Regels:
- Focus-onderwerpen krijgen prioriteit
- AI/Anthropic nieuws altijd in aitech
- FD-artikelen voor financieel
- Nederlandse nieuwsberichten in nederland-sectie{custom_rules}
- hero_url moet een van de topnieuws_urls zijn
- nl_content: voor ALLE geselecteerde artikelen (hero + topnieuws + secties)
- Schrijf titel, teaser en body ALTIJD in het Nederlands, ook als het artikel in het Engels is
- titel: Nederlandse vertaling/bewerking van de originele kop
- sectie_urls mogen NIET dezelfde artikelen bevatten als topnieuws_urls of hero_url
- Kies voor elke sectie PRECIES het gevraagde aantal unieke artikelen dat nog niet in topnieuws staat

Bronnenbalans (VERPLICHT):
- hero_url: ALTIJD van een Nederlandse bron (nos.nl, volkskrant.nl, fd.nl, nrc.nl, nu.nl) tenzij er absoluut geen geschikt NL artikel is
- topnieuws_urls: kies spreiding over onderwerpen (politiek, internationaal, economie); gebruik niet alleen NL bronnen zodat NL-sectie genoeg artikelen houdt
- Internationale bronnen (Guardian, BBC, Reuters) zijn welkom in topnieuws voor internationaal perspectief
- Vermijd herhaling: niet meer dan 2 artikelen over hetzelfde thema in topnieuws
- nederland-sectie krijgt 3 NL artikelen die NIET in topnieuws staan
"""
    return prompt

def fetch_og_image(url: str) -> str:
    """Haal og:image of twitter:image op van een artikel-URL."""
    if not url:
        return ""
    try:
        from urllib.request import urlopen, Request
        import html as html_mod
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120",
            "Accept": "text/html,application/xhtml+xml",
        })
        with urlopen(req, timeout=10) as r:
            chunk = r.read(65536).decode("utf-8", errors="ignore")
        # Probeer meerdere patronen
        patterns = [
            r'property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'content=["\']([^"\']+)["\'][^>]*property=["\']og:image',
            r'name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
            r'content=["\']([^"\']+)["\'][^>]*name=["\']twitter:image',
        ]
        for pat in patterns:
            m = re.search(pat, chunk, re.I)
            if m:
                img = html_mod.unescape(m.group(1).strip())
                if img.startswith("http"):
                    return img
    except Exception:
        pass
    return ""


def make_article_card(key: str, index: dict, section: str, nl_content: dict = None) -> dict | None:
    """Maak een artikel-card uit de brondata, met optionele Nederlandse tekst."""
    a = lookup_article(key, index)
    if not a:
        return None
    title   = a.get("title") or a.get("titel") or ""
    summary = a.get("summary") or a.get("description") or ""
    source  = a.get("source") or ""
    link    = a.get("link") or a.get("url") or ""
    pub     = a.get("published") or a.get("pub_date") or ""
    tag_label = TAG_LABELS.get(section, section.title())

    # Datum formatteren
    try:
        from dateutil import parser as dp
        dt = dp.parse(pub)
        from datetime import timezone
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        from datetime import datetime
        maanden = ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"]
        datum_str = f"{dt.day} {maanden[dt.month-1]}, {dt.strftime('%H:%M')} CEST"
    except:
        datum_str = pub[:16] if pub else ""

    # Nederlandse content: zoek in nl_content op url (met fuzzy fallback)
    nl = {}
    if nl_content:
        nl = nl_content.get(key) or nl_content.get(normalize_url(key)) or {}
        if not nl:
            # Fuzzy: zoek op genormaliseerde url
            norm_key = normalize_url(key)
            for nc_url, nc_val in nl_content.items():
                if normalize_url(nc_url) == norm_key:
                    nl = nc_val
                    break

    nl_titel = nl.get("titel") or title
    teaser   = nl.get("teaser") or (summary[:200] if summary else title)
    body_md  = nl.get("body") or (summary[:500] if summary else title)

    return {
        "id": re.sub(r'[^a-z0-9]+', '-', title.lower())[:30].strip('-') or f"art-{hash(key) % 10000}",
        "titel": nl_titel,
        "teaser": teaser,
        "body_md": body_md,
        "trap3_md": None,
        "bronnen": [{"naam": source, "url": link}],
        "tag": section,
        "tag_label": tag_label,
        "datum": datum_str,
    }

_DOMAIN_DISPLAY = {
    "theguardian.com": "The Guardian",
    "guardian.com":    "The Guardian",
    "nos.nl":          "NOS",
    "nrc.nl":          "NRC",
    "volkskrant.nl":   "Volkskrant",
    "fd.nl":           "FD",
    "nu.nl":           "NU.nl",
    "rtlnieuws.nl":    "RTL Nieuws",
    "ftm.nl":          "FTM",
    "bbc.co.uk":       "BBC",
    "bbc.com":         "BBC",
    "aljazeera.com":   "Al Jazeera",
    "ft.com":          "Financial Times",
    "cnbc.com":        "CNBC",
    "motorsport.com":  "Motorsport",
    "chess.com":       "Chess.com",
    "vi.nl":           "VI",
    "fcupdate.nl":     "FCUpdate",
    "techcrunch.com":  "TechCrunch",
    "theverge.com":    "The Verge",
    "anthropic.com":   "Anthropic",
    "espn.nl":         "ESPN",
    # Analytisch / academisch
    "bruegel.org":     "Bruegel",
    "cepr.org":        "VoxEU/CEPR",
    "voxeu.org":       "VoxEU/CEPR",
    # ECB naast persbericht
    "bankingsupervision.europa.eu": "ECB Bankentoezicht",
    # AI / Tech
    "simonwillison.net":  "Simon Willison",
    "interconnects.ai":   "Interconnects",
    "404media.co":        "404 Media",
    "jack-clark.net":     "Import AI",
    "lastweekinai.com":   "Last Week in AI",
    "deepmind.google":    "DeepMind",
    "arstechnica.com":    "Ars Technica",
}

def _build_bronnen_lijst(secties: dict, topnieuws: list, hero: dict) -> list[str]:
    """Verzamel alle bronnen uit geselecteerde artikelen met nette display-namen."""
    seen: dict[str, str] = {}  # raw_naam → display_naam

    def _add(art: dict) -> None:
        for b in art.get("bronnen", []):
            raw = b.get("naam", "").strip()
            if not raw:
                continue
            # Probeer display naam op te zoeken
            domain = raw.lower().removeprefix("www.")
            display = _DOMAIN_DISPLAY.get(domain, _DOMAIN_DISPLAY.get(raw.lower(), raw))
            seen[raw] = display

    all_arts = list(topnieuws) + ([hero] if hero else [])
    for sec in secties.values():
        all_arts.extend(sec.get("artikelen", []))
    for art in all_arts:
        if isinstance(art, dict):
            _add(art)

    # Sorteer: Nederlandse bronnen eerst, daarna internationaal
    nl_first = {"NOS", "NRC", "Volkskrant", "FD", "NU.nl", "RTL Nieuws", "FTM"}
    result = sorted(seen.values(), key=lambda n: (0 if n in nl_first else 1, n))
    return result


def main():
    extra_args = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""

    if not SELECTED.exists():
        print(f"[planner] FOUT: {SELECTED} niet gevonden", file=sys.stderr)
        sys.exit(1)

    data    = json.loads(SELECTED.read_text())
    widgets = load_widgets()
    focus   = load_focus()
    index   = build_article_index(data)

    if not index:
        print("[planner] Geen artikelen gevonden", file=sys.stderr)
        sys.exit(1)

    # Vault-searches parallel uitvoeren (archief + specialist vault)
    import concurrent.futures as _cf

    # Bouw vault-query alvast voor specialist secties
    specialist_secs = {"regulatoir", "huizenmarkt"}
    active_specialist = [s for s in (ACTIVE_SECTIONS or []) if s in specialist_secs]
    vault_query = ""
    if active_specialist:
        query_titles = []
        for key, a in index.items():
            if key == "_norm" or not isinstance(a, dict): continue
            sec = TOPIC_TO_SECTION.get(a.get("_topic", ""), "")
            if sec in specialist_secs:
                title = a.get("title") or a.get("titel") or ""
                if title:
                    query_titles.append(title[:60])
        vault_query = " ".join(query_titles[:6]) or " ".join(active_specialist)

    archive_context = ""
    vault_context = ""
    vault_connecties: list[str] = []

    with _cf.ThreadPoolExecutor(max_workers=2) as _pool:
        # Archief-search (alleen als focus gezet)
        _f_archive = _pool.submit(search_archive, focus, 4) if focus else None
        # Vault-search (alleen als specialist secties actief)
        _f_vault = _pool.submit(search_vault_full, vault_query, 5) if vault_query else None

        if _f_archive:
            print(f"[planner] Archief doorzoeken op: {focus[:60]}…", flush=True)
        if _f_vault:
            print(f"[planner] Vault doorzoeken voor: {', '.join(active_specialist)}…", flush=True)

        if _f_archive:
            archive_context = _f_archive.result()
            if archive_context:
                print(f"[planner] Archief: {archive_context.count(chr(10))+1} passages gevonden", flush=True)
            else:
                print("[planner] Archief: geen relevante passages", flush=True)

        if _f_vault:
            vault_context, vault_connecties = _f_vault.result()
            if vault_connecties:
                print(f"[planner] Vault: {len(vault_connecties)} connecties gevonden", flush=True)
            else:
                print("[planner] Vault: geen relevante notities", flush=True)

    prompt = build_selection_prompt(index, focus, archive_context, vault_context)
    print(f"[planner] Prompt: {len(prompt)} tekens, {len(index)} artikelen", flush=True)

    CLAUDE_TIMEOUT = 720  # 12 minuten per poging
    CLAUDE_CMD = ["claude", "-p", prompt, "--model", "claude-opus-4-7",
                  "--dangerously-skip-permissions"]

    result = None
    for poging in range(1, 3):  # max 2 pogingen
        t0 = time.time()
        print(f"[planner] Claude aanroepen (poging {poging}/2)…", flush=True)
        try:
            result = subprocess.run(
                CLAUDE_CMD,
                capture_output=True, text=True, timeout=CLAUDE_TIMEOUT,
                stdin=subprocess.DEVNULL
            )
        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            print(f"[planner] TIMEOUT na {elapsed:.0f}s (poging {poging}/2) — "
                  f"rate-limiting door actieve Claude Code sessie.",
                  file=sys.stderr, flush=True)
            if poging < 2:
                print("[planner] Wacht 60s voor herpoging…", flush=True)
                time.sleep(60)
            continue
        except Exception as e:
            print(f"[planner] Onverwachte fout: {e}", file=sys.stderr)
            sys.exit(1)

        elapsed = time.time() - t0
        print(f"[planner] Claude klaar in {elapsed:.0f}s (code {result.returncode})", flush=True)

        if result.returncode == 0:
            break  # succes

        # Code != 0: log volledig en besluit of we herprobeeren
        stderr_msg = result.stderr.strip()
        stdout_msg = result.stdout.strip()
        print(f"[planner] FOUT (code {result.returncode}, poging {poging}/2):", file=sys.stderr)
        if stderr_msg:
            print(f"  stderr: {stderr_msg[:400]}", file=sys.stderr)
        if stdout_msg and not stdout_msg.startswith("{"):
            print(f"  stdout: {stdout_msg[:400]}", file=sys.stderr)

        # Rate-limit indicatoren → herprobeeren na wacht
        rate_signals = ("rate", "429", "overloaded", "capacity", "timeout", "408")
        combined = (stderr_msg + stdout_msg).lower()
        if poging < 2 and any(s in combined for s in rate_signals):
            print("[planner] Rate-limit gedetecteerd — wacht 60s voor herpoging…", flush=True)
            time.sleep(60)
            continue
        elif poging < 2:
            print("[planner] Onbekende fout — wacht 30s voor herpoging…", flush=True)
            time.sleep(30)

    if result is None or result.returncode != 0:
        print("[planner] Alle pogingen mislukt. Generatie afgebroken.", file=sys.stderr, flush=True)
        sys.exit(1)

    # Parseer JSON uit stdout
    out = result.stdout.strip()
    if out.startswith("```"):
        out = re.sub(r'^```[a-z]*\n?', '', out).rstrip('`').strip()
    m = re.search(r'\{[\s\S]+\}', out)
    if not m:
        print(f"[planner] Geen JSON in output: {out[:300]}", file=sys.stderr)
        sys.exit(1)
    try:
        selection = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"[planner] JSON fout: {e}\nOutput: {out[:500]}", file=sys.stderr)
        sys.exit(1)

    # Bouw het volledige plan uit de selectie + brondata
    now = datetime.now()
    maanden = ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"]
    dagen   = ["maandag","dinsdag","woensdag","donderdag","vrijdag","zaterdag","zondag"]
    datum_lang = f"{dagen[now.weekday()]} {now.day} {maanden[now.month-1]} {now.year}"
    datum_iso  = now.strftime("%Y-%m-%d")
    datum_kort = f"{now.day} {maanden[now.month-1]}"

    w = widgets

    nl_content = selection.get("nl_content", {})

    # Hero
    hero_url  = selection.get("hero_url", "")
    hero_a    = lookup_article(hero_url, index) or {}
    hero_link = hero_a.get("link") or hero_a.get("url") or hero_url
    hero_sec  = TOPIC_TO_SECTION.get(hero_a.get("_topic","wereld"), "wereld")
    hero_card = make_article_card(hero_url, index, hero_sec, nl_content)
    if hero_card:
        nl_hero   = nl_content.get(hero_url) or nl_content.get(normalize_url(hero_url)) or {}
        hero_card["lead"]       = nl_hero.get("teaser") or hero_card["teaser"]
        hero_card["foto_url"]   = fetch_og_image(hero_link)
        hero_card["foto_credit"] = "Bron: " + hero_card["bronnen"][0].get("naam","") if hero_card.get("bronnen") else ""
        hero_card["id"]         = "hero"

    # Bijhouden welke URLs al gebruikt zijn (voor deduplicatie)
    used_urls: set = set()
    if hero_url:
        used_urls.add(normalize_url(hero_url))

    # Topnieuws (hero-url wordt niet opgenomen als top-artikel)
    topnieuws = []
    for i, url in enumerate(selection.get("topnieuws_urls", [])[:6]):
        n = normalize_url(url)
        if n in used_urls:
            continue
        a = lookup_article(url, index) or {}
        topic   = a.get("_topic", "wereld")
        section = TOPIC_TO_SECTION.get(topic, "wereld")
        card = make_article_card(url, index, section, nl_content)
        if card:
            used_urls.add(n)
            card["id"] = f"top{len(topnieuws)+1}"
            topnieuws.append(card)
        if len(topnieuws) >= 5:
            break

    # Secties — met fallback als Claude's URLs niet matchen
    secties = {}
    active_secs = ACTIVE_SECTIONS if ACTIVE_SECTIONS else ["nederland", "wereld", "financieel", "sport", "aitech"]

    # Bouw fallback-pool per sectie uit de brondata
    fallback: dict[str, list] = {s: [] for s in active_secs}
    for key, a in index.items():
        if key == "_norm" or not isinstance(a, dict): continue
        topic = a.get("_topic","overig")
        sec = TOPIC_TO_SECTION.get(topic, None)
        if sec and sec in fallback:
            fallback[sec].append(key)

    for section in active_secs:
        urls = selection.get("sectie_urls", {}).get(section, [])
        artikelen = []
        for url in urls[:5]:
            n = normalize_url(url)
            if n in used_urls:
                continue
            card = make_article_card(url, index, section, nl_content)
            if card:
                used_urls.add(n)
                artikelen.append(card)
        # Fallback: vul aan vanuit brondata als minder dan 3 artikelen
        if len(artikelen) < 3:
            for fb_url in fallback.get(section, []):
                n = normalize_url(fb_url)
                if n in used_urls: continue
                card = make_article_card(fb_url, index, section, nl_content)
                if card:
                    used_urls.add(n)
                    artikelen.append(card)
                if len(artikelen) >= 3: break
        secties[section] = {"artikelen": artikelen[:4]}

    # Foto's parallel ophalen voor topnieuws + secties (max 30s totaal)
    import concurrent.futures
    all_cards: list[dict] = list(topnieuws)
    for sec_data in secties.values():
        all_cards.extend(sec_data.get("artikelen", []))

    def _fetch_card_img(card: dict) -> None:
        url = (card.get("bronnen") or [{}])[0].get("url", "")
        if url and not card.get("foto_url"):
            card["foto_url"] = fetch_og_image(url)

    if all_cards:
        print(f"[planner] Foto's ophalen voor {len(all_cards)} kaarten...", flush=True)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futures = {pool.submit(_fetch_card_img, c): c for c in all_cards}
                concurrent.futures.wait(futures, timeout=30)
        except Exception as e:
            print(f"[planner] Foto-fetch waarschuwing: {e}", flush=True)
        n_photos = sum(1 for c in all_cards if c.get("foto_url"))
        print(f"[planner] {n_photos}/{len(all_cards)} foto's gevonden", flush=True)

    # Koersen in financieel
    if "financieel" in secties:
        secties["financieel"]["koersen"] = [
            {"naam": "AEX",     "waarde": w.get("aex","—"),    "delta": w.get("aex_pct","—")},
            {"naam": "S&P 500", "waarde": w.get("sp500","—"),  "delta": w.get("sp500_pct","—")},
            {"naam": "Brent",   "waarde": f"${w.get('brent','—')}", "delta": w.get("brent_pct","—")},
            {"naam": "EUR/USD", "waarde": w.get("eurusd","—"), "delta": "—"},
        ]

    plan = {
        "datum":            datum_lang,
        "datum_iso":        datum_iso,
        "tijd":             now.strftime("%H:%M"),
        "tijdzone":         "CEST",
        "widgets": {
            "weer_temp":   w.get("weer_temp","—"),
            "weer_icon":   w.get("weer_icon","🌤️"),
            "aex":         w.get("aex","—"),
            "aex_pct":     w.get("aex_pct","—"),
            "sp500":       w.get("sp500","—"),
            "sp500_pct":   w.get("sp500_pct","—"),
            "brent":       w.get("brent","—"),
            "brent_pct":   w.get("brent_pct","—"),
            "eurusd":      w.get("eurusd","—"),
            "verkeer":     w.get("verkeer","A27/A28 — zie ANWB"),
            "brent_trend": w.get("brent_trend", [80,82,85,83,88,86,84,87,90,88,85,86,84,87,89]),
        },
        "breaking":         selection.get("breaking", [])[:5],
        "hero":             hero_card or {},
        "topnieuws":        topnieuws,
        "secties":          secties,
        "kruisverband_md":  selection.get("kruisverband_md", ""),
        "vault_connecties": vault_connecties,
        "bronnen_lijst":    _build_bronnen_lijst(secties, topnieuws, hero_card),
    }

    OUTPUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    sz = OUTPUT.stat().st_size // 1024
    print(f"[planner] Plan geschreven: {OUTPUT} ({sz}KB, {len(topnieuws)} topnieuws, {sum(len(s['artikelen']) for s in secties.values())} sectie-artikelen)")

if __name__ == "__main__":
    main()
