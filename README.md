# Nieuwsstation

Persoonlijk nieuwsstation dat dagelijks een interactieve HTML-dagkrant genereert, aangedreven door Claude. Nieuws wordt opgehaald uit RSS-feeds, Guardian API en FD, redactioneel geselecteerd door Claude Opus, en gerenderd als een self-contained HTML-bestand met interactieve visuals.

## Wat het doet

- Haalt nieuws op uit 30+ bronnen (NOS, Volkskrant, Guardian, FD, EBA, ECB, AFM, motorsport, ...)
- Claude Opus maakt een redactioneel plan: hero, topnieuws, 5 secties, kruisverband-analyse
- Renderer bouwt een 130KB HTML-dagkrant met Chart.js grafieken en D3.js visualisaties
- On-demand achtergrondartikelen via `api_server.py` (lokale server op poort 7432)
- Optioneel: automatische upload naar NotebookLM voor een Audio Overview podcast

## Vereisten

- Python 3.11+
- [Claude Code CLI](https://claude.ai/code) — geïnstalleerd en ingelogd
- Obsidian (voor de plugin-interface) — optioneel als je Claude Code Desktop gebruikt

## Installatie

### 1. Clone de repo

```bash
git clone https://github.com/macpac312/claude-nieuwsstation.git ~/nieuwsstation
cd ~/nieuwsstation
```

### 2. Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Guardian API key

Gratis key via [open-platform.theguardian.com](https://open-platform.theguardian.com/access/).

```bash
mkdir -p ~/.config/nieuwsstation
echo "JOUW_GUARDIAN_API_KEY" > ~/.config/nieuwsstation/guardian_api_key
```

### 4. FD credentials (optioneel)

Voor full-text FD-artikelen:

```bash
cp .env.example .env
# Vul FD_EMAIL en FD_PASSWORD in .env
```

### 5. Focus instellen

```bash
cp focus.md.example focus.md
# Pas focus.md aan met je eigen onderwerpen
```

### 6. Vault-pad instellen

Standaard verwacht het systeem de Obsidian vault op `~/Documents/WorkMvMOBS`. Pas dit aan in:
- `src/dagkrant_renderer.py` — variabele `BRIEFINGS`
- `src/vault_search.py` — variabele `VAULT_ROOT`
- `src/api_server.py` — variabele `VAULT_PATH` (zoek op `WorkMvMOBS`)

### 7. Claude skills installeren

```bash
mkdir -p ~/.claude/skills/nieuwsstation ~/.claude/commands
cp claude-config/skills/nieuwsstation/SKILL.md ~/.claude/skills/nieuwsstation/
cp claude-config/commands/dagkrant.md ~/.claude/commands/
cp claude-config/commands/briefing.md ~/.claude/commands/
```

### 8. Obsidian plugin bouwen (optioneel)

```bash
cd obsidian-plugin
npm install
npm run build
# Kopieer de gebouwde plugin naar je vault:
mkdir -p ~/Documents/WorkMvMOBS/.obsidian/plugins/nieuwsstation
cp main.js manifest.json styles.css ~/Documents/WorkMvMOBS/.obsidian/plugins/nieuwsstation/
```

Activeer de plugin in Obsidian onder Settings → Community plugins.

## Gebruik

### Via Claude Desktop (HTML direct in het gesprek) — aanbevolen

De nieuwste Claude Desktop kan HTML inline renderen, en met de meegeleverde
**MCP-server** kan Claude de hele pipeline zelf draaien — geen aparte
terminal, geen `/tmp`-permissieprobleem, geen losse `api_server.py`.

**Eenmalige setup:**

```bash
cd ~/nieuwsstation
pip install -e mcp-server/
```

Kopieer `claude-config/claude_desktop_config.example.json` naar:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Pas de paden aan en herstart Claude Desktop. **Geen API-key nodig** — je
Claude Max-abonnement dekt alle tekst-generatie (redactioneel plan,
kruisverbanden, achtergrondartikelen). Zie
[mcp-server/README.md](mcp-server/README.md) voor details.

**Dagelijks gebruik:**

Tik in Claude Desktop:

```
/dagkrant
```

Of natuurlijke taal: *"maak de dagkrant van vandaag"*. Claude:
1. roept `nieuwsstation.fetch_news()` → krijgt 40 artikelen + widgets terug
2. bouwt het redactionele plan in-context
3. roept `nieuwsstation.render_dagkrant(plan)` → krijgt het HTML-pad terug
4. leest het bestand via filesystem-MCP en rendert het inline in het gesprek

### Via Claude Code (CLI)

```
/nieuwsstation
```

Of het wrapper-script in een terminal:

```bash
bash scripts/dagkrant.sh             # fetch + plan + render
bash scripts/dagkrant.sh --with-api  # start ook api_server.py voor ▶ Achtergrond-knoppen
bash scripts/dagkrant.sh --open      # open het HTML-bestand in de standaard browser
bash scripts/dagkrant.sh --hours 48  # groter tijdvenster voor de fetch
```

### Handmatig (stap voor stap)

```bash
# Stap 1: Data ophalen
bash scripts/fetch-dagkrant-data.sh --hours 24

# Stap 2: Dagkrant genereren (via Claude Code)
# Gebruik /dagkrant command in Claude Code

# Stap 3: API-server starten voor achtergrond-knoppen
python3 src/api_server.py &
# Server draait op http://127.0.0.1:7432
```

De dagkrant wordt opgeslagen als `~/Documents/WorkMvMOBS/Briefings/YYYY-MM-DD-dagkrant.html`.

## Architectuur

```
scripts/fetch-dagkrant-data.sh
  ├── rss_fetcher.py          → /tmp/dk-rss.json
  ├── guardian_fetcher.py     → gemergd in /tmp/dk-rss.json
  ├── fd_fetcher.py           → /tmp/dk-fd.json
  ├── fetch_widgets.py        → /tmp/dagkrant-widgets.json
  └── preselect_articles.py   → /tmp/dagkrant-selected.json

Claude Code (/dagkrant command)
  └── dagkrant_planner.py     → /tmp/dagkrant-plan.json

dagkrant_renderer.py
  └── dagkrant_template.html  → Briefings/YYYY-MM-DD-dagkrant.html

api_server.py (achtergrond, poort 7432)
  ├── /background             → on-demand achtergrondartikelen
  ├── /kruisverband-visual    → D3.js verbanden-diagram
  └── /notebooklm             → upload naar NotebookLM
```

## Configuratie

Bronnen en secties: `src/config/sources.yaml`
Actieve onderwerpen: `focus.md`
FD-credentials: `.env`
Guardian API key: `~/.config/nieuwsstation/guardian_api_key`

## NotebookLM (optioneel)

Voor automatische podcast-generatie via NotebookLM:

```bash
# Eenmalige setup (Google login opslaan)
python3 src/notebooklm_uploader.py --setup

# Daarna werkt de 📤 knop in de dagkrant automatisch
```

Vereist: `pip install playwright && playwright install chromium`
