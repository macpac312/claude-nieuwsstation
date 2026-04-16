"""MCP-server voor Nieuwsstation.

Registreert de tools `fetch_news` en `render_dagkrant` zodat Claude Desktop
de hele dagkrant-pipeline zelf kan draaien. Geen Anthropic-API-key nodig:
de tekst-generatie (redactioneel plan, kruisverbanden, achtergrondartikelen)
gebeurt door Claude Desktop zélf — onder je Claude Max-abonnement.

Zet `NIEUWSSTATION_ENABLE_BACKGROUND_TOOL=1` om de optionele
`generate_background` tool extra te registreren (vereist wél een aparte
ANTHROPIC_API_KEY — alleen relevant voor wie de oude api_server.py-route
wil bouwen via de MCP-server in plaats van Claude Max).
"""
import os
import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    sys.stderr.write(
        "[nieuwsstation-mcp] FOUT: 'mcp' SDK niet geïnstalleerd.\n"
        "Installeer met:  pip install -e mcp-server/\n"
        f"Originele import-error: {e}\n"
    )
    raise SystemExit(1)

from .tools.fetch import fetch_news as _fetch_news
from .tools.render import render_dagkrant as _render_dagkrant


mcp = FastMCP("nieuwsstation")


@mcp.tool()
def fetch_news(
    hours: int = 24,
    skip_guardian: bool = False,
    skip_fd: bool = False,
) -> dict[str, Any]:
    """Haal Nederlandse + internationale nieuwsartikelen op en preselecteer.

    Combineert RSS-feeds (NOS, Volkskrant, NRC, NU.nl, ...), Guardian API
    en FD voor de Dagkrant-pipeline. Dedupliceert, scoort op bron-prioriteit
    en recency, en levert ~40 geselecteerde artikelen verdeeld over secties
    (nederland, wereld, financieel, sport, aitech, regulatoir, huizenmarkt).
    Voegt ook widgets toe (weer, AEX, S&P, Brent, EUR/USD).

    Args:
        hours:         tijdvenster in uren (default 24, max 72)
        skip_guardian: sla Guardian API over indien geen API-key beschikbaar
        skip_fd:       sla FD-fetch over indien geen credentials

    Returns dict met sleutels: selected, widgets, stats, logs.
    Gebruik dit ALTIJD als eerste stap in /dagkrant.
    """
    return _fetch_news(hours=hours, skip_guardian=skip_guardian, skip_fd=skip_fd)


@mcp.tool()
def render_dagkrant(plan: dict[str, Any]) -> dict[str, Any]:
    """Render het redactionele plan naar een interactieve HTML-dagkrant.

    Schrijft `~/Documents/WorkMvMOBS/Briefings/YYYY-MM-DD-dagkrant.html`
    (~130 KB self-contained). Bevat hero-artikel, topnieuws, secties,
    kruisverband-analyse, Chart.js grafieken en D3.js visualisaties.

    Args:
        plan: het JSON-plan-object volgens het schema in
              claude-config/commands/dagkrant.md (datum_iso, hero,
              topnieuws, secties, widgets, kruisverband_md, ...).

    Returns: {path, size_kb, datum_iso, sections, open_url}.
    Lees daarna `path` via filesystem-MCP en toon de HTML inline in
    Claude Desktop.
    """
    return _render_dagkrant(plan)


# ─── Optionele tool: generate_background ──────────────────────────────────────
# Niet nodig voor Claude Max — Claude Desktop schrijft achtergrondartikelen
# direct in het gesprek. Alleen registreren als de gebruiker het expliciet
# aanzet én een ANTHROPIC_API_KEY beschikbaar is.
if os.environ.get("NIEUWSSTATION_ENABLE_BACKGROUND_TOOL") == "1":
    from .tools.background import generate_background as _generate_background

    @mcp.tool()
    def generate_background(
        title: str,
        summary: str = "",
        sources: list[str] | None = None,
        topic: str = "",
    ) -> dict[str, Any]:
        """Optioneel: genereer achtergrondartikel via aparte Anthropic API.

        Alleen geregistreerd als NIEUWSSTATION_ENABLE_BACKGROUND_TOOL=1.
        Vereist ANTHROPIC_API_KEY. Voor Claude Max-gebruikers: NIET nodig —
        Claude Desktop schrijft de achtergrond zelf in het gesprek.
        """
        return _generate_background(
            title=title, summary=summary, sources=sources or [], topic=topic
        )


def main() -> None:
    """Start de MCP-server op stdio (zoals Claude Desktop verwacht)."""
    mcp.run()


if __name__ == "__main__":
    main()
