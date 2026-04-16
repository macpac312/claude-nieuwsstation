"""fetch_news: haalt RSS + Guardian + FD op, dedupliceert, preselecteert.

Wrapt de bestaande shell-pipeline (`scripts/fetch-dagkrant-data.sh`) +
`src/fetch_widgets.py` + `src/preselect_articles.py` via subprocess.
Voordeel: geen herschrijving van de bestaande modules.
"""
import json
import subprocess
import sys
from typing import Any

from .._paths import (
    NIEUWSSTATION_HOME,
    TMP_READY,
    TMP_SELECTED,
    TMP_WIDGETS,
    assert_home_exists,
)


def _run(cmd: list[str], timeout: int = 90, optional: bool = False) -> tuple[int, str]:
    """Run subprocess, return (returncode, combined-output). Capture all output
    zodat MCP-clients geen rotzooi op stderr/stdout zien."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(NIEUWSSTATION_HOME),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout + "\n" + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        if optional:
            return 124, f"timeout na {timeout}s (optioneel — overgeslagen)"
        raise
    except FileNotFoundError as e:
        return 127, str(e)


def fetch_news(
    hours: int = 24,
    skip_guardian: bool = False,
    skip_fd: bool = False,
) -> dict[str, Any]:
    """Haal nieuws op en preselecteer voor de dagkrant.

    Args:
        hours: tijdvenster in uren (default 24)
        skip_guardian: sla Guardian API over (handig zonder API-key)
        skip_fd: sla FD-fetch over (handig zonder credentials)

    Returns:
        {
          "selected": {topics: {topic: {items: [...], item_count: N, ...}}, fd_focus_items: [...]},
          "widgets":  {weer_temp, aex, sp500, brent, eurusd, ..., brent_trend: [...]},
          "stats":    {total_seen: N, total_selected: M, topics: [...]},
          "logs":     "stdout/stderr van de pipeline (samengevat)",
        }
    """
    assert_home_exists()
    logs: list[str] = []

    # ── 1. Hoofdpijplijn: RSS + Guardian + FD ────────────────────────────────
    fetch_script = NIEUWSSTATION_HOME / "scripts/fetch-dagkrant-data.sh"
    cmd = ["bash", str(fetch_script), "--hours", str(hours)]
    if skip_guardian:
        cmd.append("--no-guardian")
    if skip_fd:
        cmd.append("--no-fd")

    rc, out = _run(cmd, timeout=180)
    logs.append(f"[fetch] rc={rc}\n{out[-2000:]}")
    if rc != 0:
        return {
            "error": f"fetch-dagkrant-data.sh faalde (rc={rc})",
            "logs": "\n\n".join(logs),
        }

    # ── 2. Widgets (weer + markten) ──────────────────────────────────────────
    rc, out = _run(
        ["python3", str(NIEUWSSTATION_HOME / "src/fetch_widgets.py")],
        timeout=30,
        optional=True,
    )
    logs.append(f"[widgets] rc={rc}\n{out[-500:]}")

    # ── 3. Preselectie ───────────────────────────────────────────────────────
    rc, out = _run(
        ["python3", str(NIEUWSSTATION_HOME / "src/preselect_articles.py")],
        timeout=30,
    )
    logs.append(f"[preselect] rc={rc}\n{out[-500:]}")
    if rc != 0:
        return {
            "error": f"preselect_articles.py faalde (rc={rc})",
            "logs": "\n\n".join(logs),
        }

    # ── 4. JSON inlezen ──────────────────────────────────────────────────────
    if not TMP_SELECTED.exists():
        return {"error": f"{TMP_SELECTED} bestaat niet na pipeline", "logs": "\n\n".join(logs)}

    selected = json.loads(TMP_SELECTED.read_text(encoding="utf-8"))
    widgets: dict[str, Any] = {}
    if TMP_WIDGETS.exists():
        try:
            widgets = json.loads(TMP_WIDGETS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            widgets = {}

    # ── 5. Statistieken ──────────────────────────────────────────────────────
    topics = selected.get("topics", {})
    total_selected = sum(len(t.get("items", [])) for t in topics.values())
    total_seen = 0
    if TMP_READY.exists():
        try:
            ready = json.loads(TMP_READY.read_text(encoding="utf-8"))
            total_seen = ready.get("total_items", 0)
        except json.JSONDecodeError:
            pass

    return {
        "selected": selected,
        "widgets": widgets,
        "stats": {
            "total_seen": total_seen,
            "total_selected": total_selected,
            "topics": [
                {"topic": t, "count": len(d.get("items", []))}
                for t, d in topics.items()
            ],
            "hours": hours,
        },
        "logs": "\n\n".join(logs),
    }
