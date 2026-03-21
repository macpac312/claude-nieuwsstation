#!/usr/bin/env python3
"""Briefing Renderer voor het Nieuwsstation.

Genereert HTML-enhanced markdown briefings die er prachtig uitzien
in Obsidian (reading view) en Obsidian Publish.

Features:
- Uitklapbare artikelen via <details>/<summary>
- Nieuws-cards met gradient achtergronden
- Inline SVG charts
- Bronnen-pills met type labels
- Actieknoppen
- Catppuccin Mocha styling via CSS classes

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

# Catppuccin Mocha kleuren
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
    "regulatoir": {"icon": "📋", "color": C["blue"], "gradient": f"linear-gradient(135deg, {C['blue']}22, {C['surface0']})"},
    "huizenmarkt": {"icon": "🏠", "color": C["green"], "gradient": f"linear-gradient(135deg, {C['green']}22, {C['surface0']})"},
    "financieel": {"icon": "📊", "color": C["peach"], "gradient": f"linear-gradient(135deg, {C['peach']}22, {C['surface0']})"},
    "tech": {"icon": "⚡", "color": C["mauve"], "gradient": f"linear-gradient(135deg, {C['mauve']}22, {C['surface0']})"},
    "sport": {"icon": "⚽", "color": C["green"], "gradient": f"linear-gradient(135deg, {C['green']}22, {C['surface0']})"},
    "ai_nieuws": {"icon": "🤖", "color": C["mauve"], "gradient": f"linear-gradient(135deg, {C['mauve']}22, {C['surface0']})"},
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


def render_article_card(article: dict, topic_color: str, expanded: bool = False) -> str:
    """Render een artikel als een uitklapbare HTML card."""
    title = article.get("title", "")
    summary = article.get("summary", "")
    link = article.get("link", "")
    source = article.get("source_name", "")
    stype = article.get("source_type", "article")
    image = article.get("image_url", "")
    published = article.get("published", "")
    domain = _domain(link)
    time_str = _time_ago(published) if published else ""

    badge_color = TYPE_COLORS.get(stype, C["sapphire"])
    badge_label = TYPE_LABELS.get(stype, "Artikel")

    # Image section (als beschikbaar)
    image_html = ""
    if image:
        image_html = f'''
<div class="ns-card-image" style="background-image: url('{image}'); background-size: cover; background-position: center; height: 140px; border-radius: 10px 10px 0 0; position: relative;">
  <div style="position: absolute; bottom: 0; left: 0; right: 0; height: 60px; background: linear-gradient(transparent, {C["surface0"]}ee);"></div>
</div>'''

    # Source pill
    source_pill = f'''<a href="{link}" class="ns-source-pill" style="display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 6px; background: {C["surface0"]}88; border: 1px solid {C["surface1"]}44; text-decoration: none; font-size: 11px; margin-top: 8px;">
  <span style="padding: 1px 6px; border-radius: 3px; background: {badge_color}22; color: {badge_color}; font-weight: 600; font-size: 10px;">{badge_label}</span>
  <span style="color: {C["text"]};">{source}</span>
  <span style="color: {C["overlay0"]}; font-family: monospace; font-size: 10px;">{domain}</span>
  <span style="color: {C["overlay0"]};">↗</span>
</a>'''

    # Meta line
    meta_html = f'''<div style="display: flex; align-items: center; gap: 8px; margin-top: 6px; flex-wrap: wrap;">
  <span style="font-size: 10px; padding: 2px 8px; border-radius: 4px; background: {badge_color}22; color: {badge_color}; font-weight: 600;">{badge_label}</span>
  <span style="font-size: 11px; color: {C["overlay1"]};">{source}</span>
  {f'<span style="font-size: 10px; color: {C["surface2"]}; margin-left: auto;">{time_str}</span>' if time_str else ''}
</div>'''

    return f'''
<details class="ns-article" style="background: {C["surface0"]}aa; border: 1px solid {C["surface0"]}; border-left: 3px solid {topic_color}; border-radius: 12px; margin-bottom: 12px; overflow: hidden;">
<summary class="ns-article-summary" style="padding: 16px 20px; cursor: pointer; list-style: none; user-select: none;">
  <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 6px;">
    <strong style="font-size: 15px; color: {C["text"]}; line-height: 1.4; flex: 1;">{title}</strong>
    <span class="ns-chevron" style="font-size: 12px; color: {C["overlay0"]}; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; border-radius: 6px; background: {C["surface1"]}44; flex-shrink: 0;">▾</span>
  </div>
  <div style="font-size: 13px; color: {C["subtext0"]}; line-height: 1.6; margin-bottom: 8px;">{summary}</div>
  {meta_html}
</summary>
<div style="padding: 0 20px 20px; border-top: 1px solid {C["surface0"]}88;">

  <div style="margin-top: 12px;">
    <div style="font-size: 10px; font-weight: 600; color: {C["surface2"]}; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px;">BRONNEN</div>
    {source_pill}
  </div>

  <div style="margin-top: 16px;">
    <div style="font-size: 10px; font-weight: 600; color: {C["surface2"]}; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px;">SAMENVATTING</div>
    <div style="background: {C["mantle"]}; border-radius: 10px; padding: 16px 20px; font-size: 13px; color: {C["subtext1"]}; line-height: 1.7; border: 1px solid {C["surface0"]}44;">
      {summary}
    </div>
  </div>

  <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; padding-top: 16px; border-top: 1px solid {C["surface0"]}44;">
    <a href="{link}" style="padding: 7px 14px; border-radius: 8px; background: {C["teal"]}12; border: 1px solid {C["teal"]}22; color: {C["teal"]}; font-size: 12px; font-weight: 500; text-decoration: none; display: inline-flex; align-items: center; gap: 6px;">🔗 Open bron</a>
    <span style="padding: 7px 14px; border-radius: 8px; background: {C["sapphire"]}12; border: 1px solid {C["sapphire"]}22; color: {C["sapphire"]}; font-size: 12px; font-weight: 500; cursor: pointer;">🔍 Diepere analyse</span>
    <span style="padding: 7px 14px; border-radius: 8px; background: {C["peach"]}12; border: 1px solid {C["peach"]}22; color: {C["peach"]}; font-size: 12px; font-weight: 500; cursor: pointer;">🎙️ Podcast paper</span>
  </div>

</div>
</details>'''


def render_news_card(article: dict, topic_color: str, size: str = "full") -> str:
    """Render een visueel nieuws-card (voor 'Laatste nieuws' stijl)."""
    title = article.get("title", "")
    summary = article.get("summary", "")
    link = article.get("link", "")
    source = article.get("source_name", "")
    image = article.get("image_url", "")
    published = article.get("published", "")
    time_str = _time_ago(published) if published else ""
    stype = article.get("source_type", "article")
    badge_color = TYPE_COLORS.get(stype, C["sapphire"])
    badge_label = TYPE_LABELS.get(stype, "Artikel")

    bg_style = f"background-image: url('{image}'); background-size: cover; background-position: center;" if image else f"background: linear-gradient(135deg, {topic_color}15, {C['surface0']});"

    if size == "hero":
        return f'''
<a href="{link}" style="display: block; border-radius: 14px; overflow: hidden; text-decoration: none; margin-bottom: 14px; border: 1px solid {C["surface0"]};">
  <div style="{bg_style} min-height: 180px; padding: 20px; display: flex; flex-direction: column; justify-content: flex-end; position: relative;">
    <div style="position: absolute; inset: 0; background: linear-gradient(transparent 30%, {C["crust"]}ee 100%); border-radius: 14px;"></div>
    <div style="position: relative; z-index: 1;">
      <span style="font-size: 10px; padding: 2px 8px; border-radius: 4px; background: {badge_color}33; color: {badge_color}; font-weight: 600;">{badge_label}</span>
      <div style="font-size: 17px; font-weight: 600; color: {C["text"]}; margin-top: 8px; line-height: 1.4;">{title}</div>
    </div>
  </div>
  <div style="padding: 12px 20px; background: {C["surface0"]}44;">
    <div style="font-size: 12px; color: {C["subtext0"]}; line-height: 1.5; margin-bottom: 8px;">{summary[:150]}{"..." if len(summary) > 150 else ""}</div>
    <div style="display: flex; justify-content: space-between; font-size: 11px; color: {C["overlay0"]};">
      <span>{source}</span>
      <span>{time_str}</span>
    </div>
  </div>
</a>'''

    # Compact card
    return f'''
<a href="{link}" style="display: flex; align-items: center; gap: 14px; padding: 12px 16px; border-radius: 10px; background: {C["surface0"]}44; border: 1px solid {C["surface0"]}; text-decoration: none; margin-bottom: 8px;">
  {f'<div style="width: 56px; height: 56px; border-radius: 8px; background-image: url({chr(39)}{image}{chr(39)}); background-size: cover; background-position: center; flex-shrink: 0;"></div>' if image else f'<div style="width: 56px; height: 56px; border-radius: 8px; background: {topic_color}15; display: flex; align-items: center; justify-content: center; flex-shrink: 0; font-size: 20px;">📰</div>'}
  <div style="flex: 1; min-width: 0;">
    <span style="font-size: 10px; padding: 1px 6px; border-radius: 3px; background: {badge_color}22; color: {badge_color}; font-weight: 600;">{badge_label}</span>
    <div style="font-size: 13px; font-weight: 500; color: {C["text"]}; margin-top: 4px; line-height: 1.3;">{title}</div>
    <div style="font-size: 11px; color: {C["overlay0"]}; margin-top: 4px;">{source} · {time_str}</div>
  </div>
</a>'''


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
        is_highlight = d.get("highlight", False)

        bars += f'''
    <rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" rx="4" fill="{color}" opacity="{1 if is_highlight else 0.5}" />
    <text x="{x + bar_w // 2}" y="{y - 6}" text-anchor="middle" font-size="10" fill="{C["subtext0"]}">{val}%</text>
    <text x="{x + bar_w // 2}" y="{chart_h + 16}" text-anchor="middle" font-size="10" fill="{C["overlay0"]}">{label}</text>'''

    return f'''
<div style="background: {C["surface0"]}44; border-radius: 12px; padding: 16px; border: 1px solid {C["surface0"]}; margin: 16px 0;">
  {f'<div style="font-size: 12px; font-weight: 500; color: {C["subtext1"]}; margin-bottom: 12px;">{title}</div>' if title else ''}
  <svg width="100%" viewBox="0 0 {width} {height}" style="max-width: {width}px;">
    {bars}
  </svg>
</div>'''


def render_hype_meter(items: list[dict], title: str = "") -> str:
    """Render horizontale progress bars (AI hype meter, benchmarks)."""
    if not items:
        return ""

    rows = ""
    for item in items:
        name = item.get("name", "")
        value = item.get("value", 0)
        color = item.get("color", C["blue"])
        rows += f'''
    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
      <span style="font-size: 12px; color: {C["subtext0"]}; min-width: 120px;">{name}</span>
      <div style="flex: 1; height: 8px; background: {C["surface0"]}; border-radius: 4px; overflow: hidden;">
        <div style="height: 100%; width: {value}%; background: {color}; border-radius: 4px;"></div>
      </div>
      <span style="font-size: 11px; color: {C["overlay1"]}; min-width: 40px; text-align: right;">{value}%</span>
    </div>'''

    return f'''
<div style="background: {C["surface0"]}44; border-radius: 12px; padding: 16px 20px; border: 1px solid {C["surface0"]}; margin: 16px 0;">
  {f'<div style="font-size: 13px; font-weight: 600; color: {C["subtext1"]}; margin-bottom: 12px;">{title}</div>' if title else ''}
  {rows}
</div>'''


def render_breaking_ticker(text: str, time_str: str = "") -> str:
    """Render een breaking news ticker."""
    return f'''
<div style="background: {C["red"]}15; border: 1px solid {C["red"]}33; border-radius: 10px; padding: 10px 16px; margin-bottom: 16px; display: flex; align-items: center; gap: 10px;">
  <span style="background: {C["red"]}; color: {C["crust"]}; font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 4px; letter-spacing: 0.05em;">● BREAKING</span>
  <span style="font-size: 13px; color: {C["text"]}; flex: 1;">{text}</span>
  {f'<span style="font-size: 11px; color: {C["red"]};">{time_str}</span>' if time_str else ''}
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

    topics_list = []
    for tid, tdata in rss_data.get("topics", {}).items():
        if tdata.get("items"):
            topics_list.append(tid)

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
    md += f"""<div class="ns-briefing-header" style="margin-bottom: 24px;">

# 📡 Ochtend Briefing — {date_nl}

<div style="display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px;">
"""
    for tid in topics_list:
        meta = TOPIC_META.get(tid, {"icon": "📰", "color": C["text"]})
        md += f'  <span style="font-size: 11px; padding: 3px 10px; border-radius: 6px; background: {meta["color"]}18; color: {meta["color"]}; font-weight: 500;">{meta["icon"]} {tid}</span>\n'

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

    # Per topic
    for topic_id, topic_data in rss_data.get("topics", {}).items():
        items = topic_data.get("items", [])
        if not items:
            continue

        meta = TOPIC_META.get(topic_id, {"icon": "📰", "color": C["text"]})

        md += f'\n## <span style="color: {meta["color"]}">{meta["icon"]} {topic_id.replace("_", " ").title()}</span>\n\n'

        # Eerste artikel als hero card (als het een image heeft)
        hero_done = False
        for item in items:
            if item.get("image_url") and not hero_done:
                md += render_news_card(item, meta["color"], "hero")
                hero_done = True
            else:
                md += render_article_card(item, meta["color"])

    # Kruisverband-analyse
    md += f"""
---

## <span style="color: {C["lavender"]}">🔗 Kruisverband-analyse</span>

<div style="background: {C["mantle"]}; border-radius: 12px; padding: 20px 24px; font-size: 13px; color: {C["subtext1"]}; line-height: 1.7; border: 1px solid {C["surface0"]}44; border-left: 3px solid {C["lavender"]}44;">

*De kruisverband-analyse wordt automatisch gegenereerd door Claude bij het aanmaken van de briefing via het `/briefing` command.*

</div>

"""

    # Vault notes
    if vault_data and vault_data.get("notes"):
        md += f'\n## Gerelateerde vault notes\n\n<div style="display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0;">\n'
        for note in vault_data["notes"][:8]:
            md += f'  <span style="font-size: 11px; padding: 4px 10px; border-radius: 6px; background: {C["lavender"]}18; color: {C["lavender"]}; border: 1px solid {C["lavender"]}22; cursor: pointer;">[[{note["title"]}]]</span>\n'
        md += '</div>\n\n'

    # Bronnen tabel
    md += '\n## Bronnen\n\n'
    all_sources = set()
    for topic_data in rss_data.get("topics", {}).values():
        for item in topic_data.get("items", []):
            all_sources.add((item.get("source_name", ""), _domain(item.get("link", "")), item.get("source_type", "")))

    for i, (name, domain, stype) in enumerate(sorted(all_sources), 1):
        md += f'{i}. **{name}** — `{domain}` ({TYPE_LABELS.get(stype, stype)})\n'

    md += '\n'
    return md


def main():
    parser = argparse.ArgumentParser(description="Nieuwsstation Briefing Renderer")
    parser.add_argument("--rss", required=True, help="Pad naar RSS fetcher output JSON")
    parser.add_argument("--vault", help="Pad naar vault search output JSON")
    parser.add_argument("--focus", help="Focus prompt")
    parser.add_argument("--output", help="Output pad (default: ~/Documents/WorkMvMOBS/Briefings/YYYY-MM-DD.md)")

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
