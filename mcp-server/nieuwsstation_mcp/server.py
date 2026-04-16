"""MCP-server voor Nieuwsstation.

Registreert de tools `fetch_news`, `render_dagkrant` en
`generate_background` zodat Claude Desktop ze direct kan aanroepen.
"""
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
from .tools.background import generate_background as _generate_background


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


@mcp.tool()
def generate_background(
    title: str,
    summary: str = "",
    sources: list[str] | None = None,
    topic: str = "",
) -> dict[str, Any]:
    """Genereer een diepgaand achtergrondartikel (~600-1000 woorden) bij een
    nieuwsitem uit de dagkrant. Vervangt de oude api_server.py /background-route.

    Vereist ANTHROPIC_API_KEY in de omgeving van de MCP-server.
    Doet web-zoeken naar extra bronnen (DuckDuckGo), zoekt YouTube-context,
    raadpleegt het vault-archief, en laat Claude Opus de analyse schrijven.
    Duurt ~30-60s per artikel.

    Returns: {html, archive_hits} bij succes, of {error} bij falen.
    """
    return _generate_background(
        title=title, summary=summary, sources=sources or [], topic=topic
    )


def main() -> None:
    """Start de MCP-server op stdio (zoals Claude Desktop verwacht)."""
    mcp.run()


if __name__ == "__main__":
    main()
