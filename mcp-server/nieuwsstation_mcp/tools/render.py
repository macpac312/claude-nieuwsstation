"""render_dagkrant: schrijft het redactionele plan naar HTML.

Wrapt `src/dagkrant_renderer.py` via subprocess. Het script leest
`/tmp/dagkrant-plan.json` en schrijft naar
`~/Documents/WorkMvMOBS/Briefings/YYYY-MM-DD-dagkrant.html`.
"""
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .._paths import BRIEFINGS_DIR, NIEUWSSTATION_HOME, TMP_PLAN, assert_home_exists


def render_dagkrant(plan: dict[str, Any]) -> dict[str, Any]:
    """Render het redactionele plan naar een interactieve HTML-dagkrant.

    Args:
        plan: het redactionele plan-object volgens het schema in
              `claude-config/commands/dagkrant.md` (datum_iso, hero,
              topnieuws, secties, widgets, kruisverband_md, ...).

    Returns:
        {
          "path":      "/absolute/pad/naar/2026-04-16-dagkrant.html",
          "size_kb":   142,
          "datum_iso": "2026-04-16",
          "sections":  ["nederland", "wereld", ...],
          "open_url":  "file:///absolute/pad/naar/...html",
        }

    De gebruiker kan het bestand vervolgens via filesystem-MCP openen, en
    Claude Desktop rendert het inline (HTML-render-modus).
    """
    assert_home_exists()

    if not isinstance(plan, dict):
        return {"error": "plan moet een dict zijn"}

    # 1. Plan naar /tmp schrijven (renderer leest hier)
    TMP_PLAN.parent.mkdir(parents=True, exist_ok=True)
    TMP_PLAN.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    # 2. Briefings-map garanderen
    BRIEFINGS_DIR.mkdir(parents=True, exist_ok=True)

    # 3. Renderer draaien
    try:
        proc = subprocess.run(
            ["python3", str(NIEUWSSTATION_HOME / "src/dagkrant_renderer.py")],
            cwd=str(NIEUWSSTATION_HOME),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {"error": "renderer timeout (60s)"}

    if proc.returncode != 0:
        return {
            "error": f"renderer faalde (rc={proc.returncode})",
            "stderr": proc.stderr[-1500:],
            "stdout": proc.stdout[-500:],
        }

    # 4. Output-pad bepalen
    datum_iso = plan.get("datum_iso") or datetime.now().strftime("%Y-%m-%d")
    out = BRIEFINGS_DIR / f"{datum_iso}-dagkrant.html"

    if not out.exists():
        # Fallback: pak het meest recente dagkrant-bestand
        candidates = sorted(BRIEFINGS_DIR.glob("*-dagkrant.html"))
        if candidates:
            out = candidates[-1]
        else:
            return {
                "error": f"renderer ran, maar geen dagkrant.html gevonden in {BRIEFINGS_DIR}",
                "stdout": proc.stdout[-500:],
            }

    return {
        "path":      str(out.resolve()),
        "size_kb":   out.stat().st_size // 1024,
        "datum_iso": datum_iso,
        "sections":  list(plan.get("secties", {}).keys()),
        "open_url":  out.resolve().as_uri(),
        "renderer_log": proc.stdout.strip()[-300:],
    }
