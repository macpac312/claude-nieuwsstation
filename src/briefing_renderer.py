#!/usr/bin/env python3
"""Briefing Renderer v2 voor het Nieuwsstation.

Genereert HTML-enhanced markdown briefings conform de mockup-stijl:
- Ingeklapt: titel + korte samenvatting + impact callout + vertaal/opslaan knoppen
- Uitgeklapt: bronnen-pills, uitgebreide samenvatting, diepe analyse, actiepunten, vault links
- Tabs per topic bovenaan
- Publish-compatible (pure HTML in markdown)

Gebruik:
    python briefing_renderer.py --rss /tmp/rss.json --vault /tmp/vault.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

VAULT_PATH = Path.home() / "Documents" / "WorkMvMOBS"
BRIEFINGS_PATH = VAULT_PATH / "Briefings"

# Catppuccin Mocha
C = {
    "base": "#1e1e2e", "mantle": "#181825", "crust": "#11111b",
    "surface0": "#313244", "surface1": "#45475a", "surface2": "#585b70",
    "overlay0": "#6c7086", "overlay1": "#7f849c",
    "text": "#cdd6f4", "subtext0": "#a6adc8", "subtext1": "#bac2de",
    "lavender": "#b4befe", "blue": "#89b4fa", "sapphire": "#74c7ec",
    "teal": "#94e2d5", "green": "#a6e3a1", "yellow": "#f9e2af",
    "peach": "#fab387", "red": "#f38ba8", "mauve": "#cba6f7",
    "pink": "#f5c2e7",
}

TOPIC_META = {
    "regulatoir": {"icon": "📋", "color": C["blue"], "label": "Regulatoir"},
    "huizenmarkt": {"icon": "🏠", "color": C["green"], "label": "Huizenmarkt"},
    "financieel": {"icon": "📊", "color": C["peach"], "label": "Financieel"},
    "tech": {"icon": "⚡", "color": C["mauve"], "label": "Tech & AI"},
    "sport": {"icon": "⚽", "color": C["green"], "label": "Sport"},
    "ai_nieuws": {"icon": "🤖", "color": C["mauve"], "label": "AI Nieuws"},
}

TYPE_LABELS = {"article": "Artikel", "paper": "Paper", "data": "Dataset", "regulation": "Regulering", "news_api": "Nieuws"}
TYPE_COLORS = {"article": C["sapphire"], "paper": C["mauve"], "data": C["green"], "regulation": C["blue"], "news_api": C["peach"]}


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def _time_ago(iso_date: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_date)
        diff = datetime.now(timezone.utc) - dt
        mins = int(diff.total_seconds() / 60)
        if mins < 60:
            return f"{mins} min"
        hours = mins // 60
        if hours < 24:
            return f"{hours} uur"
        return f"{hours // 24}d"
    except Exception:
        return ""


def _short_summary(text: str, max_len: int = 120) -> str:
    """Maak een korte samenvatting voor ingeklapte weergave."""
    if len(text) <= max_len:
        return text
    # Knip op woordgrens
    cut = text[:max_len].rsplit(" ", 1)[0]
    return cut + "..."


def render_article(article: dict, topic_color: str, topic_id: str, idx: int) -> str:
    """Render een artikel met compacte ingeklapte + rijke uitgeklapte weergave."""
    title = article.get("title", "")
    summary = article.get("summary", "")
    link = article.get("link", "")
    source = article.get("source_name", "")
    stype = article.get("source_type", "article")
    published = article.get("published", "")
    domain = _domain(link)
    time_str = _time_ago(published) if published else ""

    badge_color = TYPE_COLORS.get(stype, C["sapphire"])
    badge_label = TYPE_LABELS.get(stype, "Artikel")

    short = _short_summary(summary)
    art_id = f"{topic_id}-{idx}"

    # ─── INGEKLAPT: titel + korte samenvatting + impact hint + knoppen ───
    collapsed_html = f'''
  <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;">
    <div style="flex: 1;">
      <div style="font-size: 15px; font-weight: 600; color: {C["text"]}; line-height: 1.4; margin-bottom: 6px;">{title}</div>
      <div style="font-size: 13px; color: {C["subtext0"]}; line-height: 1.5;">{short}</div>
    </div>
    <span class="ns-chevron" style="font-size: 12px; color: {C["overlay0"]}; min-width: 24px; height: 24px; display: inline-flex; align-items: center; justify-content: center; border-radius: 6px; background: {C["surface1"]}44; flex-shrink: 0; margin-top: 2px;">▾</span>
  </div>
  <div style="display: flex; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap;">
    <span style="font-size: 10px; padding: 2px 8px; border-radius: 4px; background: {badge_color}22; color: {badge_color}; font-weight: 600;">{badge_label}</span>
    <span style="font-size: 11px; color: {C["overlay1"]};">{source}</span>
    {f'<span style="font-size: 10px; color: {C["surface2"]};">{time_str}</span>' if time_str else ''}
    <span style="flex: 1;"></span>
    <a href="{link}" style="font-size: 10px; padding: 3px 8px; border-radius: 4px; background: {C["teal"]}15; color: {C["teal"]}; text-decoration: none; border: 1px solid {C["teal"]}22;">💾 Bewaar</a>
    <span style="font-size: 10px; padding: 3px 8px; border-radius: 4px; background: {C["sapphire"]}15; color: {C["sapphire"]}; border: 1px solid {C["sapphire"]}22; cursor: pointer;">🌐 Vertaal NL</span>
  </div>'''

    # ─── UITGEKLAPT: bronnen, uitgebreide samenvatting, analyse, acties, vault links ───
    expanded_html = f'''
  <div style="margin-top: 16px;">
    <div style="font-size: 10px; font-weight: 600; color: {C["surface2"]}; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px;">BRONNEN</div>
    <a href="{link}" target="_blank" style="display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 8px; background: {C["surface0"]}66; border: 1px solid {C["surface0"]}; text-decoration: none; margin-bottom: 4px;">
      <span style="font-size: 10px; padding: 1px 6px; border-radius: 3px; background: {badge_color}22; color: {badge_color}; font-weight: 600; border: 1px solid {badge_color}33;">{badge_label}</span>
      <span style="font-size: 12px; color: {C["text"]}; font-weight: 500; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{source}: {title[:60]}{"..." if len(title) > 60 else ""}</span>
      <span style="font-size: 10px; color: {C["overlay0"]}; font-family: monospace;">{domain}</span>
      <span style="color: {C["overlay0"]};">↗</span>
    </a>
  </div>

  <div style="margin-top: 16px;">
    <div style="font-size: 10px; font-weight: 600; color: {C["surface2"]}; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px;">UITGEBREIDE SAMENVATTING</div>
    <div style="background: {C["mantle"]}; border-radius: 10px; padding: 16px 20px; font-size: 13px; color: {C["subtext1"]}; line-height: 1.7; border: 1px solid {C["surface0"]}44;">
      {summary}
    </div>
  </div>

  <div style="margin-top: 16px;">
    <div style="font-size: 10px; font-weight: 600; color: {C["surface2"]}; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px;">IMPACT ANALYSE</div>
    <div style="border-left: 3px solid {topic_color}; padding: 14px 20px; font-size: 13px; color: {C["subtext1"]}; line-height: 1.7; background: {C["mantle"]}88; border-radius: 0 10px 10px 0;">
      <em style="color: {C["overlay0"]};">Impact analyse wordt gegenereerd bij het gebruik van /briefing</em>
    </div>
  </div>

  <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; padding-top: 14px; border-top: 1px solid {C["surface0"]}44;">
    <a href="{link}" target="_blank" style="padding: 7px 14px; border-radius: 8px; background: {C["teal"]}12; border: 1px solid {C["teal"]}22; color: {C["teal"]}; font-size: 12px; font-weight: 500; text-decoration: none; display: inline-flex; align-items: center; gap: 6px;">💾 Opslaan als note in vault</a>
    <span style="padding: 7px 14px; border-radius: 8px; background: {C["sapphire"]}12; border: 1px solid {C["sapphire"]}22; color: {C["sapphire"]}; font-size: 12px; font-weight: 500; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">🔍 Diepere analyse genereren</span>
    <span style="padding: 7px 14px; border-radius: 8px; background: {C["peach"]}12; border: 1px solid {C["peach"]}22; color: {C["peach"]}; font-size: 12px; font-weight: 500; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">🎙️ Podcast paper maken</span>
    <span style="padding: 7px 14px; border-radius: 8px; background: {C["overlay0"]}12; border: 1px solid {C["overlay0"]}22; color: {C["overlay0"]}; font-size: 12px; font-weight: 500; cursor: pointer; display: inline-flex; align-items: center; gap: 6px;">📋 Kopieer samenvatting</span>
  </div>'''

    return f'''
<details class="ns-article" style="background: {C["surface0"]}aa; border: 1px solid {C["surface0"]}; border-left: 3px solid {topic_color}; border-radius: 12px; margin-bottom: 10px; overflow: hidden;">
<summary style="padding: 14px 18px; cursor: pointer; list-style: none; user-select: none;">
{collapsed_html}
</summary>
<div style="padding: 0 18px 18px; border-top: 1px solid {C["surface0"]}88;">
{expanded_html}
</div>
</details>'''


def render_tabs(topics_with_items: list[tuple[str, dict]]) -> str:
    """Render een tab-bar bovenaan met alle topics."""
    tabs = ""
    for i, (tid, _) in enumerate(topics_with_items):
        meta = TOPIC_META.get(tid, {"icon": "📰", "color": C["text"], "label": tid})
        is_first = i == 0
        tabs += f'''<a href="#{tid}" style="padding: 6px 14px; font-size: 12px; color: {meta["color"] if is_first else C["overlay0"]}; {'background: ' + C["base"] + '; border-top: 2px solid ' + meta["color"] + '; font-weight: 500;' if is_first else 'background: transparent;'} text-decoration: none; border-radius: 6px 6px 0 0; display: inline-flex; align-items: center; gap: 4px;">{meta["icon"]} {meta["label"]}</a>'''

    return f'''
<div style="display: flex; background: {C["crust"]}; border-bottom: 1px solid {C["surface0"]}; padding: 0 8px; gap: 0; overflow-x: auto; border-radius: 8px 8px 0 0; margin-bottom: 20px;">
{tabs}
</div>'''


def render_briefing(rss_data: dict, vault_data: dict | None = None,
                    focus: str | None = None) -> str:
    """Genereer een volledige HTML-enhanced markdown briefing."""

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    months_nl = ["januari", "februari", "maart", "april", "mei", "juni",
                 "juli", "augustus", "september", "oktober", "november", "december"]
    date_nl = f"{now.day} {months_nl[now.month - 1]} {now.year}"
    total = rss_data.get("total_items", 0)

    # Verzamel topics met items
    topics_with_items = []
    for tid, tdata in rss_data.get("topics", {}).items():
        if tdata.get("items"):
            topics_with_items.append((tid, tdata))

    topics_list = [t[0] for t in topics_with_items]

    # Frontmatter
    md = f"""---
date: {date_str}
type: briefing
topics: [{", ".join(topics_list)}]
podcast: true
bronnen: {total}
generated: {now.isoformat()}
cssclasses:
  - nieuwsstation
  - ns-briefing
---

"""

    # Header
    md += f"""<div style="margin-bottom: 20px;">

# 📡 Ochtend Briefing — {date_nl}

<div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px;">
"""
    for tid in topics_list:
        meta = TOPIC_META.get(tid, {"icon": "📰", "color": C["text"], "label": tid})
        md += f'  <span style="font-size: 11px; padding: 3px 10px; border-radius: 6px; background: {meta["color"]}18; color: {meta["color"]}; font-weight: 500;">{meta["icon"]} {meta["label"]}</span>\n'

    md += f"""</div>
<div style="font-size: 12px; color: {C["overlay0"]}; margin-top: 8px;">{total} bronnen · gegenereerd {now.strftime("%H:%M")} CET</div>

</div>

"""

    # Podcast embed
    md += f"""> [!podcast] 🎙️ Podcast
> ![[Briefings/podcast/audio/{date_str}.mp3]]
> Upload podcast paper naar NotebookLM voor Audio Overview

---

"""

    # Tab bar
    md += render_tabs(topics_with_items)

    # Per topic
    for topic_id, topic_data in topics_with_items:
        items = topic_data.get("items", [])
        meta = TOPIC_META.get(topic_id, {"icon": "📰", "color": C["text"], "label": topic_id})

        md += f'\n<div id="{topic_id}">\n\n'
        md += f'## <span style="color: {meta["color"]}">{meta["icon"]} {meta["label"]}</span>\n\n'

        for idx, item in enumerate(items[:8]):
            md += render_article(item, meta["color"], topic_id, idx)

        md += '\n</div>\n\n---\n\n'

    # Kruisverband-analyse
    md += f"""
## <span style="color: {C["lavender"]}">🔗 Kruisverband-analyse</span>

<div style="background: {C["mantle"]}; border-radius: 12px; padding: 20px 24px; font-size: 13px; color: {C["subtext1"]}; line-height: 1.7; border: 1px solid {C["surface0"]}44; border-left: 3px solid {C["lavender"]}44;">

*De kruisverband-analyse wordt automatisch gegenereerd door Claude bij het aanmaken van de briefing via `/briefing`.*

</div>

"""

    # Vault notes
    if vault_data and vault_data.get("notes"):
        md += f'\n## Gerelateerde vault notes\n\n<div style="display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0;">\n'
        for note in vault_data["notes"][:8]:
            md += f'  <span style="font-size: 11px; padding: 4px 10px; border-radius: 6px; background: {C["lavender"]}18; color: {C["lavender"]}; border: 1px solid {C["lavender"]}22; cursor: pointer;">[[{note["title"]}]]</span>\n'
        md += '</div>\n\n'

    # Bronnen
    md += '\n## Bronnen\n\n'
    all_sources = set()
    for _, topic_data in topics_with_items:
        for item in topic_data.get("items", []):
            all_sources.add((item.get("source_name", ""), _domain(item.get("link", "")), item.get("source_type", "")))
    for i, (name, domain, stype) in enumerate(sorted(all_sources), 1):
        md += f'{i}. **{name}** — `{domain}` ({TYPE_LABELS.get(stype, stype)})\n'

    md += '\n'
    return md


def render_bar_chart_svg(data: list[dict], title: str = "", width: int = 600, height: int = 160) -> str:
    """Render een bar chart als inline SVG."""
    if not data:
        return ""
    bar_w = min(50, (width - 80) // len(data) - 8)
    max_val = max(d.get("value", 0) for d in data) or 1
    chart_h = height - 50
    bars = ""
    for i, d in enumerate(data):
        x = 40 + i * (bar_w + 8)
        val = d.get("value", 0)
        bar_h = max(4, (val / max_val) * (chart_h - 20))
        y = chart_h - bar_h
        color = d.get("color", C["surface1"])
        label = d.get("label", "")
        hl = d.get("highlight", False)
        bars += f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" rx="4" fill="{color}" opacity="{1 if hl else 0.5}"/>'
        bars += f'<text x="{x + bar_w // 2}" y="{y - 6}" text-anchor="middle" font-size="10" fill="{C["subtext0"]}">{val}%</text>'
        bars += f'<text x="{x + bar_w // 2}" y="{chart_h + 16}" text-anchor="middle" font-size="10" fill="{C["overlay0"]}">{label}</text>'
    return f'''
<div style="background: {C["surface0"]}44; border-radius: 12px; padding: 16px; border: 1px solid {C["surface0"]}; margin: 16px 0;">
  {f'<div style="font-size: 12px; font-weight: 500; color: {C["subtext1"]}; margin-bottom: 12px;">{title}</div>' if title else ''}
  <svg width="100%" viewBox="0 0 {width} {height}" style="max-width: {width}px;">{bars}</svg>
</div>'''


def render_hype_meter(items: list[dict], title: str = "") -> str:
    """Render horizontale progress bars."""
    if not items:
        return ""
    rows = ""
    for item in items:
        name = item.get("name", "")
        value = item.get("value", 0)
        color = item.get("color", C["blue"])
        rows += f'''<div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
      <span style="font-size: 12px; color: {C["subtext0"]}; min-width: 120px;">{name}</span>
      <div style="flex: 1; height: 8px; background: {C["surface0"]}; border-radius: 4px; overflow: hidden;"><div style="height: 100%; width: {value}%; background: {color}; border-radius: 4px;"></div></div>
      <span style="font-size: 11px; color: {C["overlay1"]}; min-width: 40px; text-align: right;">{value}%</span>
    </div>'''
    return f'''
<div style="background: {C["surface0"]}44; border-radius: 12px; padding: 16px 20px; border: 1px solid {C["surface0"]}; margin: 16px 0;">
  {f'<div style="font-size: 13px; font-weight: 600; color: {C["subtext1"]}; margin-bottom: 12px;">{title}</div>' if title else ''}{rows}
</div>'''


def render_breaking_ticker(text: str, time_str: str = "") -> str:
    """Render een breaking news ticker."""
    return f'''
<div style="background: {C["red"]}15; border: 1px solid {C["red"]}33; border-radius: 10px; padding: 10px 16px; margin-bottom: 16px; display: flex; align-items: center; gap: 10px;">
  <span style="background: {C["red"]}; color: {C["crust"]}; font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 4px;">● BREAKING</span>
  <span style="font-size: 13px; color: {C["text"]}; flex: 1;">{text}</span>
  {f'<span style="font-size: 11px; color: {C["red"]};">{time_str}</span>' if time_str else ''}
</div>'''


def main():
    parser = argparse.ArgumentParser(description="Nieuwsstation Briefing Renderer")
    parser.add_argument("--rss", required=True, help="Pad naar RSS fetcher output JSON")
    parser.add_argument("--vault", help="Pad naar vault search output JSON")
    parser.add_argument("--focus", help="Focus prompt")
    parser.add_argument("--output", help="Output pad")

    args = parser.parse_args()

    rss_data = json.loads(Path(args.rss).read_text())
    vault_data = json.loads(Path(args.vault).read_text()) if args.vault else None

    md = render_briefing(rss_data, vault_data, args.focus)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_path = Path(args.output) if args.output else BRIEFINGS_PATH / f"{date_str}.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md)

    print(f"[OK] Briefing geschreven naar: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
