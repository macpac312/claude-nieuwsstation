#!/usr/bin/env python3
"""
Genereer retroactieve markdown-digests van bestaande HTML-dagkranten.
Deze .md bestanden worden door vault_search gebruikt als historisch archief.

Gebruik:
    python3 retroactive_digests.py
"""
import json
import re
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

BRIEFINGS = Path.home() / "Documents/WorkMvMOBS/Briefings"
MAANDEN = ["jan","feb","mrt","apr","mei","jun","jul","aug","sep","okt","nov","dec"]

TAG_LABELS = {
    "nederland": "Nederland", "wereld": "Wereld",
    "financieel": "Financieel", "sport": "Sport", "aitech": "AI & Tech",
}


def datum_nl(iso: str) -> str:
    try:
        from datetime import date
        d = date.fromisoformat(iso)
        return f"{d.day} {MAANDEN[d.month-1]} {d.year}"
    except Exception:
        return iso


def extract_from_html(html_path: Path) -> dict | None:
    """Extraheer artikeldata uit dagkrant HTML (nieuw én oud formaat)."""
    content = html_path.read_text(encoding="utf-8", errors="ignore")

    result = {"articles": [], "breaking": [], "kruisverband": ""}

    # ── Nieuw formaat: DAGKRANT_ARTICLES JS array (aanwezig vanaf ~april 2026) ──
    m = re.search(r'var DAGKRANT_ARTICLES=(\[[\s\S]*?\]);', content)
    if m:
        try:
            result["articles"] = json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    if HAS_BS4:
        soup = BeautifulSoup(content, "html.parser")

        # Breaking news
        breaking_div = soup.find(id="breaking")
        if breaking_div:
            text_el = breaking_div.find(class_="breaking-text")
            if text_el:
                raw = text_el.get_text().strip()
                result["breaking"] = [b.strip() for b in raw.split("•") if b.strip()]

        # Kruisverband/analyse
        for sel in ["#kruisverband", ".kruisverband-body", ".analyse-body"]:
            el = soup.select_one(sel)
            if el:
                result["kruisverband"] = el.get_text(separator=" ").strip()[:600]
                break

        # ── Oud formaat: h2/h3 structuur (voor april 2026) ──
        if not result["articles"]:
            SECTIE_H2 = {"wereld", "nederland", "financieel", "sport", "regulatoir",
                         "regulatoir & toezicht", "financieel & markten", "ai & technologie"}
            current_tag = "wereld"
            article_id = 0

            # Hero: eerste grote h2 die geen sectienaam is
            for h2 in soup.find_all("h2"):
                txt = h2.get_text().strip()
                if txt.lower() not in SECTIE_H2 and len(txt) > 15:
                    teaser_el = h2.find_next_sibling("p")
                    teaser = teaser_el.get_text()[:200] if teaser_el else ""
                    result["articles"].append({
                        "id": "hero", "titel": txt, "teaser": teaser,
                        "url": "", "tag": "wereld", "bron": "", "datum": "",
                    })
                    break

            # H3 items → sectie-artikelen
            tag_map = {
                "wereld": "wereld", "nederland": "nederland",
                "regulatoir": "financieel", "regulatoir & toezicht": "financieel",
                "financieel": "financieel", "financieel & markten": "financieel",
                "sport": "sport", "ai & technologie": "aitech",
            }
            for el in soup.find_all(["h2", "h3"]):
                tag_name = el.name
                txt = el.get_text().strip()
                if tag_name == "h2" and txt.lower() in tag_map:
                    current_tag = tag_map[txt.lower()]
                    continue
                if tag_name == "h3" and len(txt) > 10:
                    teaser_el = el.find_next_sibling("p")
                    teaser = teaser_el.get_text()[:200] if teaser_el else ""
                    article_id += 1
                    result["articles"].append({
                        "id": f"art{article_id}", "titel": txt, "teaser": teaser,
                        "url": "", "tag": current_tag, "bron": "", "datum": "",
                    })

    return result if result["articles"] else None


def write_digest(datum_iso: str, data: dict, out_path: Path) -> None:
    """Schrijf markdown digest naar disk."""
    articles = data["articles"]
    breaking = data.get("breaking", [])
    kruisverband = data.get("kruisverband", "")

    lines = [
        "---",
        f"date: {datum_iso}",
        "type: dagkrant-digest",
        "tags: [dagkrant, nieuws]",
        "---",
        "",
        f"# Dagkrant — {datum_nl(datum_iso)}",
        "",
    ]

    if breaking:
        lines.append("## Breaking")
        for b in breaking:
            lines.append(f"- {b}")
        lines.append("")

    # Hero
    hero = next((a for a in articles if a.get("id") == "hero"), None)
    if hero:
        lines.append("## Hero")
        lines.append(f"- **{hero['titel']}** ({hero.get('bron','')}) — {hero.get('teaser','')}")
        lines.append("")

    # Topnieuws (articles with id starting with "top")
    topnieuws = [a for a in articles if str(a.get("id","")).startswith("top")]
    if topnieuws:
        lines.append("## Topnieuws")
        for a in topnieuws:
            lines.append(f"- **{a['titel']}** ({a.get('bron','')}) — {a.get('teaser','')}")
        lines.append("")

    # Per sectie
    by_tag: dict[str, list] = {}
    for a in articles:
        tag = a.get("tag", "")
        if tag and str(a.get("id","")) not in ("hero",) and not str(a.get("id","")).startswith("top"):
            by_tag.setdefault(tag, []).append(a)

    for tag, label in TAG_LABELS.items():
        arts = by_tag.get(tag, [])
        if arts:
            lines.append(f"## {label}")
            for a in arts:
                lines.append(f"- **{a['titel']}** ({a.get('bron','')}) — {a.get('teaser','')}")
            lines.append("")

    if kruisverband:
        lines.append("## Analyse")
        lines.append(kruisverband)
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    html_files = sorted(BRIEFINGS.glob("*-dagkrant.html"))
    generated = 0
    skipped = 0

    for html_path in html_files:
        # Datum uit bestandsnaam
        m = re.match(r"(\d{4}-\d{2}-\d{2})-dagkrant\.html", html_path.name)
        if not m:
            continue
        datum_iso = m.group(1)

        digest_path = BRIEFINGS / f"{datum_iso}-dagkrant.md"
        if digest_path.exists():
            print(f"  [skip] {digest_path.name} bestaat al")
            skipped += 1
            continue

        data = extract_from_html(html_path)
        if not data or not data["articles"]:
            print(f"  [warn] Geen artikelen in {html_path.name}")
            continue

        write_digest(datum_iso, data, digest_path)
        n = len(data["articles"])
        print(f"  [OK]   {digest_path.name} — {n} artikelen")
        generated += 1

    print(f"\nKlaar: {generated} nieuw, {skipped} overgeslagen")


if __name__ == "__main__":
    main()
