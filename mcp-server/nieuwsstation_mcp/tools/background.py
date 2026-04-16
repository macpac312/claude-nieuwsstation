"""generate_background: on-demand achtergrondartikel via Claude.

Importeert `src/api_server.py:generate_background` rechtstreeks (geen subprocess
en geen losse `api_server.py` HTTP-server meer nodig). Vereist `ANTHROPIC_API_KEY`
in de omgeving van de MCP-server.
"""
import sys
from typing import Any

from .._paths import NIEUWSSTATION_HOME, assert_home_exists


def generate_background(
    title: str,
    summary: str = "",
    sources: list[str] | None = None,
    topic: str = "",
) -> dict[str, Any]:
    """Genereer een diepgaand achtergrondartikel bij een nieuwsitem.

    Args:
        title:    titel van het artikel (verplicht)
        summary:  korte teaser/samenvatting
        sources:  lijst URLs van originele bronnen
        topic:    sectie-tag (nederland/wereld/financieel/sport/aitech/regulatoir)

    Returns:
        {"html": "<h4>...</h4>...", "archive_hits": N}  bij succes
        {"error": "..."}                                bij falen
    """
    assert_home_exists()
    if not title:
        return {"error": "veld 'title' is verplicht"}

    # src/ aan sys.path toevoegen, eenmalig
    src_dir = str(NIEUWSSTATION_HOME / "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    try:
        from api_server import generate_background as _gen
    except ImportError as e:
        return {
            "error": f"kan generate_background niet importeren uit api_server.py: {e}",
            "hint":  "Controleer dat anthropic geïnstalleerd is: pip install anthropic",
        }

    try:
        html, error, archive_hits = _gen(
            title=title,
            summary=summary or "",
            sources=sources or [],
            topic=topic or "",
            extra="",
            related_articles=[],
        )
    except Exception as e:
        return {"error": f"generate_background gooide exception: {type(e).__name__}: {e}"}

    if error:
        return {"error": error}

    return {
        "html": html,
        "archive_hits": archive_hits,
        "title": title,
    }
