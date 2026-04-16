---
name: nieuwsstation
description: >
  Persoonlijk nieuwsstation dat automatisch nieuws ophaalt, analyseert, en
  de dagkrant genereert in de Obsidian vault. Gebruik deze skill wanneer de
  gebruiker vraagt om een briefing, dagkrant, nieuwsoverzicht, of podcast paper.
  Triggert ook bij vragen over recente regulatoire updates, huizenmarkt
  nieuws, financieel nieuws, tech/AI nieuws, of sportnieuws.
---

# Nieuwsstation Skill

## Primaire output: De Dagkrant (HTML)

De dagkrant is de primaire output — een interactieve HTML-nieuwssite opgeslagen in:
`~/Documents/WorkMvMOBS/Briefings/YYYY-MM-DD-dagkrant.html`

De dagkrant vervangt de markdown briefing als standaard output.

## Wanneer te gebruiken

- Gebruiker vraagt om een briefing, dagkrant, of nieuwsoverzicht
- Gebruiker vraagt om een podcast paper
- Gebruiker vraagt naar recent nieuws over specifieke topics
- Gebruiker wil vault-context bij een nieuwsitem

## Volledige pipeline

### Fase A: Data ophalen (geautomatiseerd)

Voer de gecombineerde datafetch uit:
```bash
bash ~/nieuwsstation/scripts/fetch-dagkrant-data.sh --hours 24
```

Dit haalt op:
1. RSS feeds (rss_fetcher.py) → /tmp/dk-rss.json
2. Guardian API (guardian_fetcher.py) → gemergd in /tmp/dk-rss.json
3. FD RSS + full text (fd_fetcher.py) → /tmp/dk-fd.json
4. FD focus-archief (fd_fetcher.py --focus) → /tmp/dk-fd-focus.json
5. Gecombineerd → /tmp/dagkrant-ready.json

Configuratie: `~/nieuwsstation/src/config/sources.yaml`
Focus/actieve verhalen: `~/nieuwsstation/focus.md`

### Fase B: Dagkrant genereren

Genereer de HTML dagkrant via het /dagkrant command (zie ~/.claude/commands/dagkrant.md).
De data uit Fase A is al beschikbaar in /tmp/dagkrant-ready.json.

De dagkrant bevat een **drietrapsraket** per artikel:
- Trap 1: ingeklapt — titel + teaser (altijd zichtbaar)
- Trap 2: uitgeklapt — samenvatting + bronlinks (klik op kaart)
- Trap 3: achtergrond — on-demand gegenereerd via api_server.py (▶ Achtergrond knop)

### Fase C: Achtergrond API starten (optioneel)

Voor on-demand achtergrond-generatie bij ▶ knoppen in de dagkrant:
```bash
python3 ~/nieuwsstation/src/api_server.py &
```

De server luistert op http://127.0.0.1:7432. Blijft actief totdat het terminal-venster
gesloten wordt. Elke ▶ Achtergrond-knop in de dagkrant roept deze server aan.

## Model gebruik

- **Fase A (data fetch)**: geen model (pure data)
- **Fase B (dagkrant)**: Claude Opus 4.7 voor redactionele kwaliteit
- **Fase C (achtergrond on-demand)**: Claude Sonnet 4.6 voor snelheid

## Podcast paper (optioneel)

Genereer een podcast paper van 2000-3000 woorden als plain tekst .md:
- Locatie: `~/Documents/WorkMvMOBS/Briefings/podcast/YYYY-MM-DD.md`
- Geoptimaliseerd voor NotebookLM Audio Overview
- Dekt alle secties van de dagkrant + kruisverbanden

## Schrijfstijl

- Nederlands
- NRC / Financial Times kwaliteit
- Analytisch, niet sensationeel
- Rabobank/IRB/AVM context waar relevant
