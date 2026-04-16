# /briefing

Genereer een dagelijkse nieuwsbriefing en sla deze op in de Obsidian vault.

## Instructies

1. Lees de configuratie: ~/nieuwsstation/src/config/sources.yaml
2. Voer het RSS fetch script uit: python3 ~/nieuwsstation/src/rss_fetcher.py
3. Vertaal niet-Nederlandse artikelen: python3 ~/nieuwsstation/src/translator.py
4. Doorzoek de vault op context: python3 ~/nieuwsstation/src/vault_search.py
5. Genereer de HTML-briefing: python3 ~/nieuwsstation/src/briefing_renderer.py
6. Schrijf de podcast paper
7. Geef een samenvatting van de highlights

## Parameters

$ARGUMENTS wordt gebruikt als topic-filter en/of focus-prompt.

Voorbeelden:
- /briefing → alle geconfigureerde topics
- /briefing regulatoir huizenmarkt → alleen die topics
- /briefing "Focus op CRR3 leverage ratio impact" → alle topics met focus

## Stap-voor-stap

### Stap 1: Configuratie lezen
Lees ~/nieuwsstation/src/config/sources.yaml om te weten welke topics en feeds beschikbaar zijn.

### Stap 2: RSS feeds ophalen
```bash
python3 ~/nieuwsstation/src/rss_fetcher.py --topics <TOPICS> --hours 24 --output /tmp/nieuwsstation_rss.json
```
Als geen topics opgegeven: gebruik --all.

### Stap 3: Vertalen naar Nederlands
Vertaal niet-Nederlandse artikelen automatisch:
```bash
python3 ~/nieuwsstation/src/translator.py --input /tmp/nieuwsstation_rss.json --output /tmp/nieuwsstation_rss.json
```
Dit vertaalt Engelse titels en samenvattingen naar Nederlands via Claude. Originelen worden bewaard.

### Stap 4: Vault doorzoeken
```bash
python3 ~/nieuwsstation/src/vault_search.py --news-json /tmp/nieuwsstation_rss.json --top 10 --output /tmp/nieuwsstation_vault.json
```

### Stap 5: HTML-briefing genereren
```bash
python3 ~/nieuwsstation/src/briefing_renderer.py --rss /tmp/nieuwsstation_rss.json --vault /tmp/nieuwsstation_vault.json
```
Dit genereert ~/Documents/WorkMvMOBS/Briefings/YYYY-MM-DD.md met:
- Topic tabs bovenaan
- Uitklapbare artikel-cards met impact callouts
- Bewaar-knoppen (obsidian:// URI)
- 🌐 NL badge bij vertaalde artikelen
- Bronnen-pills, actieknoppen
- Kruisverband-analyse sectie
- Vault link pills

### Stap 6: Podcast paper schrijven
Schrijf een podcast paper (2000-4000 woorden) geoptimaliseerd voor NotebookLM:
- Helder gestructureerd met koppen
- Meerdere perspectieven/spanningspunten
- Geschreven alsof het een briefingdocument is voor twee analisten
- GEEN wikilinks (NotebookLM begrijpt die niet)

Sla op als: ~/Documents/WorkMvMOBS/Briefings/podcast/YYYY-MM-DD.md

### Stap 7: Directories aanmaken
```bash
mkdir -p ~/Documents/WorkMvMOBS/Briefings/podcast/audio ~/Documents/WorkMvMOBS/Clippings
```

## Schrijfstijl

- Nederlands
- Professioneel maar toegankelijk
- Gebruik [[wikilinks]] voor vault-referenties
- Gebruik Obsidian callouts: > [!info], > [!warning], > [!tip]
- Datums in Nederlands formaat: 20 maart 2026

## Na afloop

Meld aan de gebruiker:
- Welke topics behandeld zijn
- Hoeveel bronnen verwerkt en vertaald
- Top 3-5 highlights
- Pad naar de briefing note
- Pad naar de podcast paper
- Reminder: "Upload podcast paper naar NotebookLM voor Audio Overview"
