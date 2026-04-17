#!/usr/bin/env python3
"""
Dagkrant renderer: JSON-plan → HTML
Leest /tmp/dagkrant-plan.json + template → schrijft Briefings/YYYY-MM-DD-dagkrant.html
"""
import json as json_mod
import json, re, sys
from pathlib import Path
from datetime import datetime, timezone

TEMPLATE  = Path.home() / "nieuwsstation/src/templates/dagkrant_template.html"
BRIEFINGS = Path.home() / "Documents/WorkMvMOBS/Briefings"
PLAN_FILE = Path("/tmp/dagkrant-plan.json")


# ─── Markdown → HTML ─────────────────────────────────────────────────────────
def md(text: str) -> str:
    """Lichte markdown conversie (geen externe dependencies)."""
    if not text:
        return ""
    # Split op lege regels → paragrafen
    paragraphs = re.split(r'\n\s*\n', text.strip())
    parts = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if para.startswith("### "):
            parts.append(f"<h5>{_inline(para[4:])}</h5>")
        elif para.startswith("## "):
            parts.append(f"<h4>{_inline(para[3:])}</h4>")
        elif para.startswith("> "):
            parts.append(f"<blockquote>{_inline(para[2:])}</blockquote>")
        elif para.startswith("- ") or para.startswith("* "):
            items = [f"<li>{_inline(l[2:])}</li>" for l in para.split("\n") if l.startswith(("- ", "* "))]
            parts.append("<ul>" + "".join(items) + "</ul>")
        else:
            # Meerdere regels → één paragraaf
            lines = [_inline(l) for l in para.split("\n") if l.strip()]
            parts.append("<p>" + " ".join(lines) + "</p>")
    return "\n".join(parts)


def _inline(s: str) -> str:
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'\*(.+?)\*',     r'<em>\1</em>', s)
    s = re.sub(r'`(.+?)`',       r'<code>\1</code>', s)
    return s


# ─── HTML bouwstenen ──────────────────────────────────────────────────────────
def tag_html(tag: str, label: str) -> str:
    cls_map = {
        "nederland":   "tag-nl",       "wereld":     "tag-world",
        "financieel":  "tag-finance",  "sport":      "tag-sport",
        "aitech":      "tag-ai",       "ai_tech":    "tag-ai",
        "regulatoir":  "tag-reg",      "huizenmarkt":"tag-housing",
        "live":        "tag-live",     "analyse":    "tag-analysis",
    }
    cls = cls_map.get(tag, f"tag-{tag}")
    return f'<span class="tag {cls}">{label}</span>'


def bronnen_html(bronnen: list) -> str:
    if not bronnen:
        return ""
    links = "".join(
        f'<a class="source-link" href="{b.get("url","#")}" target="_blank">&#128196; {b.get("naam","bron")}</a>'
        for b in bronnen
    )
    return f'<div class="source-links" style="margin-top:.8rem">{links}</div>'


def render_article_card(art: dict) -> str:
    """Render één article-card. Klik opent artikel in rechter panel."""
    aid       = art.get("id", "x")
    titel     = art.get("titel", "")
    teaser    = art.get("teaser", "")
    datum     = art.get("datum", "")
    bronnen   = art.get("bronnen", [])
    bron_naam = (bronnen or [{}])[0].get("naam", art.get("bron", ""))
    bron_url  = (bronnen or [{}])[0].get("url", "")
    tag       = art.get("tag", "")
    label     = art.get("tag_label", tag.capitalize())
    foto_url  = art.get("foto_url", "")

    # Escape voor data-attributen
    def esc(s: str) -> str:
        return s.replace('"', '&quot;').replace("'", "&#39;")

    # Foto bovenaan de kaart (16:9)
    foto_html = (
        f'<div class="article-img">'
        f'<img src="{esc(foto_url)}" alt="" loading="lazy"'
        f' onerror="this.parentElement.style.display=\'none\'">'
        f'</div>'
    ) if foto_url else ""

    # Achtergrond-knop
    bg_btn = f'<button class="bg-badge" onclick="openBg(\'bg-{aid}\', event)">&#9654; Achtergrond</button>'
    # Opslaan-knop (direct opslaan zonder achtergrond)
    save_btn = f'<button class="save-btn" onclick="saveArticle(this, event)" title="Opslaan als Obsidian-notitie">&#128190;</button>'

    # Artikel-link opent reader-panel rechts
    reader_attrs = (
        f'data-reader-url="{esc(bron_url)}"'
        f' data-reader-title="{esc(titel)}"'
        f' data-reader-teaser="{esc(teaser)}"'
        f' data-reader-bron="{esc(bron_naam)}"'
        f' data-reader-datum="{esc(datum)}"'
        f' data-reader-tag="{tag}"'
    )

    return f"""
<div class="article-card" {reader_attrs} onclick="openReader(this, event)">
  {foto_html}
  <div class="article-body">
    {bg_btn}
    {save_btn}
    {tag_html(tag, label)}
    <h3>{titel}</h3>
    <p>{teaser}</p>
    <div class="meta">{bron_naam} &bull; {datum}</div>
  </div>
</div>"""


def render_bg_panel(art: dict) -> str:
    """Render het bg-article panel (trap3). Pre-gevuld of on-demand knop."""
    aid       = art.get("id", "x")
    titel     = art.get("titel", "")
    datum     = art.get("datum", "")
    trap3_md  = art.get("trap3_md", "")
    bronnen   = art.get("bronnen", [])
    bron_namen = ", ".join(b.get("naam", "") for b in bronnen)
    summary   = art.get("teaser", art.get("body_md", ""))[:300]
    sources_csv = ",".join(b.get("naam", "") for b in bronnen)

    # Titel en teaser escapen voor data-attributen
    def esc(s: str) -> str:
        return s.replace('"', '&quot;').replace("'", "&#39;")

    if trap3_md:
        # Pre-gegenereerd: toon direct
        inner = f"""
    <h4>{titel}</h4>
    <p class="bg-byline">Analyse &middot; De Dagkrant &middot; {datum}</p>
    {md(trap3_md)}
    <div class="bg-footer">Bronnen: {bron_namen}</div>"""
    else:
        # On-demand: toon generate-knop (data-attributen, geen onclick)
        tag_val = art.get("tag", "")
        bron_url_val = (bronnen or [{}])[0].get("url", "") if bronnen else ""
        inner = f"""
    <div class="bg-gen-wrap" style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:12rem;gap:1rem">
      <p style="color:var(--t3);font-size:.9rem">{esc(titel)}</p>
      <button class="bg-gen-btn"
              data-bgid="bg-{aid}"
              data-title="{esc(titel)}"
              data-summary="{esc(summary)}"
              data-sources="{esc(sources_csv)}"
              data-tag="{esc(tag_val)}"
              data-url="{esc(bron_url_val)}"
              style="padding:.7rem 1.6rem;background:var(--accent);color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:.9rem;font-weight:600">
        &#9889; Genereer achtergrond
      </button>
    </div>"""

    return f"""
<div class="bg-article" id="bg-{aid}">
  <div class="bg-inner">
    {inner}
  </div>
</div>"""


def render_hero(hero: dict) -> str:
    foto_url    = hero.get("foto_url", "")
    foto_credit = hero.get("foto_credit", "")
    foto_html   = (
        f'<div class="hero-img"><img src="{foto_url}" alt="{hero.get("titel","")}" loading="lazy">'
        f'<div class="photo-credit">{foto_credit}</div></div>'
    ) if foto_url else ""

    body_html = md(hero.get("body_md", ""))

    # Altijd achtergrond-knop — pre-gevuld of on-demand (zelfde als artikel cards)
    titel_esc   = hero.get("titel","").replace('"','&quot;').replace("'","&#39;")
    summary_esc = hero.get("teaser", hero.get("body_md",""))[:300].replace('"','&quot;').replace("'","&#39;")
    sources_csv = ",".join(b.get("naam","") for b in hero.get("bronnen",[]))
    if hero.get("trap3_md"):
        bg_btn = '<button class="bg-btn" onclick="openBg(\'bg-hero\', event)">&#9654; Achtergrond</button>'
    else:
        bg_btn = (
            f'<button class="bg-gen-btn bg-btn"'
            f' data-bgid="bg-hero"'
            f' data-title="{titel_esc}"'
            f' data-summary="{summary_esc}"'
            f' data-sources="{sources_csv}">&#9889; Genereer achtergrond</button>'
        )

    return f"""
<div class="hero-article">
  {tag_html(hero.get("tag","wereld"), hero.get("tag_label","Wereld"))}
  {foto_html}
  <div class="hero-text">
    <h2>{hero.get("titel","")}</h2>
    <p class="lead">{hero.get("lead","")}</p>
    {body_html}
    <div class="meta">{hero.get("datum","")} &bull; {", ".join(b.get("naam","") for b in hero.get("bronnen",[]))}</div>
    {bronnen_html(hero.get("bronnen",[]))}
    {bg_btn}
  </div>
</div>"""


def render_section(sid: str, label: str, tag_cls: str, artikelen: list) -> str:
    if not artikelen:
        return ""
    visible   = artikelen[:3]
    extra     = artikelen[3:]
    cards_vis = "\n".join(render_article_card(a) for a in visible)
    more_btn  = (f'<button class="more-btn" id="morebtn-{sid}" '
                 f'onclick="toggleMore(\'{sid}\')" title="Meer artikelen">meer &#9662;</button>'
                 if extra else "")
    extra_html = ""
    if extra:
        extra_cards = "\n".join(render_article_card(a) for a in extra)
        extra_html = f'\n<div class="extra-cards" id="more-{sid}">\n{extra_cards}\n</div>'
    return f"""
<hr class="section-sep" id="{sid}"/>
<div class="section-head">
  {tag_html(tag_cls, label)}
  <h2>{label}</h2>
  <div class="section-line"></div>
  {more_btn}
</div>
<div class="article-grid">
{cards_vis}{extra_html}
</div>"""


def sparkline_svg(values: list, up_color: str = "#16a34a", down_color: str = "#dc2626",
                  width: int = 72, height: int = 24) -> str:
    """Genereer een inline SVG sparkline voor een reeks getallen."""
    if len(values) < 2:
        return ""
    mn, mx = min(values), max(values)
    rng = mx - mn or 1
    step = width / (len(values) - 1)
    pts = " ".join(
        f"{i * step:.1f},{height - (v - mn) / rng * height:.1f}"
        for i, v in enumerate(values)
    )
    trend_up = values[-1] >= values[0]
    color = up_color if trend_up else down_color
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'style="display:inline-block;vertical-align:middle;overflow:visible">'
        f'<polyline points="{pts}" fill="none" stroke="{color}" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


def render_financieel_section(data: dict, widgets: dict | None = None) -> str:
    arts = data.get("artikelen", [])
    if not arts:
        return ""
    w = widgets or {}
    koersen = data.get("koersen", [])

    # Trend-data per koers-naam
    trend_map = {
        "AEX":     w.get("aex_trend", []),
        "S&P 500": w.get("sp500_trend", []),
        "Brent":   w.get("brent_trend", []),
    }

    # ── Weer-widget ──────────────────────────────────────────────────────────
    weer_html = ""
    if w.get("weer_temp") and w.get("weer_temp") != "?":
        feel = w.get("weer_feel", "")
        wind = w.get("weer_wind", "")
        hum  = w.get("weer_humidity", "")
        desc = w.get("weer_desc", "")
        feel_str  = f"<span>Voelt als {feel}°C</span>" if feel and feel != "?" else ""
        wind_str  = f"<span>Wind {wind} km/h</span>" if wind and wind != "?" else ""
        hum_str   = f"<span>Vochtigheid {hum}%</span>" if hum and hum != "?" else ""
        detail_html = "\n".join(filter(None, [feel_str, wind_str, hum_str]))
        weer_html = f"""
<div class="weather-widget">
  <h3>&#127777; Hilversum</h3>
  <div class="weather-main">
    <div class="weather-temp">{w['weer_temp']}°</div>
    <div class="weather-icon">{w.get('weer_icon','🌤️')}</div>
  </div>
  <div class="weather-desc">{desc}</div>
  <div class="weather-details" style="margin-top:.8rem">{detail_html}</div>
</div>"""

    # ── Verkeer-widget ───────────────────────────────────────────────────────
    verkeer_html = f"""
<div class="traffic-widget">
  <h3>&#128663; A27/A28 Hilversum–Utrecht</h3>
  <div class="traffic-item">
    <strong>Actuele status</strong>
    <span><a href="https://www.anwb.nl/verkeer/nederland" target="_blank"
      style="color:#fff;text-decoration:underline">Bekijk op ANWB &#8599;</a></span>
  </div>
  <div class="traffic-route">
    <strong>Route:</strong> Hilversum → Knipstraat Utrecht
  </div>
</div>"""

    # ── Koersen-tabel met sparklines ─────────────────────────────────────────
    koersen_html = ""
    if koersen:
        now_str = datetime.now().strftime("%H:%M")
        rows = ""
        for k in koersen:
            naam  = k["naam"]
            delta = str(k.get("delta", ""))
            kleur = "var(--green)" if not delta.startswith("-") else "var(--red)"
            trend = trend_map.get(naam, [])
            spark = sparkline_svg(trend) if trend else ""
            rows += (
                f'<tr>'
                f'<td class="kn">{naam}</td>'
                f'<td class="kv">{k["waarde"]}</td>'
                f'<td class="kd" style="color:{kleur}">{delta}</td>'
                f'<td class="ks">{spark}</td>'
                f'</tr>'
            )
        koersen_html = f"""
<div class="sidebar">
  {weer_html}
  {verkeer_html}
  <div class="widget">
    <h3>Markten <span style="font-weight:400;font-size:.65rem;float:right">{now_str}</span></h3>
    <table class="koersen-table">{rows}</table>
  </div>
</div>"""
    elif weer_html:
        koersen_html = f'<div class="sidebar">{weer_html}{verkeer_html}</div>'

    visible   = arts[:3]
    extra     = arts[3:]
    cards_vis = "\n".join(render_article_card(a) for a in visible)
    more_btn  = (f'<button class="more-btn" id="morebtn-financieel" '
                 f'onclick="toggleMore(\'financieel\')" title="Meer artikelen">meer &#9662;</button>'
                 if extra else "")
    extra_html = ""
    if extra:
        extra_cards = "\n".join(render_article_card(a) for a in extra)
        extra_html = f'\n<div class="extra-cards" id="more-financieel">\n{extra_cards}\n</div>'
    return f"""
<hr class="section-sep" id="financieel"/>
<div class="section-head">
  {tag_html("financieel", "Financieel")}
  <h2>Financieel</h2>
  <div class="section-line"></div>
  {more_btn}
</div>
<div class="layout-main">
  <div class="article-grid">{cards_vis}{extra_html}</div>
  {koersen_html}
</div>"""


def _esc_js(s: str) -> str:
    """Escape een string voor gebruik in een JS-string literal."""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")


def render_kruisverband(plan: dict) -> str:
    tekst = plan.get("kruisverband_md", "")
    if not tekst:
        return ""
    vault = plan.get("vault_connecties", [])
    vault_html = ""
    if vault:
        chips = ""
        for v in vault:
            # Accepteer zowel dict (nieuw) als legacy string "[[title]]"
            if isinstance(v, dict):
                title   = v.get("title", "")
                path    = v.get("path", "")
                excerpt = v.get("excerpt", "")
            else:
                title   = str(v).strip("[]")
                path    = title + ".md"
                excerpt = ""
            if not title:
                continue
            tooltip = _esc_js(excerpt) if excerpt else _esc_js(title)
            chips += (
                f'<a href="#" class="vault-link" title="{tooltip}"'
                f" onclick=\"openVaultNote('{_esc_js(title)}','{_esc_js(path)}',event)\">"
                f"&#128196; {title}</a>"
            )
        vault_html = f'<div class="vault-connecties"><h5>&#128279; Vault-connecties</h5>{chips}</div>'

    # Data voor /kruisverband-visual endpoint (bezorgd als <script type="application/json">)
    import json as _json
    topnieuws_data = []
    for t in (plan.get("topnieuws", [])[:6]):
        sectie = t.get("tag_label", "") or t.get("tag", "")
        topnieuws_data.append({
            "titel": t.get("titel", ""),
            "sectie": sectie,
            "article_id": sectie.lower().replace(" ", "-") or "dagkrant",
        })
    # Hero ook meenemen
    hero_obj = plan.get("hero", {})
    if hero_obj.get("titel"):
        hero_sectie = hero_obj.get("tag_label", "") or hero_obj.get("tag", "Hero")
        topnieuws_data.insert(0, {
            "titel": hero_obj.get("titel", ""),
            "sectie": hero_sectie,
            "article_id": hero_sectie.lower().replace(" ", "-") or "hero",
        })
    datum_iso = plan.get("datum_iso", "")
    payload = _json.dumps({
        "kruisverband_md": tekst,
        "topnieuws": topnieuws_data,
        "datum_iso": datum_iso,
    }, ensure_ascii=False)
    # Escape </script> om HTML-parser breakout te voorkomen
    payload_safe = payload.replace("</", "<\\/")

    return f"""
<hr class="section-sep" id="kruisverband"/>
<div class="section-head">
  <span class="tag tag-analysis">Analyse</span>
  <h2>Kruisverbanden</h2>
  <div class="section-line"></div>
</div>
<div class="layout-main">
  <div>
    <button class="ns-viz-btn" id="viz-kruisverband-btn" onclick="generateKruisverbandVisual(event)">&#128279; Visualiseer verbanden</button>
    <div id="viz-kruisverband-target"></div>
    <script type="application/json" id="kruisverband-data">{payload_safe}</script>
    {md(tekst)}
  </div>
  {vault_html}
</div>"""


# ─── Navigatie ────────────────────────────────────────────────────────────────
NAV_SECTIONS = [
    ("breaking",     "&#9679; Live",  "live"),
    ("nederland",    "Nederland",     ""),
    ("wereld",       "Wereld",        ""),
    ("financieel",   "Financieel",    ""),
    ("regulatoir",   "Regulatoir",    ""),
    ("huizenmarkt",  "Huizenmarkt",   ""),
    ("sport",        "Sport",         ""),
    ("aitech",       "AI &amp; Tech", ""),
    ("kruisverband", "Analyse",       ""),
]

def render_nav(extra_sections: list | None = None) -> str:
    sections = list(NAV_SECTIONS)
    if extra_sections:
        # Voeg extra secties in vóór 'kruisverband'
        insert_idx = next((i for i, (sid, _, _) in enumerate(sections) if sid == "kruisverband"), len(sections))
        for item in reversed(extra_sections):
            sections.insert(insert_idx, item)
    return "".join(
        f'<a class="{cls}" data-scroll="{sid}">{lbl}</a>'
        for sid, lbl, cls in sections
    )


# ─── Brent chart data ────────────────────────────────────────────────────────
def render_brent_script(plan: dict) -> str:
    trend = plan.get("widgets", {}).get("brent_trend", [])
    brent_js = ""
    if trend:
        brent_js = f"""
  var canvas = document.getElementById('brent-chart');
  if (canvas && typeof Chart !== 'undefined') {{
    new Chart(canvas, {{
      type: 'line',
      data: {{
        labels: {json.dumps([str(i+1) for i in range(len(trend))])},
        datasets: [{{data: {json.dumps(trend)}, borderColor:'#f59e0b',borderWidth:2,pointRadius:0,fill:false,tension:.4}}]
      }},
      options: {{plugins:{{legend:{{display:false}}}},scales:{{x:{{display:false}},y:{{display:false}}}}}}
    }});
  }}"""

    return f"""
<script>
// ─── Brent chart ──────────────────────────────────────────────────────────
(function(){{{brent_js}
}})();

// ─── API server auto-herstart ──────────────────────────────────────────────
// Probeert de api_server te starten via het Obsidian app-object (Node.js context)
function _startApiServer(onDone) {{
  try {{
    var spawn = require('child_process').spawn;
    var home  = process.env.HOME || '/home/marcel';
    var check = spawn('nc', ['-z', '-w1', '127.0.0.1', '7432'], {{ stdio: 'ignore' }});
    check.on('close', function(code) {{
      if (code !== 0) {{
        var proc = spawn('python3', [home + '/nieuwsstation/src/api_server.py'], {{
          detached: true, stdio: 'ignore',
          env: Object.assign({{}}, process.env, {{ PYTHONUNBUFFERED: '1' }})
        }});
        proc.unref();
        // Geef server 2 seconden om op te starten
        setTimeout(onDone, 2000);
      }} else {{
        onDone();
      }}
    }});
    check.on('error', function() {{ onDone(); }});
  }} catch(err) {{
    // Niet in Node.js context (bijv. externe browser) — skip
    onDone();
  }}
}}

// ─── Hulpfuncties voor artikelen ──────────────────────────────────────────
function _esc(s) {{
  return (s || '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function _buildRelatedHtml(tag, currentUrl) {{
  if (!window.DAGKRANT_ARTICLES || !tag) return '';
  var rel = DAGKRANT_ARTICLES.filter(function(a) {{
    return a.tag === tag && a.url !== currentUrl && a.titel;
  }}).slice(0, 4);
  if (!rel.length) return '';
  var items = rel.map(function(a) {{
    return '<div style="padding:.45rem 0;border-bottom:1px solid var(--border)">'
      + '<a href="#" onclick="_openReaderFromMeta(this);return false;"'
      + ' data-url="' + _esc(a.url) + '"'
      + ' data-title="' + _esc(a.titel) + '"'
      + ' data-teaser="' + _esc(a.teaser) + '"'
      + ' data-bron="' + _esc(a.bron) + '"'
      + ' data-datum="' + _esc(a.datum) + '"'
      + ' data-tag="' + _esc(a.tag) + '"'
      + ' style="color:var(--t1);text-decoration:none;font-size:.82rem;line-height:1.35;display:block">'
      + a.titel
      + '</a>'
      + '<div style="font-size:.7rem;color:var(--t3);margin-top:.1rem">' + (a.bron || '') + '</div>'
      + '</div>';
  }}).join('');
  return '<div style="padding:.8rem 1.6rem 1.5rem">'
    + '<div style="font-size:.7rem;color:var(--t3);font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.5rem">Vergelijkbare artikelen</div>'
    + items + '</div>';
}}

function _openReaderFromMeta(el) {{
  var fake = document.createElement('div');
  fake.setAttribute('data-reader-url',    el.getAttribute('data-url'));
  fake.setAttribute('data-reader-title',  el.getAttribute('data-title'));
  fake.setAttribute('data-reader-teaser', el.getAttribute('data-teaser'));
  fake.setAttribute('data-reader-bron',   el.getAttribute('data-bron'));
  fake.setAttribute('data-reader-datum',  el.getAttribute('data-datum'));
  fake.setAttribute('data-reader-tag',    el.getAttribute('data-tag'));
  openReader(fake, null);
}}

// ─── Achtergrond vanuit reader (companion panel) ───────────────────────────
function _openReaderBgFromReader() {{
  if (!_readerCurTitle) return;

  // Toggle: als al open, sluit het
  if (_readerBgPanel) {{ _closeReaderBg(); return; }}

  var title   = _readerCurTitle;
  var summary = _readerCurTeaser;
  var tag     = _readerCurTag;
  var url     = _readerCurUrl;

  // Verwante artikelen (zelfde sectie)
  var related = [];
  if (window.DAGKRANT_ARTICLES && tag) {{
    related = DAGKRANT_ARTICLES
      .filter(function(a) {{ return a.tag === tag && a.url !== url && a.titel; }})
      .slice(0, 5)
      .map(function(a) {{ return {{title: a.titel, summary: a.teaser, url: a.url}}; }});
  }}

  // Bouw companion panel — verschijnt links van de reader
  _readerBgPanel = document.createElement('div');
  _readerBgPanel.setAttribute('data-companion-panel', '1');
  _readerBgPanel.className = 'bg-panel-left';
  _readerBgPanel.innerHTML =
    '<div class="bg-panel-header">'
    + '<span>Achtergrond &bull; ' + (tag || 'analyse') + '</span>'
    + '<button class="bg-panel-close" onclick="_closeReaderBg()" title="Sluiten">&times;</button>'
    + '</div>'
    + '<div class="bg-inner" style="padding:1.5rem;text-align:center;color:var(--t3)">'
    + '<p style="font-size:.9rem">\u23f3 Achtergrond wordt gegenereerd\u2026</p>'
    + '<p style="font-size:.75rem;margin-top:.4rem;color:var(--t3)">' + title + '</p>'
    + '</div>';
  document.body.appendChild(_readerBgPanel);
  document.body.classList.add('split');

  // Activeer de reader bg-knop (toon "sluit" state)
  var bgBtn = _readerPanel && _readerPanel.querySelector('.reader-bg-btn');
  if (bgBtn) {{ bgBtn.textContent = '\u2715 Sluit analyse'; }}

  requestAnimationFrame(function() {{
    requestAnimationFrame(function() {{
      if (_readerBgPanel) _readerBgPanel.classList.add('open');
    }});
  }});

  var inner = _readerBgPanel.querySelector('div:last-child');

  fetch('http://127.0.0.1:7432/background', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{title: title, summary: summary, sources: [], related_articles: related}})
  }})
  .then(function(r) {{ return r.json(); }})
  .then(function(data) {{
    if (!_readerBgPanel) return;
    var cur = _readerBgPanel.querySelector('div:last-child');
    if (!cur) return;
    if (data.html) {{
      var archiveBadge = '';
      if (data.archive_hits && data.archive_hits > 0) {{
        archiveBadge = '<p style="margin:.2rem 0 .8rem;font-size:.7rem;color:var(--t3)">'
          + '📚 Historische context uit archief ('
          + data.archive_hits + (data.archive_hits === 1 ? ' dagkrant' : ' dagkranten') + ')</p>';
      }}
      cur.innerHTML =
        '<div style="padding:1.4rem 1.6rem 0">'
        + '<h3 style="margin:0 0 .3rem;line-height:1.3;font-size:1rem">' + title + '</h3>'
        + '<p class="bg-byline" style="margin:.2rem 0 0">Analyse \u00b7 De Dagkrant</p>'
        + archiveBadge
        + '</div>'
        + '<div style="padding:0 1.6rem 2rem">' + data.html + '</div>';
    }} else {{
      cur.innerHTML = '<p style="color:var(--red);padding:1rem">Fout: ' + (data.error || 'onbekend') + '</p>';
    }}
  }})
  .catch(function() {{
    var cur = _readerBgPanel && _readerBgPanel.querySelector('div:last-child');
    if (cur) cur.innerHTML = '<p style="color:var(--red);padding:1rem">\u26a0\ufe0f API niet bereikbaar</p>';
    var bgBtn2 = _readerPanel && _readerPanel.querySelector('.reader-bg-btn');
    if (bgBtn2) {{ bgBtn2.textContent = '\u26a1 Achtergrond'; bgBtn2.disabled = false; }}
  }});
}}

// ─── On-demand achtergrond generatie ──────────────────────────────────────
// Gebruik event-delegatie op document zodat ook gekopieerde buttons werken
function _handleBgGenClick(btn, e) {{
  e.stopPropagation();
  var panelId = btn.getAttribute('data-bgid');
  var title   = btn.getAttribute('data-title');
  var summary = btn.getAttribute('data-summary');
  var tag     = btn.getAttribute('data-tag') || '';
  var srcs    = (btn.getAttribute('data-sources') || '').split(',').filter(Boolean);

  // Verwante artikelen (zelfde sectie, exclusief dit artikel)
  var related = [];
  if (window.DAGKRANT_ARTICLES && tag) {{
    related = DAGKRANT_ARTICLES
      .filter(function(a) {{ return a.tag === tag && a.titel !== title; }})
      .slice(0, 5)
      .map(function(a) {{ return {{title: a.titel, summary: a.teaser, url: a.url}}; }});
  }}

  // Update de bron-panel inner (voor als openBg() later innerHTML kopieert)
  var srcPanel = document.getElementById(panelId);
  var srcInner = srcPanel ? srcPanel.querySelector('.bg-inner') : null;

  btn.disabled = true;
  btn.textContent = '\u23f3 Genereren...';

  // Open het sidebar-panel meteen met laadtekst
  if (typeof openBg === 'function') {{
    openBg(panelId, e);
  }}

  // Vind het actieve inner-element (sidebar of bron-panel)
  var activeInner = (window.bgPanel && window.bgPanel.querySelector('.bg-inner')) || srcInner;

  if (activeInner) {{
    activeInner.innerHTML = '<p style="padding:1.5rem;color:var(--t3);text-align:center">\u23f3 Achtergrond wordt gegenereerd...</p>';
  }}

  fetch('http://127.0.0.1:7432/background', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{title: title, summary: summary, sources: srcs, related_articles: related}})
  }})
  .then(function(r) {{ return r.json(); }})
  .then(function(data) {{
    var archiveBadge2 = (data.archive_hits && data.archive_hits > 0)
      ? '<p style="margin:.1rem 0 .6rem;font-size:.7rem;color:var(--t3)">📚 Historische context uit archief ('
        + data.archive_hits + (data.archive_hits === 1 ? ' dagkrant' : ' dagkranten') + ')</p>'
      : '';
    var html = data.html
      ? '<h4>' + title + '</h4><p class="bg-byline">Analyse \u00b7 De Dagkrant \u00b7 gegenereerd</p>'
        + archiveBadge2 + data.html
      : '<p style="color:var(--red);padding:1rem">Fout: ' + (data.error || 'onbekend') + '</p>';
    if (srcInner) srcInner.innerHTML = html;
    var curInner = window.bgPanel && window.bgPanel.querySelector('.bg-inner');
    if (curInner && curInner !== srcInner) curInner.innerHTML = html;
  }})
  .catch(function() {{
    // Server niet bereikbaar — probeer hem te starten en opnieuw te proberen
    var setMsg = function(html) {{
      if (srcInner) srcInner.innerHTML = html;
      var curInner = window.bgPanel && window.bgPanel.querySelector('.bg-inner');
      if (curInner && curInner !== srcInner) curInner.innerHTML = html;
    }};
    setMsg('<p style="padding:1.5rem;color:var(--t3);text-align:center">\u23f3 API herstart\u2026</p>');
    _startApiServer(function() {{
      fetch('http://127.0.0.1:7432/background', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{title: title, summary: summary, sources: srcs, related_articles: related}})
      }})
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        var html = data.html
          ? '<h4>' + title + '</h4><p class="bg-byline">Analyse \u00b7 De Dagkrant \u00b7 gegenereerd</p>' + data.html
          : '<p style="color:var(--red);padding:1rem">Fout: ' + (data.error || 'onbekend') + '</p>';
        setMsg(html);
        if (srcInner) srcInner.innerHTML = html;
      }})
      .catch(function() {{
        btn.disabled = false;
        btn.textContent = '\u26a0\ufe0f Probeer opnieuw';
        setMsg('<p style="color:var(--red);padding:1rem">&#9888; API niet bereikbaar. Herstart Obsidian of start de server handmatig.</p>');
      }});
    }});
  }});
}}

// Event-delegatie op document
document.addEventListener('click', function(e) {{
  var btn = e.target.closest('.bg-gen-btn');
  if (btn) _handleBgGenClick(btn, e);
}});

// ─── Kruisverband-visualisatie ───────────────────────────────────────────
function generateKruisverbandVisual(e) {{
  var btn = e && e.currentTarget ? e.currentTarget : document.getElementById('viz-kruisverband-btn');
  if (!btn) return;
  var target = document.getElementById('viz-kruisverband-target');
  var dataEl = document.getElementById('kruisverband-data');
  if (!target || !dataEl) return;

  var payload;
  try {{ payload = JSON.parse(dataEl.textContent); }}
  catch (err) {{
    target.innerHTML = '<p style="color:var(--red);font-size:.8rem">Kon data niet lezen.</p>';
    return;
  }}

  btn.disabled = true;
  btn.textContent = '\u23f3 Verbanden worden geanalyseerd...';

  var doFetch = function() {{
    return fetch('http://127.0.0.1:7432/kruisverband-visual', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(payload)
    }}).then(function(r) {{ return r.json(); }});
  }};

  doFetch()
    .then(function(data) {{
      if (data && data.visual_html) {{
        target.innerHTML = data.visual_html;
        btn.style.display = 'none';
        // Chart.js re-init indien nodig (voor dynamisch toegevoegde canvas)
        if (typeof Chart !== 'undefined') {{
          var scripts = target.querySelectorAll('script');
          scripts.forEach(function(s) {{
            try {{ (new Function(s.textContent))(); }} catch (e) {{}}
          }});
        }}
      }} else {{
        btn.disabled = false;
        btn.textContent = '\u26a0\ufe0f Probeer opnieuw';
        target.innerHTML = '<p style="color:var(--red);font-size:.8rem;padding:.5rem">Fout: ' + ((data && data.error) || 'onbekend') + '</p>';
      }}
    }})
    .catch(function() {{
      // API niet bereikbaar — probeer server te starten
      target.innerHTML = '<p style="color:var(--t3);font-size:.8rem">\u23f3 API herstart...</p>';
      if (typeof _startApiServer === 'function') {{
        _startApiServer(function() {{
          doFetch()
            .then(function(data) {{
              if (data && data.visual_html) {{
                target.innerHTML = data.visual_html;
                btn.style.display = 'none';
              }} else {{
                btn.disabled = false;
                btn.textContent = '\u26a0\ufe0f Probeer opnieuw';
                target.innerHTML = '<p style="color:var(--red);font-size:.8rem">Fout bij genereren.</p>';
              }}
            }})
            .catch(function() {{
              btn.disabled = false;
              btn.textContent = '\u26a0\ufe0f Probeer opnieuw';
              target.innerHTML = '<p style="color:var(--red);font-size:.8rem">API niet bereikbaar.</p>';
            }});
        }});
      }} else {{
        btn.disabled = false;
        btn.textContent = '\u26a0\ufe0f Probeer opnieuw';
      }}
    }});
}}

// ─── Artikel reader-panel ──────────────────────────────────────────────────
var _readerPanel = null;
var _readerBgPanel = null;     // achtergrond companion panel (naast reader)
var _readerOrigHtml  = null;   // originele artikel-HTML
var _readerTransHtml = null;   // vertaalde HTML (null = nog niet vertaald)
var _readerTranslated = false; // huidige weergave: vertaald?
// huidig artikel-meta (voor achtergrondknop in reader)
var _readerCurTitle  = '';
var _readerCurTeaser = '';
var _readerCurTag    = '';
var _readerCurUrl    = '';

function _closeReaderBg() {{
  if (_readerBgPanel) {{
    _readerBgPanel.classList.remove('open');
    var p = _readerBgPanel;
    _readerBgPanel = null;
    if (!bgPanel) document.body.classList.remove('split');
    setTimeout(function() {{ if (p && p.parentNode) p.parentNode.removeChild(p); }}, 350);
  }}
}}

function _closeReader() {{
  _closeReaderBg();
  if (_readerPanel) {{
    _readerPanel.classList.remove('open');
    setTimeout(function() {{
      if (_readerPanel && _readerPanel.parentNode)
        _readerPanel.parentNode.removeChild(_readerPanel);
      _readerPanel = null;
    }}, 350);
  }}
  _readerOrigHtml = _readerTransHtml = null;
  _readerTranslated = false;
}}

// YouTube links in achtergrond-panels: open als popup met ondertiteling
document.addEventListener('click', function(e) {{
  var a = e.target.closest('a[href*="youtube.com/watch"]');
  if (!a) return;
  // alleen als het in een panel staat
  if (!a.closest('.bg-panel') && !a.closest('[data-companion-panel]')) return;
  e.preventDefault();
  var href = a.getAttribute('href') || '';
  var sep = href.includes('?') ? '&' : '?';
  var ytUrl = href + sep + 'cc_load_policy=1&cc_lang_pref=nl';
  window.open(ytUrl, 'ytplayer', 'width=1366,height=768,top=0,left=0,resizable=yes,scrollbars=no');
}});

function _readerContentEl() {{
  return _readerPanel && _readerPanel.querySelector('.reader-article-body');
}}

function _toggleTranslate() {{
  var btn = _readerPanel && _readerPanel.querySelector('.reader-translate-btn');
  var body = _readerContentEl();
  if (!body || !btn) return;

  // Toggle als beide versies beschikbaar zijn
  if (_readerTransHtml !== null) {{
    _readerTranslated = !_readerTranslated;
    body.innerHTML = _readerTranslated ? _readerTransHtml : _readerOrigHtml;
    btn.textContent = _readerTranslated ? '🔤 Origineel' : '🌐 Vertaal NL';
    btn.title = _readerTranslated ? 'Toon originele taal' : 'Vertaal naar Nederlands';
    return;
  }}

  // Eerste keer vertalen
  if (_readerOrigHtml === null) return;
  btn.disabled = true;
  btn.textContent = '\u23f3\u2026';
  fetch('http://127.0.0.1:7432/translate', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{html: _readerOrigHtml}})
  }})
  .then(function(r) {{ return r.json(); }})
  .then(function(data) {{
    btn.disabled = false;
    if (data.already_dutch) {{
      btn.textContent = '\u2713 NL';
      btn.title = 'Artikel is al in het Nederlands';
      btn.style.opacity = '0.5';
      return;
    }}
    if (data.html) {{
      _readerTransHtml = data.html;
      _readerTranslated = true;
      var body2 = _readerContentEl();
      if (body2) body2.innerHTML = _readerTransHtml;
      btn.textContent = '🔤 Origineel';
      btn.title = 'Toon originele taal';
    }} else {{
      btn.textContent = '\u26a0\ufe0f Fout';
    }}
  }})
  .catch(function() {{
    btn.disabled = false;
    btn.textContent = '\u26a0\ufe0f Fout';
  }});
}}

function openReader(card, e) {{
  if (e) e.stopPropagation();
  // Negeer klik op bg-badge knop
  if (e && e.target.closest('.bg-badge, .bg-gen-btn')) return;

  var url    = card.getAttribute('data-reader-url');
  var title  = card.getAttribute('data-reader-title');
  var teaser = card.getAttribute('data-reader-teaser');
  var bron   = card.getAttribute('data-reader-bron');
  var datum  = card.getAttribute('data-reader-datum');
  var tag    = card.getAttribute('data-reader-tag');

  // Verwijder bestaand panel
  _closeReader();
  // Sluit ook bg-panel als open
  if (typeof closeBgPanel === 'function') closeBgPanel();

  // Sla artikel meta op voor bg-knop
  _readerCurTitle  = title;
  _readerCurTeaser = teaser;
  _readerCurTag    = tag;
  _readerCurUrl    = url;

  // Bouw reader panel — knoppen rechtsboven in header
  _readerPanel = document.createElement('div');
  _readerPanel.className = 'bg-panel';
  _readerPanel.innerHTML =
    '<div class="bg-panel-header">'
    + '<span>' + (bron || 'Artikel') + '</span>'
    + '<div style="display:flex;align-items:center;gap:.4rem">'
    + '<button class="reader-bg-btn" onclick="_openReaderBgFromReader()" title="Genereer achtergrond analyse"'
    + ' style="background:var(--accent);border:none;border-radius:4px;'
    + 'padding:.25rem .6rem;font-size:.72rem;cursor:pointer;color:#fff;opacity:0.4"'
    + ' disabled>\u26a1 Achtergrond</button>'
    + '<button class="reader-translate-btn" onclick="_toggleTranslate()" title="Vertaal naar Nederlands"'
    + ' style="background:var(--bg3);border:1px solid var(--border);border-radius:4px;'
    + 'padding:.25rem .6rem;font-size:.72rem;cursor:pointer;color:var(--t2);opacity:0.4"'
    + ' disabled>🌐 Vertaal NL</button>'
    + '<button class="bg-panel-close" onclick="_closeReader()" title="Sluiten">&times;</button>'
    + '</div>'
    + '</div>'
    + '<div class="bg-inner reader-inner">'
    + '<p style="padding:2rem;text-align:center;color:var(--t3)">\u23f3 Artikel laden\u2026</p>'
    + '</div>';
  document.body.appendChild(_readerPanel);
  requestAnimationFrame(function() {{ _readerPanel.classList.add('open'); }});

  var inner = _readerPanel.querySelector('.reader-inner');

  // Toon alvast de bestaande data
  inner.innerHTML =
    '<div style="padding:1.4rem 1.6rem">'
    + (tag ? '<span class="tag tag-' + tag + '" style="font-size:.65rem;padding:.2rem .6rem">' + tag + '</span>' : '')
    + '<h3 style="margin:.8rem 0 .4rem;line-height:1.3">' + title + '</h3>'
    + '<div class="meta" style="margin-bottom:1rem">' + (bron || '') + (datum ? ' \u2022 ' + datum : '') + '</div>'
    + '<p style="color:var(--t2);line-height:1.6">' + teaser + '</p>'
    + '<hr style="margin:1.2rem 0;border:none;border-top:1px solid var(--border)">'
    + '<p style="color:var(--t3);font-size:.85rem;text-align:center">\u23f3 Volledige artikel ophalen\u2026</p>'
    + '</div>';

  if (!url) return;

  // Haal volledig artikel op via api_server
  fetch('http://127.0.0.1:7432/article', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{url: url, title: title}})
  }})
  .then(function(r) {{ return r.json(); }})
  .then(function(data) {{
    if (!_readerPanel) return;
    var curInner = _readerPanel.querySelector('.reader-inner');
    if (!curInner) return;
    if (data.html) {{
      // Sla originele HTML op voor vertaal-toggle
      _readerOrigHtml = data.html;
      _readerTransHtml = null;
      _readerTranslated = false;

      curInner.innerHTML =
        '<div style="padding:1.4rem 1.6rem 0">'
        + (tag ? '<span class="tag tag-' + tag + '" style="font-size:.65rem;padding:.2rem .6rem">' + tag + '</span>' : '')
        + '<h3 style="margin:.8rem 0 .4rem;line-height:1.3">' + title + '</h3>'
        + '<div class="meta" style="margin-bottom:1.2rem">' + (bron || '') + (datum ? ' \u2022 ' + datum : '') + '</div>'
        + '</div>'
        + '<div class="reader-article-body" style="padding:0 1.6rem 2rem" class="article-reader-content">'
        + data.html
        + '</div>'
        + _buildRelatedHtml(tag, url);

      // Activeer de knoppen
      var tBtn = _readerPanel.querySelector('.reader-translate-btn');
      if (tBtn) {{ tBtn.disabled = false; tBtn.style.opacity = '1'; }}
      var bgBtn = _readerPanel.querySelector('.reader-bg-btn');
      if (bgBtn) {{ bgBtn.disabled = false; bgBtn.style.opacity = '1'; }}
    }} else {{
      curInner.innerHTML =
        '<div style="padding:1.4rem 1.6rem">'
        + '<h3 style="margin:0 0 .8rem">' + title + '</h3>'
        + '<p style="color:var(--t2)">' + teaser + '</p>'
        + '<p style="color:var(--t3);font-size:.85rem;margin-top:1rem">'
        + (data.error || 'Artikel kon niet worden geladen.') + '</p>'
        + (url ? '<p><a href="' + url + '" target="_blank" style="color:var(--accent)">Open in browser \u2197</a></p>' : '')
        + '</div>';
    }}
  }})
  .catch(function() {{
    if (!_readerPanel) return;
    var curInner = _readerPanel.querySelector('.reader-inner');
    if (curInner) curInner.innerHTML =
      '<div style="padding:1.4rem 1.6rem">'
      + '<p style="color:var(--t3);font-size:.85rem">\u23f3 API herstart\u2026</p>'
      + '</div>';
    _startApiServer(function() {{
      fetch('http://127.0.0.1:7432/article', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{url: url, title: title}})
      }})
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{
        if (!_readerPanel) return;
        var curInner2 = _readerPanel.querySelector('.reader-inner');
        if (!curInner2) return;
        if (data.html) {{
          _readerOrigHtml = data.html;
          _readerTransHtml = null;
          _readerTranslated = false;
          curInner2.innerHTML =
            '<div style="padding:1.4rem 1.6rem 0">'
            + (tag ? '<span class="tag tag-' + tag + '" style="font-size:.65rem;padding:.2rem .6rem">' + tag + '</span>' : '')
            + '<h3 style="margin:.8rem 0 .4rem;line-height:1.3">' + title + '</h3>'
            + '<div class="meta" style="margin-bottom:1.2rem">' + (bron || '') + (datum ? ' \u2022 ' + datum : '') + '</div>'
            + '</div>'
            + '<div class="reader-article-body" style="padding:0 1.6rem 2rem">'
            + data.html + '</div>'
            + _buildRelatedHtml(tag, url);
          var tBtn2 = _readerPanel && _readerPanel.querySelector('.reader-translate-btn');
          if (tBtn2) {{ tBtn2.disabled = false; tBtn2.style.opacity = '1'; }}
          var bgBtn2 = _readerPanel && _readerPanel.querySelector('.reader-bg-btn');
          if (bgBtn2) {{ bgBtn2.disabled = false; bgBtn2.style.opacity = '1'; }}
        }} else {{
          curInner2.innerHTML =
            '<div style="padding:1.4rem 1.6rem">'
            + '<h3 style="margin:0 0 .8rem">' + title + '</h3>'
            + '<p style="color:var(--t2)">' + teaser + '</p>'
            + (url ? '<p><a href="' + url + '" target="_blank" style="color:var(--accent)">Open in browser \u2197</a></p>' : '')
            + '</div>';
        }}
      }})
      .catch(function() {{
        if (!_readerPanel) return;
        var curInner2 = _readerPanel.querySelector('.reader-inner');
        if (curInner2) curInner2.innerHTML =
          '<div style="padding:1.4rem 1.6rem">'
          + '<h3 style="margin:0 0 .8rem">' + title + '</h3>'
          + '<p style="color:var(--t2)">' + teaser + '</p>'
          + (url ? '<p><a href="' + url + '" target="_blank" style="color:var(--accent)">Open in browser \u2197</a></p>' : '')
          + '</div>';
      }});
    }});
  }});
}}
</script>"""


# ─── Topnieuws grid ──────────────────────────────────────────────────────────
def render_topnieuws(items: list) -> str:
    if not items:
        return ""
    visible   = items[:3]
    extra     = items[3:6]
    cards_vis = "\n".join(render_article_card(a) for a in visible)
    more_btn  = (f'<button class="more-btn" id="morebtn-topnieuws" '
                 f'onclick="toggleMore(\'topnieuws\')" title="Meer artikelen">meer &#9662;</button>'
                 if extra else "")
    extra_html = ""
    if extra:
        extra_cards = "\n".join(render_article_card(a) for a in extra)
        extra_html = f'\n<div class="extra-cards" id="more-topnieuws">\n{extra_cards}\n</div>'
    return f"""
<hr class="section-sep" id="topnieuws"/>
<div class="section-head">
  <span class="tag">Topnieuws</span>
  <h2>Topnieuws</h2>
  <div class="section-line"></div>
  {more_btn}
</div>
<div class="article-grid topnieuws-grid">
{cards_vis}{extra_html}
</div>"""


# ─── Archief digest ──────────────────────────────────────────────────────────
def write_digest(plan: dict, datum_iso: str, path: Path) -> None:
    """
    Schrijf een compact doorzoekbaar markdown-digest van de dagkrant.
    Dit bestand wordt door vault_search gebruikt als historisch archief.
    """
    maanden = ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"]
    try:
        d = datetime.fromisoformat(datum_iso)
        datum_nl = f"{d.day} {maanden[d.month-1]} {d.year}"
    except Exception:
        datum_nl = datum_iso

    lines = [
        f"---",
        f"date: {datum_iso}",
        f"type: dagkrant-digest",
        f"tags: [dagkrant, nieuws]",
        f"---",
        f"",
        f"# Dagkrant — {datum_nl}",
        f"",
    ]

    # Breaking news
    breaking = plan.get("breaking", [])
    if breaking:
        lines.append("## Breaking")
        for b in breaking:
            lines.append(f"- {b}")
        lines.append("")

    # Helper: artikel naar bullet
    def art_line(a: dict) -> str:
        t = a.get("titel", "")
        teaser = a.get("teaser", "")
        bron = (a.get("bronnen") or [{}])[0].get("naam", "")
        parts = [f"**{t}**"]
        if bron:
            parts.append(f"({bron})")
        if teaser:
            parts.append(f"— {teaser}")
        return "- " + " ".join(parts)

    # Hero
    hero = plan.get("hero")
    if hero:
        lines.append("## Hero")
        lines.append(art_line(hero))
        body = hero.get("body_md", "")
        if body:
            lines.append(f"  {body[:300]}")
        lines.append("")

    # Topnieuws
    topnieuws = plan.get("topnieuws", [])
    if topnieuws:
        lines.append("## Topnieuws")
        for a in topnieuws:
            lines.append(art_line(a))
        lines.append("")

    # Secties (inclusief specialist + custom)
    sectie_labels = {
        "nederland": "Nederland", "wereld": "Wereld",
        "financieel": "Financieel", "sport": "Sport", "aitech": "AI & Tech",
        "voetbal": "Voetbal", "regulatoir": "Regulatoir", "huizenmarkt": "Huizenmarkt",
    }
    # Voeg dynamisch toe wat in het plan staat maar niet in de standaard map
    for sid in plan.get("secties", {}):
        if sid not in sectie_labels:
            sectie_labels[sid] = sid.replace("_dk", "").replace("_", " ").title()
    for sid, label in sectie_labels.items():
        arts = plan.get("secties", {}).get(sid, {}).get("artikelen", [])
        if arts:
            lines.append(f"## {label}")
            for a in arts:
                lines.append(art_line(a))
            lines.append("")

    # Kruisverband analyse
    kruisverband = plan.get("kruisverband_md", "")
    if kruisverband:
        lines.append("## Analyse")
        lines.append(kruisverband)
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


# ─── Main render ─────────────────────────────────────────────────────────────
def render(plan: dict, template: str) -> str:
    w = plan.get("widgets", {})
    now = datetime.now()

    # Navigatie — wordt later bijgewerkt als we custom secties kennen
    nav_items = None  # placeholder

    # Breaking banner
    breaking_items = plan.get("breaking", [])
    breaking_text  = " &bull; ".join(breaking_items) if breaking_items else "De Dagkrant"

    # Alle artikelen voor bg-panels
    all_articles = []
    if plan.get("hero"):
        all_articles.append(plan["hero"])
    all_articles.extend(plan.get("topnieuws", []))
    for sec in plan.get("secties", {}).values():
        all_articles.extend(sec.get("artikelen", []))

    bg_panels = "\n".join(render_bg_panel(a) for a in all_articles)

    # Content block
    secties = plan.get("secties", {})
    content_parts = []

    if plan.get("hero"):
        content_parts.append(render_hero(plan["hero"]))

    if plan.get("topnieuws"):
        content_parts.append(render_topnieuws(plan["topnieuws"]))

    # Vaste secties
    CUSTOM_SECTION_LABELS = {
        "voetbal":     "Voetbal",
        "regulatoir":  "Regulatoir",
        "huizenmarkt": "Huizenmarkt",
    }
    sec_config = [
        ("nederland",    "Nederland",     "nederland"),
        ("wereld",       "Wereld",        "wereld"),
        ("financieel",   "Financieel",    "financieel"),
        ("regulatoir",   "Regulatoir",    "regulatoir"),
        ("huizenmarkt",  "Huizenmarkt",   "huizenmarkt"),
        ("sport",        "Sport",         "sport"),
        ("aitech",       "AI &amp; Tech", "aitech"),
        ("ai_tech",      "AI &amp; Tech", "aitech"),
    ]
    # Voeg custom/extra secties toe die in het plan staan maar niet in sec_config
    known_sids = {sid for sid, _, _ in sec_config}
    extra_nav = []
    for sid in secties:
        if sid not in known_sids:
            label = CUSTOM_SECTION_LABELS.get(sid, sid.replace("_dk", "").replace("_", " ").title())
            sec_config.append((sid, label, sid))
            extra_nav.append((sid, label, ""))

    # Navigatie met eventuele custom secties
    nav_items = render_nav(extra_nav if extra_nav else None)

    rendered_secs = set()
    for sid, label, tag_cls in sec_config:
        if sid in secties and sid not in rendered_secs:
            sec_data = secties[sid]
            if sid == "financieel":
                content_parts.append(render_financieel_section(sec_data, plan.get("widgets", {})))
            else:
                content_parts.append(render_section(sid, label, tag_cls, sec_data.get("artikelen", [])))
            rendered_secs.add(sid)

    content_parts.append(render_kruisverband(plan))
    content_parts.append(bg_panels)

    content = "\n".join(content_parts)

    # Source list
    bronnen_lijst = plan.get("bronnen_lijst", [])
    source_list = " &bull; ".join(bronnen_lijst) if bronnen_lijst else ""

    # Brent chart
    brent_script = render_brent_script(plan)

    # Template placeholders invullen
    html = template
    html = html.replace("{{DATE_LONG}}",   plan.get("datum", ""))
    html = html.replace("{{WEATHER_TEMP}}", w.get("weer_temp", ""))
    html = html.replace("{{WEATHER_ICON}}", w.get("weer_icon", ""))
    html = html.replace("{{NAV_ITEMS}}",   nav_items)
    html = html.replace("{{BREAKING_TEXT}}", breaking_text)
    html = html.replace("{{CONTENT}}",    content)
    html = html.replace("{{TIME}}",       plan.get("tijd", now.strftime("%H:%M")))
    html = html.replace("{{TIMEZONE}}",   plan.get("tijdzone", "CET"))
    html = html.replace("{{SOURCE_LIST}}", source_list)

    # Brent chart script vóór </body>
    if brent_script:
        html = html.replace("</body>", brent_script + "\n</body>")

    # Animatie-init: count-up voor stat-cards + Chart.js defaults
    anim_js = """<script>
(function(){
  // ── Count-up voor .ns-viz-count[data-target] ──────────────────────────
  function animateCount(el){
    var raw=el.dataset.target||'0';
    var target=parseFloat(raw.replace(',','.'));
    var suffix=el.dataset.suffix||'';
    var prefix=el.dataset.prefix||'';
    var dec=(raw.includes('.')||raw.includes(','))?(raw.split(/[.,]/)[1]||'').length:0;
    var dur=1100,st=null;
    function step(ts){
      if(!st)st=ts;
      var p=Math.min((ts-st)/dur,1),ease=1-Math.pow(1-p,3);
      el.textContent=prefix+(target*ease).toFixed(dec)+suffix;
      if(p<1)requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  function initCounters(root){
    (root||document).querySelectorAll('.ns-viz-count[data-target]').forEach(function(el){
      if(el._counted)return;
      if('IntersectionObserver' in window){
        new IntersectionObserver(function(ens,obs){
          ens.forEach(function(e){if(e.isIntersecting&&!e.target._counted){e.target._counted=true;obs.disconnect();animateCount(e.target);}});
        },{threshold:.4}).observe(el);
      } else { el._counted=true; animateCount(el); }
    });
  }
  initCounters();
  // Herinitialiseer voor dynamisch toegevoegde visuals (achtergrondartikelen)
  new MutationObserver(function(muts){
    muts.forEach(function(m){m.addedNodes.forEach(function(n){if(n.querySelectorAll)initCounters(n);});});
  }).observe(document.body,{childList:true,subtree:true});

  // ── Chart.js annotation plugin registreren ────────────────────────────
  if(typeof Chart!=='undefined'&&typeof ChartAnnotation!=='undefined'){
    Chart.register(ChartAnnotation);
  }
})();
</script>"""
    html = html.replace("</body>", anim_js + "\n</body>")

    # Artikel metadata JS-variabele voor vergelijkbare artikelen + verwante bg-analyse
    meta_list = []
    for a in all_articles:
        bronnen_a = a.get("bronnen", [{}])
        meta_list.append({
            "id":    a.get("id", ""),
            "titel": a.get("titel", ""),
            "teaser": a.get("teaser", ""),
            "url":   (bronnen_a[0] if bronnen_a else {}).get("url", ""),
            "tag":   a.get("tag", ""),
            "bron":  (bronnen_a[0] if bronnen_a else {}).get("naam", ""),
            "datum": a.get("datum", ""),
        })
    meta_js = (
        "<script>var DAGKRANT_ARTICLES="
        + json_mod.dumps(meta_list, ensure_ascii=False)
        + ";</script>"
    )
    html = html.replace("</body>", meta_js + "\n</body>")

    return html


def render_sections_only(plan: dict) -> str:
    """
    Render alleen de secties uit het plan als HTML-fragmenten (voor append-modus).
    Geeft de gecombineerde HTML terug van alle secties in plan['secties'].
    """
    CUSTOM_SECTION_LABELS = {"voetbal": "Voetbal"}
    secties = plan.get("secties", {})
    nl_content = {}  # al verwerkt in plan

    parts = []
    for sid, sec_data in secties.items():
        artikelen = sec_data.get("artikelen", [])
        if not artikelen:
            continue
        label = CUSTOM_SECTION_LABELS.get(sid, sid.replace("_dk", "").replace("_", " ").title())
        if sid == "financieel":
            parts.append(render_financieel_section(sec_data, plan.get("widgets", {})))
        else:
            parts.append(render_section(sid, label, sid, artikelen))

    all_arts = []
    for sec_data in secties.values():
        all_arts.extend(sec_data.get("artikelen", []))
    if all_arts:
        parts.append("\n".join(render_bg_panel(a) for a in all_arts))

    return "\n".join(parts)


def append_sections_to_html(existing_html: str, new_sections_html: str, plan: dict) -> str:
    """
    Voeg nieuwe secties-HTML in vóór het kruisverband-blok in de bestaande dagkrant.
    Werkt ook nieuwe bg-panels en nav-links bij.
    """
    # Marker voor injectie: vlak voor kruisverband separator
    marker = '<hr class="section-sep" id="kruisverband"/>'
    if marker in existing_html:
        existing_html = existing_html.replace(marker, new_sections_html + "\n" + marker)
    else:
        # Fallback: vóór </main> of </body>
        for end_tag in ("</main>", "</body>"):
            if end_tag in existing_html:
                existing_html = existing_html.replace(end_tag, new_sections_html + "\n" + end_tag)
                break

    # Voeg nav-links toe voor de nieuwe secties (vóór Analyse-link)
    CUSTOM_SECTION_LABELS = {"voetbal": "Voetbal"}
    for sid in plan.get("secties", {}):
        nav_marker = f'data-scroll="{sid}"'
        if nav_marker not in existing_html:
            label = CUSTOM_SECTION_LABELS.get(sid, sid.replace("_dk", "").replace("_", " ").title())
            new_nav = f'<a class="" data-scroll="{sid}">{label}</a>'
            analyse_nav = 'data-scroll="kruisverband"'
            if analyse_nav in existing_html:
                existing_html = existing_html.replace(
                    f'data-scroll="kruisverband"',
                    f'{new_nav[:-4]} data-scroll="kruisverband"'
                    # Safer: insert full link before kruisverband
                )
                # Simpler approach: find the <a> containing kruisverband and insert before it
                existing_html = existing_html.replace(
                    f'{new_nav[:-4]} data-scroll="kruisverband"',
                    f'data-scroll="kruisverband"',
                )
                # Actually insert properly
                kruis_link_pattern = re.compile(r'(<a[^>]*data-scroll="kruisverband"[^>]*>[^<]*</a>)')
                existing_html = kruis_link_pattern.sub(new_nav + r'\1', existing_html, count=1)

    return existing_html


def main():
    plan_path = PLAN_FILE
    if len(sys.argv) > 1:
        plan_path = Path(sys.argv[1])

    if not plan_path.exists():
        print(f"[renderer] FOUT: {plan_path} niet gevonden", file=sys.stderr)
        sys.exit(1)

    if not TEMPLATE.exists():
        print(f"[renderer] FOUT: template niet gevonden: {TEMPLATE}", file=sys.stderr)
        sys.exit(1)

    raw = plan_path.read_text()

    # JSON extractie (veilig, ook als Claude iets extra's schrijft)
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            plan = json.loads(match.group())
        else:
            print(f"[renderer] FOUT: geen geldig JSON gevonden in {plan_path}", file=sys.stderr)
            sys.exit(1)

    import os as _os
    datum_iso = plan.get("datum_iso") or datetime.now().strftime("%Y-%m-%d")
    output    = BRIEFINGS / f"{datum_iso}-dagkrant.html"
    append_mode = _os.environ.get("DAGKRANT_APPEND_MODE", "") == "true"

    if append_mode and output.exists():
        # Append-modus: voeg alleen nieuwe secties toe aan bestaand bestand
        existing_html   = output.read_text(encoding="utf-8")
        new_secs_html   = render_sections_only(plan)
        updated_html    = append_sections_to_html(existing_html, new_secs_html, plan)
        output.write_text(updated_html, encoding="utf-8")
        print(f"[renderer] Sectie(s) toegevoegd aan: {output} ({len(updated_html)//1024}KB)")
    else:
        template = TEMPLATE.read_text()
        html     = render(plan, template)
        output.write_text(html, encoding="utf-8")
        print(f"[renderer] Dagkrant geschreven: {output} ({len(html)//1024}KB)")

    # Schrijf/update doorzoekbaar markdown digest voor archief
    digest_path = BRIEFINGS / f"{datum_iso}-dagkrant.md"
    write_digest(plan, datum_iso, digest_path)
    print(f"[renderer] Digest geschreven: {digest_path}")


if __name__ == "__main__":
    main()
