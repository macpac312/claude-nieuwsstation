#!/bin/bash
# Automatische ochtend briefing via cron
# Installatie: crontab -e → 0 7 * * 1-5 ~/nieuwsstation/scripts/briefing-cron.sh
#
# Vereist: tmux sessie 'newsstation' met Claude Code Channels actief
# OF: directe claude -p aanroep (zie onderaan)

LOGFILE="$HOME/nieuwsstation/logs/briefing-$(date +%Y-%m-%d).log"
mkdir -p "$HOME/nieuwsstation/logs"

echo "[$(date)] Starting briefing..." >> "$LOGFILE"

# Optie 1: Via tmux sessie (als Channels draait)
if tmux has-session -t newsstation 2>/dev/null; then
    tmux send-keys -t newsstation '/briefing' Enter
    echo "[$(date)] Sent /briefing to tmux session" >> "$LOGFILE"
else
    # Optie 2: Directe claude -p aanroep
    cd "$HOME/nieuwsstation" || exit 1
    claude -p "Genereer de ochtend briefing voor vandaag met alle topics. Gebruik het /briefing command." >> "$LOGFILE" 2>&1
    echo "[$(date)] Briefing completed via claude -p" >> "$LOGFILE"
fi
