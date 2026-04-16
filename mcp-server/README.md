# Nieuwsstation MCP-server

Custom MCP-server die de dagkrant-pipeline beschikbaar maakt als tools in
Claude Desktop. Wrapt de bestaande Python-modules en shell-scripts zodat
Claude Desktop **zonder `/tmp`-permissies of losse `api_server.py`** een
volledige dagkrant kan genereren en inline weergeven.

## Tools

| Tool | Doel |
|------|------|
| `fetch_news(hours=24)` | RSS + Guardian + FD ophalen, dedupliceren, top-40 selecteren, widgets toevoegen. Returns dict met `selected`, `widgets`, `stats`. |
| `render_dagkrant(plan)` | Render het redactionele plan naar `~/Documents/WorkMvMOBS/Briefings/YYYY-MM-DD-dagkrant.html` (~130 KB). Returns `{path, size_kb, open_url, ...}`. |
| `generate_background(title, summary, sources, topic)` | On-demand achtergrondartikel via Claude Opus. Vervangt de oude `api_server.py`. Vereist `ANTHROPIC_API_KEY`. |

## Installatie

### 1. Python-package installeren

```bash
cd ~/nieuwsstation
pip install -e mcp-server/
```

### 2. Claude Desktop configureren

Kopieer `claude-config/claude_desktop_config.example.json` naar:

| OS | Pad |
|----|-----|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

Pas de paden `/home/marcel/...` aan naar je eigen gebruikersnaam, vul je
`ANTHROPIC_API_KEY` in (alleen nodig voor `generate_background`), en
**herstart Claude Desktop**.

### 3. Verificatie

In Claude Desktop → Settings → Developer → "Local MCP servers" zou je
`nieuwsstation` moeten zien met status *connected*. Tik in het gesprek:

```
maak de dagkrant van vandaag
```

Of expliciet:

```
/dagkrant
```

## Handmatige test buiten Claude Desktop

```bash
# Server starten op stdio (Ctrl+C om te stoppen):
python3 -m nieuwsstation_mcp

# Of de tools direct aanroepen vanuit Python:
python3 -c "
from nieuwsstation_mcp.tools.fetch import fetch_news
result = fetch_news(hours=24, skip_guardian=True, skip_fd=True)
print(f'{result[\"stats\"][\"total_selected\"]} artikelen geselecteerd')
"
```

## Environment-variabelen

| Variabele | Default | Doel |
|-----------|---------|------|
| `NIEUWSSTATION_HOME` | `~/nieuwsstation` | Repo-locatie (sources.yaml, scripts/, src/) |
| `BRIEFINGS_DIR` | `~/Documents/WorkMvMOBS/Briefings` | Waar dagkrant.html landt |
| `ANTHROPIC_API_KEY` | — | Alleen nodig voor `generate_background` |

## Architectuur

```
Claude Desktop
    │
    ▼  MCP stdio
nieuwsstation_mcp.server  (FastMCP)
    │
    ├── fetch_news ──► subprocess → scripts/fetch-dagkrant-data.sh
    │                              src/fetch_widgets.py
    │                              src/preselect_articles.py
    │                  ◄── leest /tmp/dagkrant-{ready,selected,widgets}.json
    │                  (eigen proces; geen Claude-permissieprobleem)
    │
    ├── render_dagkrant ──► subprocess → src/dagkrant_renderer.py
    │                       ◄── HTML in Briefings/
    │
    └── generate_background ──► import api_server.generate_background()
                                ◄── HTML-string (achtergrondartikel)
```

De MCP-server is een **thin shim** — geen herschrijving van de bestaande
modules. Daardoor blijft de Claude Code CLI-flow (`bash scripts/dagkrant.sh`)
ongewijzigd werken naast de Claude Desktop-flow.
