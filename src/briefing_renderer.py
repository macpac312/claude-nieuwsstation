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


def article(a, tc, tid, idx):
    """Render één artikel — exact conform mockup."""
    title = _esc(a.get("title", ""))
    summ = _esc(a.get("summary", ""))
    link = a.get("link", "")
    src = _esc(a.get("source_name", ""))
    st = a.get("source_type", "article")
    pub = a.get("published", "")
    dom = _dom(link)
    ago = _ago(pub) if pub else ""
    bc = TCOLOR.get(st, C["st0"])
    bl = TLABEL.get(st, "Artikel")

    # Korte samenvatting voor callout (max 2 zinnen)
    sentences = summ.split(". ")
    short_callout = ". ".join(sentences[:2])
    if len(sentences) > 2:
        short_callout += "."

    from urllib.parse import quote

    is_translated = a.get("translated", False)
    title_orig = _esc(a.get("title_original", "")) if is_translated else ""
    summ_orig = _esc(a.get("summary_original", "")) if is_translated else ""

    # Bewaar: obsidian URI om nieuwe note aan te maken in Clippings map
    save_title = title.replace('"', '').replace("'", "").replace("&amp;", "&")
    save_content = f"---\ndate: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\nsource: {src}\nurl: {link}\ntype: clipping\n---\n\n# {save_title}\n\nBron: [{src}]({link})\n\n{summ}"
    save_url = f"obsidian://new?vault=WorkMvMOBS&name=Clippings/{quote(save_title, safe='')}&content={quote(save_content, safe='')}"

    # Vertaal badge
    translate_badge = ""
    if is_translated:
        translate_badge = f'<span style="font-size:9px;padding:2px 6px;border-radius:3px;background:{C["s2"]}18;color:{C["st0"]};border:1px solid {C["s2"]}22;" title="Automatisch vertaald uit het Engels">🌐 NL</span>'

    # ─── INGEKLAPT ───
    collapsed = f'''<div style="flex:1;">
<div style="font-size:15px;font-weight:600;color:{C["t"]};line-height:1.4;margin-bottom:6px;">{title}</div>
<div style="font-size:13px;color:{C["st0"]};line-height:1.6;">{summ[:180]}{"..." if len(summ)>180 else ""}</div>
<div style="display:flex;align-items:center;gap:6px;margin-top:8px;">
<span style="font-size:10px;padding:2px 8px;border-radius:4px;background:{C["s1"]}44;color:{C["st0"]};font-weight:600;">{bl}</span>
<span style="font-size:11px;color:{C["o1"]};">{src}</span>
{f'<span style="font-size:10px;color:{C["s2"]};">{ago}</span>' if ago else ''}
{translate_badge}
<span style="flex:1;"></span>
<a href="{save_url}" style="font-size:10px;padding:3px 8px;border-radius:4px;background:{C["s2"]}15;color:{C["st0"]};text-decoration:none;border:1px solid {C["s2"]}25;" title="Bewaar als note in Obsidian vault">💾 Bewaar</a>
</div>
</div>
<div style="width:24px;height:24px;border-radius:6px;background:{C["s1"]}44;color:{C["o0"]};display:flex;align-items:center;justify-content:center;font-size:12px;flex-shrink:0;margin-top:2px;">▾</div>'''

    # Impact callout (alleen zichtbaar als ingeklapt — verborgen bij open via CSS)
    callout = f'''<div class="ns-callout-collapsed" style="padding:0 16px 14px;">
<div style="border-left:3px solid {C["s2"]};background:{C["s2"]}08;padding:10px 14px;border-radius:0 8px 8px 0;">
<div style="font-size:12px;font-weight:600;color:{C["st0"]};margin-bottom:4px;">🔍 Impact analyse</div>
<div style="font-size:12px;color:{C["st1"]};line-height:1.6;">{short_callout}</div>
</div>
</div>'''

    # ─── UITGEKLAPT ───
    # Bronnen pill — neutrale kleuren, accent alleen op badge border
    src_pill = f'''<a href="{link}" target="_blank" style="display:flex;align-items:center;gap:8px;padding:8px 12px;border-radius:8px;background:{C["s0"]}66;border:1px solid {C["s0"]};text-decoration:none;">
<span style="font-size:10px;padding:1px 6px;border-radius:3px;background:{C["s1"]}44;color:{C["st0"]};font-weight:600;border:1px solid {C["s1"]};">{bl}</span>
<span style="font-size:12px;color:{C["t"]};font-weight:500;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{src}: {title[:55]}{"..." if len(title)>55 else ""}</span>
<span style="font-size:10px;color:{C["o0"]};font-family:monospace;">{dom}</span>
<span style="color:{C["o0"]};">↗</span>
</a>'''

    # Uitgebreide samenvatting (met origineel als vertaald)
    orig_block = ""
    if is_translated and summ_orig:
        orig_block = f'''
<details style="margin-top:8px;">
<summary style="font-size:10px;color:{C["o0"]};cursor:pointer;list-style:none;">📄 Toon origineel (Engels)</summary>
<div style="font-size:12px;color:{C["o1"]};line-height:1.6;padding:10px 14px;margin-top:6px;background:{C["s0"]}44;border-radius:8px;border-left:2px solid {C["s1"]};">
<div style="font-size:11px;font-weight:600;color:{C["o0"]};margin-bottom:4px;">{title_orig}</div>
{summ_orig}
</div>
</details>'''

    ext_summ = f'''<div style="font-size:13px;color:{C["st1"]};line-height:1.8;padding:14px 16px;background:{C["mantle"]};border-radius:10px;border:1px solid {C["s0"]};">
{summ}
{orig_block}
</div>'''

    # Diepe analyse — accent border
    deep = f'''<div style="border-left:3px solid {C["s2"]};background:{C["s2"]}08;padding:14px 16px;border-radius:0 10px 10px 0;">
<div style="font-size:13px;color:{C["st1"]};line-height:1.8;">
<em style="color:{C["o0"]};">Diepe impact analyse wordt gegenereerd bij gebruik van /briefing — Claude analyseert dan de relevantie voor Rabobank model validatie.</em>
</div>
</div>'''

    # Actieknoppen — neutrale kleuren, accent als hover-hint
    btn_s = f"padding:7px 14px;border-radius:8px;font-size:12px;font-weight:500;display:inline-flex;align-items:center;gap:6px;"
    btns = f'''<div style="display:flex;gap:8px;flex-wrap:wrap;padding-top:4px;">
<a href="{save_url}" style="{btn_s}background:{C["s2"]}12;border:1px solid {C["s2"]}25;color:{C["st0"]};text-decoration:none;">💾 Opslaan als note in vault</a>
<span style="{btn_s}background:{C["s1"]}22;border:1px solid {C["s1"]};color:{C["st0"]};cursor:pointer;">🔍 Diepere analyse genereren</span>
<span style="{btn_s}background:{C["s1"]}22;border:1px solid {C["s1"]};color:{C["st0"]};cursor:pointer;">🎙️ Podcast paper maken</span>
<span style="{btn_s}background:{C["s1"]}22;border:1px solid {C["s1"]};color:{C["o1"]};cursor:pointer;font-size:11px;">📋 Kopieer samenvatting</span>
</div>'''

    return f'''
<details class="ns-article" style="border-radius:12px;overflow:hidden;border:1px solid {C["s0"]};margin-bottom:8px;">
<summary style="padding:14px 16px;cursor:pointer;list-style:none;display:flex;align-items:start;gap:12px;">
{collapsed}
</summary>

{callout}

<div style="padding:0 16px 16px;">
<div style="height:1px;background:{C["s1"]};margin:0 0 16px;"></div>

<div style="margin-bottom:16px;">
<div style="font-size:11px;font-weight:600;color:{C["o1"]};text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px;">Bronnen</div>
{src_pill}
</div>

<div style="margin-bottom:16px;">
<div style="font-size:11px;font-weight:600;color:{C["o1"]};text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px;">Uitgebreide samenvatting</div>
{ext_summ}
</div>

<div style="margin-bottom:16px;">
<div style="font-size:11px;font-weight:600;color:{C["o1"]};text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px;">Impact analyse</div>
{deep}
</div>

{btns}
</div>
</details>'''


def render_briefing(rss_data, vault_data=None, focus=None):
    now = datetime.now(timezone.utc)
    ds = now.strftime("%Y-%m-%d")
    mnl = ["januari","februari","maart","april","mei","juni","juli","augustus","september","oktober","november","december"]
    dnl = f"{now.day} {mnl[now.month-1]} {now.year}"
    tot = rss_data.get("total_items", 0)

    twi = [(tid, td) for tid, td in rss_data.get("topics", {}).items() if td.get("items")]
    tids = [t[0] for t in twi]

    # Frontmatter
    md = f"""---
date: {ds}
type: briefing
topics: [{", ".join(tids)}]
podcast: true
bronnen: {tot}
generated: {now.isoformat()}
cssclasses:
  - nieuwsstation
  - ns-briefing
---

# 📡 Ochtend Briefing — {dnl}

<div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0;">
"""
    for tid in tids:
        m = TOPIC.get(tid, {"icon":"📰","c":C["s2"],"label":tid})
        md += f'<span style="font-size:11px;padding:3px 10px;border-radius:6px;background:{C["s1"]}33;color:{C["st0"]};font-weight:500;">{m["icon"]} {m["label"]}</span>\n'

    md += f'''</div>
<div style="font-size:12px;color:{C["o0"]};margin-top:4px;">{tot} bronnen · {now.strftime("%H:%M")} CET</div>

> [!podcast] 🎙️ Podcast
> ![[Briefings/podcast/audio/{ds}.mp3]]
> Upload podcast paper naar NotebookLM voor Audio Overview

---

'''

    # Tab bar — accent voor active tab, subtiel voor rest
    tabs = ""
    for i, (tid, _) in enumerate(twi):
        m = TOPIC.get(tid, {"icon":"📰","c":C["s2"],"label":tid})
        active = i == 0
        s = f"color:{C['t']};background:{C['base']};border-top:2px solid {C['s2']};font-weight:500;" if active else f"color:{C['o0']};"
        tabs += f'<a href="#{tid}" style="padding:6px 14px;font-size:12px;{s}text-decoration:none;border-radius:6px 6px 0 0;display:inline-flex;align-items:center;gap:4px;">{m["icon"]} {m["label"]}</a>'

    md += f'''<div style="display:flex;background:{C["crust"]};border-bottom:1px solid {C["s0"]};padding:0 8px;overflow-x:auto;border-radius:8px 8px 0 0;margin-bottom:20px;">
{tabs}
</div>

'''

    # Per topic
    for tid, td in twi:
        items = td.get("items", [])
        m = TOPIC.get(tid, {"icon":"📰","c":C["t"],"label":tid})

        md += f'<div id="{tid}">\n\n'
        md += f'## {m["icon"]} {m["label"]}\n\n'

        for idx, item in enumerate(items[:8]):
            md += article(item, m["c"], tid, idx)

        md += '\n</div>\n\n---\n\n'

    # Kruisverband
    md += f'''## 🔗 Kruisverband-analyse

<div style="background:{C["mantle"]};border-radius:12px;padding:20px 24px;font-size:13px;color:{C["st1"]};line-height:1.7;border:1px solid {C["s0"]}44;border-left:3px solid {C["s2"]}44;">

*Kruisverband-analyse wordt gegenereerd bij gebruik van /briefing — Claude legt dan verbanden tussen topics.*

</div>

'''

    # Vault notes
    if vault_data and vault_data.get("notes"):
        md += '## Gerelateerde vault notes\n\n<div style="display:flex;flex-wrap:wrap;gap:6px;margin:12px 0;">\n'
        for n in vault_data["notes"][:8]:
            md += f'<span style="font-size:11px;padding:3px 8px;border-radius:4px;background:{C["s2"]}12;color:{C["st0"]};border:1px solid {C["s2"]}22;display:inline-block;">[[{n["title"]}]]</span>\n'
        md += '</div>\n\n'

    # Bronnen
    md += '## Bronnen\n\n'
    srcs = set()
    for _, td in twi:
        for it in td.get("items", []):
            srcs.add((it.get("source_name",""), _dom(it.get("link","")), it.get("source_type","")))
    for i, (n, d, st) in enumerate(sorted(srcs), 1):
        md += f'{i}. **{n}** — `{d}` ({TLABEL.get(st, st)})\n'

    return md


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rss", required=True)
    p.add_argument("--vault")
    p.add_argument("--focus")
    p.add_argument("--output")
    a = p.parse_args()

    rss = json.loads(Path(a.rss).read_text())
    vault = json.loads(Path(a.vault).read_text()) if a.vault else None
    md = render_briefing(rss, vault, a.focus)

    ds = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = Path(a.output) if a.output else BRIEFINGS_PATH / f"{ds}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    print(f"[OK] Briefing: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
