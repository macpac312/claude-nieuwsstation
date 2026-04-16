#!/usr/bin/env python3
"""Claude Code Session Manager voor Obsidian.

Scant alle Claude Code sessies, genereert korte titels op basis van de
inhoud, en maakt klikbare markdown-bestanden in de Obsidian vault.
Klikken op de "Open sessie" link opent een nieuw terminal-venster
met de sessie via het claude-session:// protocol.

Gebruik:
    python claude_sessions.py                # Sync sessies naar vault
    python claude_sessions.py --max 80       # Max 80 sessies
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


CLAUDE_DIR = Path.home() / ".claude" / "projects"
DEFAULT_VAULT = Path.home() / "Documents" / "WorkMvMOBS"
SESSIONS_FOLDER = "Claude Sessies"

# Patronen die duiden op systeem-prompts, niet op echte gebruikersvragen
SYSTEM_PROMPT_PATTERNS = [
    r"^Je bent een",
    r"^You are a",
    r"^<command",
    r"^<system",
    r"^Analyseer het volgende",
    r"^Je mag je eigen",
    r"^Lees het volgende",
    r"^Review the following",
]


def is_system_prompt(text: str) -> bool:
    """Check of tekst een systeem-prompt is (niet een echte gebruikersvraag)."""
    for pattern in SYSTEM_PROMPT_PATTERNS:
        if re.match(pattern, text.strip()):
            return True
    return False


def generate_title(messages: list[str]) -> str:
    """Genereer een korte, beschrijvende titel op basis van berichtinhoud."""
    # Zoek de eerste echte gebruikersvraag
    user_msg = ""
    for msg in messages:
        clean = re.sub(r"<[^>]+>", "", msg).strip()
        clean = clean.replace("\n", " ")
        if not clean:
            continue
        if not is_system_prompt(clean):
            user_msg = clean
            break

    if not user_msg:
        # Fallback: gebruik eerste bericht, ook als het een prompt is
        for msg in messages:
            clean = re.sub(r"<[^>]+>", "", msg).strip().replace("\n", " ")
            if clean:
                user_msg = clean
                break

    if not user_msg:
        return "Lege sessie"

    # Maak een korte titel van de inhoud
    # Verwijder veelvoorkomende prefixen
    for prefix in [
        "Je bent een ervaren ",
        "Je bent een ",
        "You are a ",
        "Analyseer het volgende hoofdstuk en identificeer ",
        "Je mag je eigen kennis en inzichten gebruiken naast de documenten. ",
    ]:
        if user_msg.lower().startswith(prefix.lower()):
            user_msg = user_msg[len(prefix):]
            break

    # Detecteer onderwerp-categorieën
    lower = user_msg.lower()

    if any(w in lower for w in ["thriller", "romanschrijver", "hoofdstuk", "schrijf"]):
        # Extract hoofdstuknummer als mogelijk
        ch_match = re.search(r"hoofdstuk\s*(\d+)", lower)
        book_match = re.search(r'"([^"]+)"', user_msg)
        if ch_match and book_match:
            return f"Roman: {book_match.group(1)} — H{ch_match.group(1)}"
        elif ch_match:
            return f"Roman schrijven — Hoofdstuk {ch_match.group(1)}"
        elif book_match:
            return f"Roman: {book_match.group(1)}"
        else:
            return "Roman schrijven"

    if any(w in lower for w in ["redacteur", "review", "beoordeel", "redigeer"]):
        if "genadeloze" in lower or "genadeloos" in lower:
            return "Strenge redactie-review"
        return "Redactie & review"

    if any(w in lower for w in ["continuity", "consistentie", "tijdlijn"]):
        return "Continuïteitscheck"

    if any(w in lower for w in ["story bible", "plot thread"]):
        return "Story Bible update"

    if any(w in lower for w in ["karakterontwikkeling", "dialoog"]):
        return "Karakter & dialoog analyse"

    if any(w in lower for w in ["proza", "stijl", "literair"]):
        return "Proza & stijl review"

    if any(w in lower for w in ["briefing", "nieuws", "dagkrant"]):
        return "Nieuwsbriefing"

    if any(w in lower for w in ["pptx", "presentatie", "powerpoint"]):
        return "Presentatie maken"

    if any(w in lower for w in ["calcasa", "avm", "validatie"]):
        return "Calcasa / AVM werk"

    if "memory" in lower or "/memory" in lower:
        return "Memory beheer"

    # Generieke titel: eerste 60 tekens
    title = user_msg[:60].strip()
    if len(user_msg) > 60:
        # Knip bij laatste spatie
        title = title[:title.rfind(" ")] if " " in title else title
    return title


def extract_session_info(jsonl_path: Path) -> dict | None:
    """Lees een sessie-JSONL en extraheer metadata + genereer titel."""
    try:
        user_messages = []
        assistant_count = 0
        timestamp = ""
        session_id = jsonl_path.stem

        with open(jsonl_path) as f:
            for i, line in enumerate(f):
                if i > 300:
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if i == 0:
                    timestamp = data.get("timestamp", "")
                    session_id = data.get("sessionId", session_id)

                msg_type = data.get("type", "")
                if msg_type in ("queue-operation", "user"):
                    content = data.get("content", "")
                    if content:
                        user_messages.append(content)
                if msg_type in ("assistant",):
                    assistant_count += 1

        if not user_messages:
            return None

        title = generate_title(user_messages)
        message_count = len(user_messages) + assistant_count

        # Maak titel bestandsnaam-veilig
        safe_title = re.sub(r'[<>:"/\\|?*#\[\]]', "", title)[:55].strip()
        if not safe_title:
            safe_title = f"Sessie {session_id[:8]}"

        # Parse datum
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d %H:%M")
            date_sort = dt.strftime("%Y%m%d%H%M")
            date_short = dt.strftime("%d %b")
        except (ValueError, AttributeError):
            date_str = "Onbekend"
            date_sort = "0"
            date_short = "?"

        size_kb = jsonl_path.stat().st_size / 1024

        return {
            "id": session_id,
            "title": title,
            "safe_title": safe_title,
            "timestamp": timestamp,
            "date_str": date_str,
            "date_sort": date_sort,
            "date_short": date_short,
            "message_count": message_count,
            "size_kb": round(size_kb, 1),
        }
    except Exception as e:
        print(f"  [WARN] {jsonl_path.name}: {e}", file=sys.stderr)
        return None


def get_project_dir(project_name: str | None = None) -> Path | None:
    """Vind de project-directory in ~/.claude/projects/."""
    if not CLAUDE_DIR.exists():
        return None
    for d in CLAUDE_DIR.iterdir():
        if d.is_dir():
            if project_name and project_name.lower() in d.name.lower():
                return d
            elif not project_name and "WorkMvMOBS" in d.name:
                return d
    dirs = [d for d in CLAUDE_DIR.iterdir() if d.is_dir()]
    return dirs[0] if dirs else None


def scan_sessions(project_dir: Path, max_sessions: int = 80) -> list[dict]:
    """Scan alle sessies."""
    sessions = []
    for f in project_dir.glob("*.jsonl"):
        info = extract_session_info(f)
        if info:
            sessions.append(info)
    sessions.sort(key=lambda x: x["date_sort"], reverse=True)
    return sessions[:max_sessions]


def create_session_notes(sessions: list[dict], vault_path: Path,
                         project_dir: Path) -> int:
    """Maak markdown-bestanden met klikbare terminal-links."""
    sessions_dir = vault_path / SESSIONS_FOLDER
    sessions_dir.mkdir(exist_ok=True)

    # Verwijder oude bestanden
    for old in sessions_dir.glob("*.md"):
        old.unlink()

    # Werkdirectory afleiden
    project_path = str(project_dir.name).replace("-", "/")
    if not project_path.startswith("/"):
        project_path = "/" + project_path

    created = 0
    for session in sessions:
        date_prefix = session["date_str"][:10].replace("-", "")
        filename = f"{date_prefix} — {session['safe_title']}.md"
        filepath = sessions_dir / filename

        resume_cmd = f"cd {project_path} && claude --resume {session['id']}"
        # URI voor Obsidian interne terminal (shell-commands plugin)
        obsidian_uri = f"obsidian://shell-commands/?vault=WorkMvMOBS&execute=claude_resume&_input={session['id']}"

        md = f"""---
session_id: "{session['id']}"
date: "{session['date_str']}"
cssclass: claude-session
---

# {session['title']}

> **{session['date_str']}** · {session['message_count']} berichten · {session['size_kb']} KB

## [▶ Open in Obsidian terminal]({obsidian_uri})

[↗ Open in extern terminal-venster](claude-session://{session['id']})

---
`{session['id']}`
"""
        filepath.write_text(md)
        created += 1

    # Index
    index_path = sessions_dir / "_Overzicht.md"
    lines = [
        "# Claude Code Sessies",
        "",
        f"> Laatst bijgewerkt: {datetime.now().strftime('%Y-%m-%d %H:%M')} · {len(sessions)} sessies",
        "",
    ]

    # Groepeer per dag
    current_date = ""
    for s in sessions:
        day = s["date_str"][:10]
        if day != current_date:
            current_date = day
            lines.append(f"\n### {day}")
            lines.append("")

        dp = day.replace("-", "")
        link = f"{dp} — {s['safe_title']}"
        lines.append(
            f"- [[{link}|{s['title']}]] · {s['message_count']} berichten"
        )

    index_path.write_text("\n".join(lines))
    return created


def main():
    parser = argparse.ArgumentParser(description="Claude Sessions → Obsidian")
    parser.add_argument("--project", type=str, default=None)
    parser.add_argument("--vault", type=str, default=str(DEFAULT_VAULT))
    parser.add_argument("--max", type=int, default=80)
    args = parser.parse_args()

    vault_path = Path(args.vault)
    if not vault_path.exists():
        print(f"[ERROR] Vault niet gevonden: {vault_path}", file=sys.stderr)
        sys.exit(1)

    project_dir = get_project_dir(args.project)
    if not project_dir:
        print("[ERROR] Geen Claude project gevonden", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Project: {project_dir.name}", file=sys.stderr)
    sessions = scan_sessions(project_dir, max_sessions=args.max)
    print(f"[INFO] {len(sessions)} sessies gevonden", file=sys.stderr)

    created = create_session_notes(sessions, vault_path, project_dir)
    print(f"[OK] {created} sessies → {SESSIONS_FOLDER}/", file=sys.stderr)


if __name__ == "__main__":
    main()
