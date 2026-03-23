#!/bin/bash
# Nieuwsstation: genereer een volledige briefing
# Gebruik: ./generate-briefing.sh [--topics "regulatoir tech"] [--hours 24]
set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE="${HOME}/.local/bin/claude"
TMPDIR="/tmp/nieuwsstation"
mkdir -p "$TMPDIR"

TOPICS_ARG=""
HOURS=24

while [[ $# -gt 0 ]]; do
  case $1 in
    --topics) TOPICS_ARG="--topics $2"; shift 2 ;;
    --hours) HOURS="$2"; shift 2 ;;
    *) shift ;;
  esac
done

echo "📡 Nieuwsstation — Briefing genereren..."

# Stap 1: RSS ophalen
echo "  [1/4] RSS feeds ophalen..."
python3 "$DIR/src/rss_fetcher.py" ${TOPICS_ARG:---all} --hours "$HOURS" --no-filter --output "$TMPDIR/rss.json" 2>&1 | grep -E '^\[OK'

# Stap 2: Vertalen
echo "  [2/4] Artikelen vertalen..."
python3 "$DIR/src/translator.py" --input "$TMPDIR/rss.json" --output "$TMPDIR/rss_nl.json" --claude "$CLAUDE" 2>&1 | grep -E '^\[OK|^\[INFO'

# Stap 3: Vault doorzoeken
echo "  [3/4] Vault doorzoeken..."
python3 "$DIR/src/vault_search.py" --news-json "$TMPDIR/rss_nl.json" --top 10 --output "$TMPDIR/vault.json" 2>&1 | grep -E '^\[OK'

# Stap 4: Briefing renderen
echo "  [4/4] Briefing renderen..."
python3 "$DIR/src/briefing_renderer.py" --rss "$TMPDIR/rss_nl.json" --vault "$TMPDIR/vault.json" 2>&1

echo ""
echo "✅ Briefing gereed! Open in Obsidian:"
DATE=$(date -u +%Y-%m-%d)
echo "   Briefings/${DATE}/${DATE}.md"
