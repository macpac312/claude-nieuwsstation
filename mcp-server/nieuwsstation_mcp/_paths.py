"""Centrale path-resolutie voor de MCP-server."""
import os
from pathlib import Path

NIEUWSSTATION_HOME = Path(
    os.environ.get("NIEUWSSTATION_HOME", str(Path.home() / "nieuwsstation"))
).expanduser()

BRIEFINGS_DIR = Path(
    os.environ.get("BRIEFINGS_DIR", str(Path.home() / "Documents/WorkMvMOBS/Briefings"))
).expanduser()

# Tussenbestanden die de bestaande scripts naar /tmp schrijven.
# De MCP-server (eigen proces) heeft hier ongelimiteerde toegang —
# Claude Desktop hoeft /tmp NIET in zijn allowlist te hebben.
TMP_READY    = Path("/tmp/dagkrant-ready.json")
TMP_SELECTED = Path("/tmp/dagkrant-selected.json")
TMP_WIDGETS  = Path("/tmp/dagkrant-widgets.json")
TMP_PLAN     = Path("/tmp/dagkrant-plan.json")


def assert_home_exists() -> None:
    """Geeft een duidelijke foutmelding als NIEUWSSTATION_HOME ontbreekt."""
    if not NIEUWSSTATION_HOME.exists():
        raise FileNotFoundError(
            f"NIEUWSSTATION_HOME='{NIEUWSSTATION_HOME}' bestaat niet. "
            f"Zet de env-var in claude_desktop_config.json of clone de repo daar."
        )
    sources = NIEUWSSTATION_HOME / "src/config/sources.yaml"
    if not sources.exists():
        raise FileNotFoundError(
            f"sources.yaml niet gevonden op {sources}. "
            f"Klopt NIEUWSSTATION_HOME? (huidig: {NIEUWSSTATION_HOME})"
        )
