#!/usr/bin/env python3
"""
Pre-selectie voor dagkrant: kies top N artikelen per sectie.
Input:  /tmp/dagkrant-ready.json
Output: /tmp/dagkrant-selected.json  (~40 artikelen i.p.v. 180)
"""
import json, sys
from pathlib import Path
from datetime import datetime, timezone

INPUT  = Path("/tmp/dagkrant-ready.json")
OUTPUT = Path("/tmp/dagkrant-selected.json")
MAX_PER_SECTION = 6   # max artikelen per topic

# Nederlandse bronnen krijgen hogere prioriteit voor hero/topnieuws-selectie
SOURCE_PRIORITY = {
    # Nederlandse hoofdbronnen — hoogste prioriteit
    "nos.nl": 12, "volkskrant.nl": 11, "fd.nl": 11, "nrc.nl": 10,
    "nu.nl": 9, "rtlnieuws.nl": 8, "ftm.nl": 9, "telegraaf.nl": 6,
    # Regulatoire bronnen (altijd relevant)
    "ecb.europa.eu": 11, "eba.europa.eu": 11, "bis.org": 10, "dnb.nl": 10,
    "afm.nl": 10, "bankingsupervision.europa.eu": 11,
    "calcasa.nl": 9, "nvm.nl": 8,
    # Analytische bronnen (think-tanks & academisch)
    "bruegel.org": 9, "cepr.org": 8, "voxeu.org": 8,
    # Internationale bronnen — goede aanvulling, niet dominant
    "theguardian.com": 7, "guardian.com": 7,
    "reuters.com": 8, "apnews.com": 8,
    "bbc.com": 7, "bbc.co.uk": 7,
    "politico.eu": 8, "politico.com": 7,
    "bloomberg.com": 7, "wsj.com": 7, "ft.com": 8,
    "cnbc.com": 6,
    # Tech / AI
    "anthropic.com": 9, "openai.com": 8, "deepmind.google": 8,
    "theverge.com": 7, "techcrunch.com": 7, "arstechnica.com": 7,
    "simonwillison.net": 9, "interconnects.ai": 8, "404media.co": 7,
    "jack-clark.net": 8, "lastweekinai.com": 7,
    # Sport
    "f1.com": 7, "autosport.com": 6, "motorsport.com": 6,
}

# Bronnen die als 'Nederlands' gelden voor balans-controle
DUTCH_DOMAINS = {
    "nos.nl", "volkskrant.nl", "fd.nl", "nrc.nl",
    "nu.nl", "rtlnieuws.nl", "ftm.nl", "telegraaf.nl",
    "dnb.nl", "afm.nl",
}

def domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lower().replace("www.", "")
    except:
        return ""

def score(article: dict, now: datetime) -> float:
    s = 3.0

    # Bronprioriteit
    d = domain(article.get("link", article.get("url", "")))
    for key, prio in SOURCE_PRIORITY.items():
        if key in d:
            s += prio
            break
    else:
        s += 3

    # Recency
    pub = article.get("published", article.get("pub_date", ""))
    if pub:
        try:
            from dateutil import parser as dp
            dt = dp.parse(pub)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age = (now - dt).total_seconds() / 3600
            s += max(0, 6 - age * 0.25)   # +6 voor < 1u, lineair afnemend
        except:
            pass

    # Bonus volledige tekst
    if article.get("has_full_text") or article.get("full_text"):
        s += 3

    # Bonus voor langere samenvatting
    if len(article.get("summary", article.get("description", ""))) > 200:
        s += 1

    return s


def main():
    if not INPUT.exists():
        print(f"[preselect] FOUT: {INPUT} niet gevonden — voer fetch eerst uit", file=sys.stderr)
        sys.exit(1)

    raw = json.loads(INPUT.read_text())
    now = datetime.now(timezone.utc)

    out = {
        "generated_at":    raw.get("generated_at"),
        "preselected_at":  now.isoformat(),
        "pipeline_version": raw.get("pipeline_version"),
        "fd_focus_items":  raw.get("fd_focus_items", [])[:8],
        "guardian_items":  raw.get("guardian_items", 0),
        "topics": {}
    }

    total = 0
    for topic, tdata in raw.get("topics", {}).items():
        items = tdata.get("items", [])
        if not items:
            continue
        ranked = sorted(items, key=lambda a: score(a, now), reverse=True)

        # Diversiteitsregel: max 2 artikelen per domein, zodat één bron niet domineert
        selected = []
        domain_count: dict[str, int] = {}
        for a in ranked:
            d = domain(a.get("link", a.get("url", "")))
            if domain_count.get(d, 0) < 2:
                selected.append(a)
                domain_count[d] = domain_count.get(d, 0) + 1
            if len(selected) >= MAX_PER_SECTION:
                break

        total += len(selected)

        # Strip tot essentie: geen full_text, max 300 chars summary
        slim = []
        for a in selected:
            summary = a.get("summary", a.get("description", ""))
            slim.append({
                "title":     a.get("title", a.get("titel", "")),
                "summary":   summary[:300] if summary else "",
                "link":      a.get("link", a.get("url", "")),
                "published": a.get("published", a.get("pub_date", "")),
                "source":    domain(a.get("link", a.get("url", ""))),
                "full_text": (a.get("full_text") or a.get("content", ""))[:600] if a.get("has_full_text") else "",
            })
        out["topics"][topic] = {
            "items": slim,
            "item_count": len(slim),
            "original_count": len(items),
        }

    # FD focus items ook trimmen
    out["fd_focus_items"] = [
        {"title": f.get("title",""), "summary": (f.get("summary",""))[:200], "source": "FD"}
        for f in raw.get("fd_focus_items", [])[:6]
    ]

    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    orig = raw.get("total_items", "?")
    sz   = OUTPUT.stat().st_size // 1024
    print(f"[preselect] {total} artikelen geselecteerd uit {orig} → {OUTPUT} ({sz}KB)")


if __name__ == "__main__":
    main()
