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

### Via Claude Code (aanbevolen)

```
/nieuwsstation
```

Claude Code voert automatisch de volledige pipeline uit.

### Via Claude Desktop (HTML direct in het gesprek)

Sinds Claude Desktop HTML-bestanden rechtstreeks kan renderen, kun je de dagkrant in het gesprek laten verschijnen.

**Eenmalige setup:**

1. Kopieer `claude-config/claude_desktop_config.example.json` naar je Claude Desktop config-map:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
2. Pas de paden aan (`/Users/JOUW_GEBRUIKER/...`) en herstart Claude Desktop.
3. Zorg dat de slash-commands uit stap 7 staan in `~/.claude/commands/`.

**Dagelijks gebruik:**

Vraag Claude Desktop simpelweg: *"Maak de dagkrant van vandaag."* Claude voert via de shell-MCP uit:

```bash
bash ~/nieuwsstation/scripts/dagkrant.sh
```

Het wrapper-script fetcht data, vraagt Claude om het redactionele plan (`/dagkrant`-command) en rendert de HTML. Daarna leest Claude Desktop het bestand uit `~/Documents/WorkMvMOBS/Briefings/` via de filesystem-MCP en toont de dagkrant direct in het gesprek.

**Handige flags:**

```bash
bash scripts/dagkrant.sh --with-api   # start ook de Achtergrond-server (poort 7432)
bash scripts/dagkrant.sh --open       # open het HTML-bestand in de standaard browser
bash scripts/dagkrant.sh --hours 48   # groter tijdvenster voor de fetch
```

Draait de api_server niet? Geen probleem: de "▶ Achtergrond"-knoppen detecteren dat en tonen een Claude-prompt die je direct in het gesprek kunt plakken (of simpelweg kunt uitvoeren als Claude Desktop de dagkrant al leest).

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
