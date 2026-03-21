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

C = {
    "base": "#1e1e2e", "mantle": "#181825", "crust": "#11111b",
    "s0": "#313244", "s1": "#45475a", "s2": "#585b70",
    "o0": "#6c7086", "o1": "#7f849c",
    "t": "#cdd6f4", "st0": "#a6adc8", "st1": "#bac2de",
    "lav": "#b4befe", "bl": "#89b4fa", "sap": "#74c7ec",
    "tl": "#94e2d5", "gr": "#a6e3a1", "yl": "#f9e2af",
    "pe": "#fab387", "rd": "#f38ba8", "mv": "#cba6f7",
}

TOPIC = {
    "regulatoir": {"icon": "📋", "c": C["bl"], "label": "Regulatoir"},
    "huizenmarkt": {"icon": "🏠", "c": C["gr"], "label": "Huizenmarkt"},
    "financieel": {"icon": "📊", "c": C["pe"], "label": "Financieel"},
    "tech":        {"icon": "⚡", "c": C["mv"], "label": "Tech & AI"},
    "sport":       {"icon": "⚽", "c": C["gr"], "label": "Sport"},
    "ai_nieuws":   {"icon": "🤖", "c": C["mv"], "label": "AI Nieuws"},
}

TLABEL = {"article": "Artikel", "paper": "Paper", "data": "Dataset", "regulation": "Regulering", "news_api": "Nieuws"}
TCOLOR = {"article": C["sap"], "paper": C["mv"], "data": C["gr"], "regulation": C["bl"], "news_api": C["pe"]}


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
    bc = TCOLOR.get(st, C["sap"])
    bl = TLABEL.get(st, "Artikel")

    # Korte samenvatting voor callout (max 2 zinnen)
    sentences = summ.split(". ")
    short_callout = ". ".join(sentences[:2])
    if len(sentences) > 2:
        short_callout += "."

    from urllib.parse import quote

    # Bewaar: obsidian URI om nieuwe note aan te maken in Clippings map
    save_title = title.replace('"', '').replace("'", "").replace("&amp;", "&")
    save_content = f"---\ndate: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\nsource: {src}\nurl: {link}\ntype: clipping\n---\n\n# {save_title}\n\nBron: [{src}]({link})\n\n{summ}"
    save_url = f"obsidian://new?vault=WorkMvMOBS&name=Clippings/{quote(save_title, safe='')}&content={quote(save_content, safe='')}"

    # Vertaal: obsidian URI die een Claude prompt opent om dit artikel te vertalen
    translate_prompt = f"Vertaal het volgende nieuwsartikel naar het Nederlands. Behoud de structuur.\n\nTitel: {save_title}\n\nInhoud: {summ}\n\nBron: {link}"
    translate_url = f"obsidian://new?vault=WorkMvMOBS&name=Vertalingen/{quote(save_title, safe='')}&content={quote(translate_prompt, safe='')}"

    # ─── INGEKLAPT ───
    collapsed = f'''<div style="flex:1;">
<div style="font-size:15px;font-weight:600;color:{C["t"]};line-height:1.4;margin-bottom:6px;">{title}</div>
<div style="font-size:13px;color:{C["st0"]};line-height:1.6;">{summ[:180]}{"..." if len(summ)>180 else ""}</div>
<div style="display:flex;align-items:center;gap:6px;margin-top:8px;">
<span style="font-size:10px;padding:2px 8px;border-radius:4px;background:{bc}22;color:{bc};font-weight:600;">{bl}</span>
<span style="font-size:11px;color:{C["o1"]};">{src}</span>
{f'<span style="font-size:10px;color:{C["s2"]};">{ago}</span>' if ago else ''}
<span style="flex:1;"></span>
<a href="{save_url}" style="font-size:10px;padding:3px 8px;border-radius:4px;background:{C["tl"]}15;color:{C["tl"]};text-decoration:none;border:1px solid {C["tl"]}22;" title="Bewaar als note in Obsidian vault">💾 Bewaar</a>
<a href="{translate_url}" target="_blank" style="font-size:10px;padding:3px 8px;border-radius:4px;background:{C["sap"]}15;color:{C["sap"]};text-decoration:none;border:1px solid {C["sap"]}22;" title="Vertaal naar Nederlands via Google Translate">🌐 Vertaal NL</a>
</div>
</div>
<div style="width:24px;height:24px;border-radius:6px;background:{tc}18;color:{tc};display:flex;align-items:center;justify-content:center;font-size:12px;flex-shrink:0;margin-top:2px;">▾</div>'''

    # Impact callout (alleen zichtbaar als ingeklapt — verborgen bij open via CSS)
    callout = f'''<div class="ns-callout-collapsed" style="padding:0 16px 14px;">
<div style="border-left:3px solid {tc};background:{tc}0a;padding:10px 14px;border-radius:0 8px 8px 0;">
<div style="font-size:12px;font-weight:600;color:{tc};margin-bottom:4px;">🔍 Impact analyse</div>
<div style="font-size:12px;color:{C["st1"]};line-height:1.6;">{short_callout}</div>
</div>
</div>'''

    # ─── UITGEKLAPT ───
    # Bronnen pill
    src_pill = f'''<a href="{link}" target="_blank" style="display:flex;align-items:center;gap:8px;padding:8px 12px;border-radius:8px;background:{C["s0"]}66;border:1px solid {C["s0"]};text-decoration:none;">
<span style="font-size:10px;padding:1px 6px;border-radius:3px;background:{bc}22;color:{bc};font-weight:600;border:1px solid {bc}33;">{bl}</span>
<span style="font-size:12px;color:{C["t"]};font-weight:500;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{src}: {title[:55]}{"..." if len(title)>55 else ""}</span>
<span style="font-size:10px;color:{C["o0"]};font-family:monospace;">{dom}</span>
<span style="color:{C["o0"]};">↗</span>
</a>'''

    # Uitgebreide samenvatting
    ext_summ = f'''<div style="font-size:13px;color:{C["st1"]};line-height:1.8;padding:14px 16px;background:{C["mantle"]};border-radius:10px;border:1px solid {C["s0"]};">
{summ}
</div>'''

    # Diepe analyse
    deep = f'''<div style="border-left:3px solid {tc};background:{tc}0a;padding:14px 16px;border-radius:0 10px 10px 0;">
<div style="font-size:13px;color:{C["st1"]};line-height:1.8;">
<em style="color:{C["o0"]};">Diepe impact analyse wordt gegenereerd bij gebruik van /briefing — Claude analyseert dan de relevantie voor Rabobank model validatie.</em>
</div>
</div>'''

    # Actieknoppen
    btns = f'''<div style="display:flex;gap:8px;flex-wrap:wrap;padding-top:4px;">
<a href="{link}" target="_blank" style="padding:7px 14px;border-radius:8px;background:{C["tl"]}12;border:1px solid {C["tl"]}22;color:{C["tl"]};font-size:12px;font-weight:500;text-decoration:none;display:inline-flex;align-items:center;gap:6px;">💾 Opslaan als note in vault</a>
<span style="padding:7px 14px;border-radius:8px;background:{C["mv"]}12;border:1px solid {C["mv"]}22;color:{C["mv"]};font-size:12px;font-weight:500;cursor:pointer;display:inline-flex;align-items:center;gap:6px;">🔍 Diepere analyse genereren</span>
<span style="padding:7px 14px;border-radius:8px;background:{C["pe"]}12;border:1px solid {C["pe"]}22;color:{C["pe"]};font-size:12px;font-weight:500;cursor:pointer;display:inline-flex;align-items:center;gap:6px;">🎙️ Podcast paper maken</span>
<span style="padding:7px 14px;border-radius:8px;background:{C["o1"]}12;border:1px solid {C["o1"]}22;color:{C["o1"]};font-size:11px;font-weight:500;cursor:pointer;display:inline-flex;align-items:center;gap:6px;">📋 Kopieer samenvatting</span>
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
        m = TOPIC.get(tid, {"icon":"📰","c":C["t"],"label":tid})
        md += f'<span style="font-size:11px;padding:3px 10px;border-radius:6px;background:{m["c"]}18;color:{m["c"]};font-weight:500;">{m["icon"]} {m["label"]}</span>\n'

    md += f'''</div>
<div style="font-size:12px;color:{C["o0"]};margin-top:4px;">{tot} bronnen · {now.strftime("%H:%M")} CET</div>

> [!podcast] 🎙️ Podcast
> ![[Briefings/podcast/audio/{ds}.mp3]]
> Upload podcast paper naar NotebookLM voor Audio Overview

---

'''

    # Tab bar
    tabs = ""
    for i, (tid, _) in enumerate(twi):
        m = TOPIC.get(tid, {"icon":"📰","c":C["o0"],"label":tid})
        active = i == 0
        s = f"color:{m['c']};background:{C['base']};border-top:2px solid {m['c']};font-weight:500;" if active else f"color:{C['o0']};"
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
        md += f'## <span style="color:{m["c"]}">{m["icon"]} {m["label"]}</span>\n\n'

        for idx, item in enumerate(items[:8]):
            md += article(item, m["c"], tid, idx)

        md += '\n</div>\n\n---\n\n'

    # Kruisverband
    md += f'''## <span style="color:{C["lav"]}">🔗 Kruisverband-analyse</span>

<div style="background:{C["mantle"]};border-radius:12px;padding:20px 24px;font-size:13px;color:{C["st1"]};line-height:1.7;border:1px solid {C["s0"]}44;border-left:3px solid {C["lav"]}44;">

*Kruisverband-analyse wordt gegenereerd bij gebruik van /briefing — Claude legt dan verbanden tussen topics.*

</div>

'''

    # Vault notes
    if vault_data and vault_data.get("notes"):
        md += '## Gerelateerde vault notes\n\n<div style="display:flex;flex-wrap:wrap;gap:6px;margin:12px 0;">\n'
        for n in vault_data["notes"][:8]:
            md += f'<span style="font-size:11px;padding:3px 8px;border-radius:4px;background:{C["lav"]}12;color:{C["lav"]};display:inline-block;">[[{n["title"]}]]</span>\n'
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
