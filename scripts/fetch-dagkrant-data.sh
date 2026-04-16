#!/bin/bash
# fetch-dagkrant-data.sh — Haal nieuwsdata op voor De Dagkrant
# Fase A van de dagkrant-pipeline (geen Claude, kan als cron draaien)
#
# Gebruik:
#   ./fetch-dagkrant-data.sh [--hours 24] [--no-guardian] [--no-fd]
#
# Output: /tmp/dagkrant-ready.json  ← wordt gelezen door /dagkrant command
#
# Cron (06:00 elke dag):
#   0 6 * * * bash ~/nieuwsstation/scripts/fetch-dagkrant-data.sh >> ~/nieuwsstation/logs/fetch.log 2>&1

set -e
cd "$(dirname "$0")/.."

HOURS=24
SKIP_GUARDIAN=false
SKIP_FD=false
SKIP_FD_FOCUS=false
FD_FULL_TEXT=false
FD_MAX_FULL_TEXT=8

while [[ $# -gt 0 ]]; do
    case $1 in
        --hours)    HOURS="$2"; shift 2 ;;
        --no-guardian) SKIP_GUARDIAN=true; shift ;;
        --no-fd)    SKIP_FD=true; SKIP_FD_FOCUS=true; shift ;;
        --no-fd-focus) SKIP_FD_FOCUS=true; shift ;;
        --fd-full-text) FD_FULL_TEXT=true; shift ;;
        --fd-max-full-text) FD_MAX_FULL_TEXT="$2"; shift 2 ;;
        *)          shift ;;
    esac
done

mkdir -p logs

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Dagkrant data-fetch — $(date '+%Y-%m-%d %H:%M')"
echo " Tijdvenster: laatste ${HOURS} uur"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ─── Stap 1: RSS feeds (parallel met Guardian) ───
echo ""
echo "[1/4] RSS feeds ophalen..."
python3 src/rss_fetcher.py --all --section dagkrant_topics --hours "$HOURS" --output /tmp/dk-rss.json 2>&1 \
    | grep -E "^\[OK|→" \
    || { echo "  [WARN] RSS fetcher mislukt"; echo '{"topics":{},"total_items":0}' > /tmp/dk-rss.json; }

# ─── Stap 2: Guardian API (parallel starten) ───
if [ "$SKIP_GUARDIAN" = false ]; then
    echo ""
    echo "[2/4] Guardian API ophalen..."
    FOCUS_PATH="$(pwd)/focus.md"
    if python3 src/guardian_fetcher.py \
        --focus "$FOCUS_PATH" \
        --hours "$HOURS" \
        --merge-into /tmp/dk-rss.json 2>&1 | grep -E "^\[OK|\[Guardian\]|\[WARN\]"; then
        echo "  Guardian: klaar"
    else
        echo "  [WARN] Guardian fetcher mislukt, doorgaan zonder"
    fi
else
    echo "[2/4] Guardian overgeslagen (--no-guardian)"
fi

# ─── Stap 3: FD artikelen (RSS) ───
echo ""
if [ "$SKIP_FD" = false ]; then
    echo "[3/4] FD artikelen ophalen..."
    FD_FLAGS="--hours $HOURS --output /tmp/dk-fd.json"
    if [ "$FD_FULL_TEXT" = true ]; then
        FD_FLAGS="$FD_FLAGS --full-text --max-full-text $FD_MAX_FULL_TEXT"
    fi
    python3 src/fd_fetcher.py $FD_FLAGS 2>&1 \
        | grep -E "^\[OK|\[WARN\]" \
        || { echo "  FD niet beschikbaar"; echo '[]' > /tmp/dk-fd.json; }
else
    echo "[3/4] FD overgeslagen (--no-fd)"
    echo '[]' > /tmp/dk-fd.json
fi

# ─── Stap 3b: FD focus-archief ───
echo ""
if [ "$SKIP_FD_FOCUS" = false ] && [ -f "focus.md" ]; then
    echo "[3b/4] FD archief zoeken op focus-onderwerpen..."
    python3 src/fd_fetcher.py --focus focus.md --days-back 30 --output /tmp/dk-fd-focus.json 2>&1 \
        | grep -E "^\[OK|\[WARN\]|\[FD archief\]" \
        || { echo "  FD archief niet beschikbaar"; echo '[]' > /tmp/dk-fd-focus.json; }
else
    echo "[3b/4] FD focus-archief overgeslagen"
    echo '[]' > /tmp/dk-fd-focus.json
fi

# ─── Stap 4: Combineren tot dagkrant-ready.json ───
echo ""
echo "[4/4] Combineren..."
python3 - <<'PYEOF'
import json, sys
from pathlib import Path
from datetime import datetime, timezone

rss      = json.loads(Path('/tmp/dk-rss.json').read_text())       if Path('/tmp/dk-rss.json').exists()       else {"topics": {}, "total_items": 0}
fd       = json.loads(Path('/tmp/dk-fd.json').read_text())         if Path('/tmp/dk-fd.json').exists()         else []
fd_focus = json.loads(Path('/tmp/dk-fd-focus.json').read_text())   if Path('/tmp/dk-fd-focus.json').exists()   else []

# Verzamel alle bestaande URLs voor deduplicatie
all_existing = {it['link'] for t in rss.get('topics', {}).values() for it in t.get('items', [])}

def merge_fd_articles(fd_list, rss, existing_urls, topic='financieel'):
    """Voeg FD-artikelen toe aan het juiste topic."""
    if not isinstance(fd_list, list) or not fd_list:
        return 0
    if topic not in rss.get('topics', {}):
        rss.setdefault('topics', {})[topic] = {'items': [], 'item_count': 0}
    new_items = [it for it in fd_list if it.get('link') not in existing_urls]
    rss['topics'][topic]['items'].extend(new_items)
    rss['topics'][topic]['item_count'] = len(rss['topics'][topic]['items'])
    rss['total_items'] = rss.get('total_items', 0) + len(new_items)
    existing_urls.update(it['link'] for it in new_items)
    return len(new_items)

# FD RSS → financieel
n_fd = merge_fd_articles(fd, rss, all_existing, 'financieel')

# FD focus → per focus_label (gegroepeerd als achtergrond-context)
if fd_focus:
    rss['fd_focus_items'] = fd_focus  # apart bewaren als context voor Claude
    rss['fd_focus_count'] = len(fd_focus)

rss['generated_at'] = datetime.now(timezone.utc).isoformat()
rss['pipeline_version'] = '2.1'

Path('/tmp/dagkrant-ready.json').write_text(json.dumps(rss, ensure_ascii=False, indent=2))

# Overzicht
total = rss.get('total_items', 0)
guardian_items = rss.get('guardian_items', 0)
focus_items = rss.get('fd_focus_count', 0)
topics = rss.get('topics', {})
print(f"  Totaal: {total} artikelen ({guardian_items} Guardian met volledige tekst, {n_fd} FD-RSS)")
if focus_items:
    print(f"  FD focus-archief: {focus_items} achtergrond-artikelen (context voor Claude)")
for topic, td in topics.items():
    n = len(td.get('items', []))
    ft = sum(1 for it in td.get('items', []) if it.get('has_full_text'))
    ft_str = f", {ft} met volledige tekst" if ft else ""
    print(f"  {topic}: {n} items{ft_str}")
PYEOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Klaar → /tmp/dagkrant-ready.json"
echo " Start /dagkrant in Claude Code voor de HTML-generatie"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
