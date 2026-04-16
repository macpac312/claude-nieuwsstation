#!/bin/bash
# dagkrant.sh — one-shot wrapper voor De Dagkrant.
#
# Bedoeld voor Claude Desktop: één commando voert de volledige pipeline uit en
# print het pad naar het HTML-bestand dat Claude Desktop direct kan renderen.
#
# Stappen:
#   1. Data ophalen  (RSS + Guardian + FD + widgets)           → /tmp/dagkrant-ready.json
#   2. Preselectie   (dedup + focus-filter)                    → /tmp/dagkrant-selected.json
#   3. Redactioneel plan via Claude (slash-command /dagkrant)  → /tmp/dagkrant-plan.json
#   4. HTML renderen                                           → Briefings/YYYY-MM-DD-dagkrant.html
#   5. (optioneel) API-server starten voor ▶ Achtergrond-knoppen
#   6. (optioneel) HTML openen in de standaard browser / Claude Desktop
#
# Gebruik:
#   bash scripts/dagkrant.sh                # volledige flow, vraagt Claude in stap 3
#   bash scripts/dagkrant.sh --skip-plan    # sla stap 3 over (plan al aanwezig in /tmp)
#   bash scripts/dagkrant.sh --skip-fetch   # sla stap 1-2 over (data al aanwezig in /tmp)
#   bash scripts/dagkrant.sh --with-api     # start ook api_server.py in de achtergrond
#   bash scripts/dagkrant.sh --open         # open het resultaat in de standaard app
#   bash scripts/dagkrant.sh --hours 48     # tijdvenster voor fetch (default: 24)

set -e
cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

HOURS=24
SKIP_FETCH=false
SKIP_PLAN=false
WITH_API=false
OPEN_RESULT=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --hours)       HOURS="$2"; shift 2 ;;
        --skip-fetch)  SKIP_FETCH=true; shift ;;
        --skip-plan)   SKIP_PLAN=true; shift ;;
        --with-api)    WITH_API=true; shift ;;
        --open)        OPEN_RESULT=true; shift ;;
        -h|--help)
            grep -E '^# ' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "Onbekende optie: $1"; exit 1 ;;
    esac
done

TODAY="$(date +%Y-%m-%d)"
BRIEFINGS_DIR="${BRIEFINGS_DIR:-$HOME/Documents/WorkMvMOBS/Briefings}"
OUTPUT_HTML="$BRIEFINGS_DIR/${TODAY}-dagkrant.html"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " De Dagkrant — $TODAY"
echo " Output: $OUTPUT_HTML"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ─── Stap 1-2: Data ophalen ──────────────────────────────────────────────────
if [ "$SKIP_FETCH" = false ]; then
    echo ""
    echo "▶ [1/4] Data ophalen (window: ${HOURS}u)"
    bash scripts/fetch-dagkrant-data.sh --hours "$HOURS"

    echo ""
    echo "▶ [2/4] Widgets (weer + markten)"
    python3 src/fetch_widgets.py --output /tmp/dagkrant-widgets.json 2>&1 \
        | grep -E "^\[OK|\[WARN\]" \
        || echo "  [WARN] widgets kwamen niet binnen, gebruik defaults"

    echo ""
    echo "▶ [2b/4] Preselectie (dedup + focus-filter)"
    python3 src/preselect_articles.py \
        --input /tmp/dagkrant-ready.json \
        --output /tmp/dagkrant-selected.json 2>&1 \
        | tail -5
else
    echo "▶ [1-2/4] Fetch overgeslagen (--skip-fetch)"
    [ ! -f /tmp/dagkrant-selected.json ] && {
        echo "  [FOUT] /tmp/dagkrant-selected.json ontbreekt — draai eerst zonder --skip-fetch"
        exit 1
    }
fi

# ─── Stap 3: Redactioneel plan via Claude ────────────────────────────────────
if [ "$SKIP_PLAN" = false ]; then
    echo ""
    echo "▶ [3/4] Redactioneel plan"
    if [ -f /tmp/dagkrant-plan.json ] && [ "$(find /tmp/dagkrant-plan.json -mmin -5 2>/dev/null)" ]; then
        echo "  Bestaand plan in /tmp/dagkrant-plan.json is <5min oud — gebruik dat."
    else
        cat <<'EOF'

  ⚠  Dit script kan het plan niet zelf genereren — daarvoor is Claude nodig.

  Doe dit nu in Claude Desktop of Claude Code:
      /dagkrant

  Zodra /tmp/dagkrant-plan.json bestaat, druk op ENTER om door te gaan.
  (Of start dit script opnieuw met --skip-fetch als het plan al klaar is.)

EOF
        read -r _
        if [ ! -f /tmp/dagkrant-plan.json ]; then
            echo "  [FOUT] /tmp/dagkrant-plan.json ontbreekt. Afbreken."
            exit 1
        fi
    fi
else
    echo "▶ [3/4] Plan overgeslagen (--skip-plan)"
    [ ! -f /tmp/dagkrant-plan.json ] && {
        echo "  [FOUT] /tmp/dagkrant-plan.json ontbreekt."
        exit 1
    }
fi

# ─── Stap 4: HTML renderen ───────────────────────────────────────────────────
echo ""
echo "▶ [4/4] HTML renderen"
mkdir -p "$BRIEFINGS_DIR"
python3 src/dagkrant_renderer.py

if [ ! -f "$OUTPUT_HTML" ]; then
    # fallback: renderer schreef mogelijk naar andere locatie
    OUTPUT_HTML="$(ls -t "$BRIEFINGS_DIR"/*dagkrant.html 2>/dev/null | head -1)"
fi

if [ -z "$OUTPUT_HTML" ] || [ ! -f "$OUTPUT_HTML" ]; then
    echo "  [FOUT] HTML niet gerenderd."
    exit 1
fi

SIZE_KB=$(($(stat -f%z "$OUTPUT_HTML" 2>/dev/null || stat -c%s "$OUTPUT_HTML") / 1024))
echo "  ✓ $OUTPUT_HTML (${SIZE_KB} KB)"

# ─── Optioneel: API-server starten ───────────────────────────────────────────
if [ "$WITH_API" = true ]; then
    echo ""
    echo "▶ Achtergrond-server starten op poort 7432"
    if lsof -iTCP:7432 -sTCP:LISTEN >/dev/null 2>&1; then
        echo "  Server draait al."
    else
        nohup python3 src/api_server.py >> logs/api_server.log 2>&1 &
        echo "  PID $! — logs in logs/api_server.log"
    fi
fi

# ─── Optioneel: openen ───────────────────────────────────────────────────────
if [ "$OPEN_RESULT" = true ]; then
    if command -v open >/dev/null 2>&1; then
        open "$OUTPUT_HTML"
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$OUTPUT_HTML"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Klaar. Pad voor Claude Desktop:"
echo "   $OUTPUT_HTML"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
