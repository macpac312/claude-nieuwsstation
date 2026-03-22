#!/usr/bin/env python3
"""Briefing Renderer v3 — exact conform mockup-daily-briefing-tabs-v3.jsx

Ingeklapt: titel + samenvatting + impact callout (korte versie)
Uitgeklapt: bronnen pills + uitgebreide samenvatting + diepe analyse +
            actiepunten + vault links + actieknoppen

Publish-compatible: pure HTML in markdown met <details>/<summary>.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

VAULT_PATH = Path.home() / "Documents" / "WorkMvMOBS"
BRIEFINGS_PATH = VAULT_PATH / "Briefings"

# Zuiver neutrale kleuren — wit/grijs, geen blauwe tint
C = {
    "base": "#1e1e2e", "mantle": "#181825", "crust": "#11111b",
    "s0": "#313244", "s1": "#45475a", "s2": "#585b70",
    "o0": "#6c7086", "o1": "#8e8e9e",
    "t": "#e0e0e0", "st0": "#b0b0b0", "st1": "#c8c8c8",
    "gr": "#a6e3a1", "yl": "#f9e2af",
    "pe": "#fab387", "rd": "#f38ba8",
}

# Topic border/badge kleur: allemaal surface-grijs, geen kleuren
TOPIC = {
    "regulatoir": {"icon": "📋", "c": C["s2"], "label": "Regulatoir"},
    "huizenmarkt": {"icon": "🏠", "c": C["s2"], "label": "Huizenmarkt"},
    "financieel": {"icon": "📊", "c": C["s2"], "label": "Financieel"},
    "tech":        {"icon": "⚡", "c": C["s2"], "label": "Tech & AI"},
    "sport":       {"icon": "⚽", "c": C["s2"], "label": "Sport"},
    "ai_nieuws":   {"icon": "🤖", "c": C["s2"], "label": "AI Nieuws"},
}

TLABEL = {"article": "Artikel", "paper": "Paper", "data": "Dataset", "regulation": "Regulering", "news_api": "Nieuws"}
TCOLOR = {"article": C["st0"], "paper": C["st0"], "data": C["st0"], "regulation": C["st0"], "news_api": C["st0"]}


def _dom(url):
    try: return urlparse(url).netloc.replace("www.", "")
    except: return ""


def _ago(d):
    try:
        m = int((datetime.now(timezone.utc) - datetime.fromisoformat(d)).total_seconds() / 60)
        if m < 60: return f"{m} min"
        if m < 1440: return f"{m // 60} uur"
        return f"{m // 1440}d"
    except: return ""


def _esc(s):
    """Escape HTML entities."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def article(a, tc, tid, idx, hero=False):
    """Render één artikel als Obsidian callout met +/- toggle.
    Ingeklapt: kop + 2 regels samenvatting + impact callout
    Uitgeklapt: afbeelding + bronnen + uitgebreide samenvatting + impact analyse + knoppen
    """
    title = a.get("title", "")
    summ = a.get("summary", "")
    link = a.get("link", "")
    src = a.get("source_name", "")
    st = a.get("source_type", "article")
    img = a.get("image_url", "")
    dom = _dom(link)
    bl = TLABEL.get(st, "Artikel")

    from urllib.parse import quote
    is_translated = a.get("translated", False)
    title_orig = a.get("title_original", "") if is_translated else ""
    summ_orig = a.get("summary_original", "") if is_translated else ""

    save_title = title.replace('"', '').replace("'", "")
    save_content = f"---\ndate: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\nsource: {src}\nurl: {link}\ntype: clipping\n---\n\n# {save_title}\n\nBron: [{src}]({link})\n\n{summ}"
    save_url = f"obsidian://new?vault=WorkMvMOBS&name=Clippings/{quote(save_title, safe='')}&content={quote(save_content, safe='')}"

    # Korte samenvatting (max 2 regels)
    short_summ = summ[:180] + "..." if len(summ) > 180 else summ

    # Korte impact (max 2 zinnen)
    sentences = summ.split(". ")
    impact_short = ". ".join(sentences[:2])
    if len(sentences) > 2:
        impact_short += "."
    impact_short = impact_short[:200] + "..." if len(impact_short) > 200 else impact_short

    # Prefix alle regels met > voor callout
    def q(text, prefix="> "):
        return "\n".join(prefix + line for line in text.split("\n"))

    # Afbeelding markdown
    img_md = f"> ![{title}]({img})\n>\n" if img else ""

    # Origineel (als vertaald)
    orig_md = ""
    if is_translated and summ_orig:
        orig_md = f""">
> > [!quote]- 📄 Toon origineel (Engels)
> > **{title_orig}**
> > {summ_orig}"""

    md = f"""
> [!note]+ **{title}**
> {short_summ}
>
> > [!tip] 🔍 Impact analyse
> > {impact_short}
>
> ---
>
{img_md}> **BRONNEN**
> `{bl}` [{src}: {title[:50]}{"..." if len(title) > 50 else ""}]({link}) · `{dom}` ↗
>
> **UITGEBREIDE SAMENVATTING**
> {summ}
{orig_md}
>
> **IMPACT ANALYSE**
> *Diepe impact analyse wordt gegenereerd bij gebruik van /briefing.*
>
> [💾 Opslaan]({save_url}) · [🔍 Diepere analyse]({link}) · 🎙️ Podcast paper · 📋 Kopieer

"""
    return md


def _tab_bar(twi, active_tid, ds):
    """Render de tab-balk als markdown links."""
    tabs = []
    for tid, _ in twi:
        m = TOPIC.get(tid, {"icon": "📰", "c": C["s2"], "label": tid})
        if tid == active_tid:
            tabs.append(f"**{m['icon']} {m['label']}**")
        else:
            tabs.append(f"[[Briefings/{ds}/{m['label']}|{m['icon']} {m['label']}]]")
    return " · ".join(tabs) + "\n"


def render_topic_page(tid, td, twi, ds, dnl, tot, vault_data=None):
    """Render een aparte pagina voor één topic."""
    items = td.get("items", [])
    m = TOPIC.get(tid, {"icon": "📰", "c": C["s2"], "label": tid})

    md = f"""---
date: {ds}
type: briefing-topic
topic: {tid}
bronnen: {len(items)}
cssclasses:
  - nieuwsstation
  - ns-briefing
---

{_tab_bar(twi, tid, ds)}

# {m["icon"]} {m["label"]} — {dnl}

*{len(items)} artikelen · {tot} bronnen totaal*

"""

    for idx, item in enumerate(items[:10]):
        md += article(item, m["c"], tid, idx)

    # Vault notes
    if vault_data and vault_data.get("notes"):
        md += '\n---\n\n## Gerelateerde vault notes\n\n'
        for n in vault_data["notes"][:6]:
            md += f'[[{n["title"]}]] · '
        md += '\n\n'

    return md


def render_index_page(twi, ds, dnl, tot, vault_data=None):
    """Render de hoofdpagina met overzicht en links naar topic tabs."""
    tids = [t[0] for t in twi]

    md = f"""---
date: {ds}
type: briefing
topics: [{", ".join(tids)}]
podcast: true
bronnen: {tot}
cssclasses:
  - nieuwsstation
  - ns-briefing
---

{_tab_bar(twi, "", ds)}

# 📡 Ochtend Briefing — {dnl}

<div style="font-size:12px;color:{C["o0"]};margin:4px 0 16px;">{tot} bronnen · {len(twi)} topics</div>

> [!podcast] 🎙️ Podcast
> ![[Briefings/podcast/audio/{ds}.mp3]]
> Upload podcast paper naar NotebookLM voor Audio Overview

---

"""

    # Topic overzicht met links
    for tid, td in twi:
        m = TOPIC.get(tid, {"icon": "📰", "c": C["s2"], "label": tid})
        count = len(td.get("items", []))
        first_titles = [it.get("title", "")[:60] for it in td.get("items", [])[:3]]

        md += f'### [[Briefings/{ds}/{m["label"]}|{m["icon"]} {m["label"]}]] — {count} artikelen\n\n'
        for t in first_titles:
            md += f'- {t}\n'
        md += '\n'

    # Kruisverband
    md += """---

## 🔗 Kruisverband-analyse

> [!abstract] Kruisverbanden
> *Kruisverband-analyse wordt gegenereerd bij gebruik van /briefing — Claude legt dan verbanden tussen topics.*

"""

    # Vault notes
    if vault_data and vault_data.get("notes"):
        md += '## Gerelateerde vault notes\n\n'
        for n in vault_data["notes"][:8]:
            md += f'[[{n["title"]}]] · '
        md += '\n\n'

    # Bronnen
    md += '## Bronnen\n\n'
    srcs = set()
    for _, td in twi:
        for it in td.get("items", []):
            srcs.add((it.get("source_name", ""), _dom(it.get("link", "")), it.get("source_type", "")))
    for i, (n, d, st) in enumerate(sorted(srcs), 1):
        md += f'{i}. **{n}** — `{d}` ({TLABEL.get(st, st)})\n'

    return md


def render_briefing(rss_data, vault_data=None, focus=None):
    """Genereer aparte bestanden per topic + index pagina.

    Returns: dict met {filename: markdown_content}
    """
    now = datetime.now(timezone.utc)
    ds = now.strftime("%Y-%m-%d")
    mnl = ["januari", "februari", "maart", "april", "mei", "juni",
           "juli", "augustus", "september", "oktober", "november", "december"]
    dnl = f"{now.day} {mnl[now.month - 1]} {now.year}"
    tot = rss_data.get("total_items", 0)

    twi = [(tid, td) for tid, td in rss_data.get("topics", {}).items() if td.get("items")]

    pages = {}

    # Index pagina
    pages[f"Briefings/{ds}/{ds}.md"] = render_index_page(twi, ds, dnl, tot, vault_data)

    # Per topic een aparte pagina
    for tid, td in twi:
        m = TOPIC.get(tid, {"icon": "📰", "c": C["s2"], "label": tid})
        pages[f"Briefings/{ds}/{m['label']}.md"] = render_topic_page(
            tid, td, twi, ds, dnl, tot, vault_data
        )

    return pages


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rss", required=True)
    p.add_argument("--vault")
    p.add_argument("--focus")
    p.add_argument("--output", help="Base output directory (default: vault Briefings/)")
    a = p.parse_args()

    rss = json.loads(Path(a.rss).read_text())
    vault = json.loads(Path(a.vault).read_text()) if a.vault else None
    pages = render_briefing(rss, vault, a.focus)

    base = Path(a.output) if a.output else VAULT_PATH
    for rel_path, content in pages.items():
        out = base / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)
        print(f"[OK] {rel_path}", file=sys.stderr)

    print(f"\n[OK] {len(pages)} bestanden gegenereerd", file=sys.stderr)


if __name__ == "__main__":
    main()
