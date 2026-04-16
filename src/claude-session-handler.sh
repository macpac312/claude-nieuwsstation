#!/bin/bash
# Claude Code Session Handler
# Wordt aangeroepen via het claude-session:// URI protocol
# Opent een nieuw terminal-venster met de opgegeven sessie

URI="$1"
# Strip protocol prefix: claude-session://SESSION_ID
SESSION_ID="${URI#claude-session://}"
SESSION_ID="${SESSION_ID#/}"  # strip leading slash if any
SESSION_ID="${SESSION_ID%%/*}" # strip trailing path if any

if [ -z "$SESSION_ID" ]; then
    notify-send "Claude Sessie" "Geen sessie-ID opgegeven" 2>/dev/null
    exit 1
fi

WORKDIR="$HOME/Documents/WorkMvMOBS"

# Open nieuw terminal-venster met claude --resume
# Probeer eerst gnome-terminal (werkt op Pop!_OS), dan cosmic-term
if command -v gnome-terminal &>/dev/null; then
    gnome-terminal --working-directory="$WORKDIR" -- bash -c "claude --resume '$SESSION_ID'; exec bash"
elif command -v cosmic-term &>/dev/null; then
    cosmic-term -w "$WORKDIR" &
    sleep 0.5
    # cosmic-term heeft geen -e flag, dus we gebruiken gnome-terminal als fallback
fi
