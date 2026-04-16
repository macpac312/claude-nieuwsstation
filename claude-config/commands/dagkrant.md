Genereer en toon **De Dagkrant** als interactieve HTML in dit gesprek.

## Stappenplan (volg ze EXACT in volgorde)

### Stap 1 — Nieuws ophalen
Roep tool aan: `nieuwsstation.fetch_news(hours=24)`

Resultaat: dict met `selected.topics` (per sectie geselecteerde artikelen),
`widgets` (weer + markten + trends), en `stats` (aantallen, logs).

### Stap 2 — Focus lezen (optioneel)
Lees `~/nieuwsstation/focus.md` via filesystem-MCP indien aanwezig.
Dit bevat actieve onderwerpen die prioriteit verdienen in topnieuws/hero.

### Stap 3 — Redactioneel plan bouwen
Bouw in-context een JSON-plan volgens onderstaand schema. Gebruik UITSLUITEND
artikelen uit `selected.topics` en widgets uit `widgets`. Voer GEEN extra
WebFetch of WebSearch uit.

### Stap 4 — Renderen
Roep tool aan: `nieuwsstation.render_dagkrant(plan)` met het plan-object
als enige argument. Resultaat bevat `path`, `size_kb`, `open_url`.

### Stap 5 — HTML tonen
Lees het bestand op `result.path` via filesystem-MCP en toon de HTML inline
in dit gesprek (Claude Desktop rendert HTML rechtstreeks).

---

## JSON-schema voor het plan (Stap 3)

```json
{
  "datum":     "donderdag 16 april 2026",
  "datum_iso": "2026-04-16",
  "tijd":      "09:00",
  "tijdzone":  "CEST",

  "widgets": {
    "weer_temp":  "14",
    "weer_icon":  "🌦️",
    "aex":        "876",  "aex_pct":    "-0.3%",
    "sp500":      "5234", "sp500_pct":  "-1.2%",
    "brent":      "67.80","brent_pct":  "+0.5%",
    "eurusd":     "1.094",
    "verkeer":    "A27/A28 — zie ANWB",
    "brent_trend": [80,82,85,83,88,86,84,87,90,88,85,86,84,87,89]
  },

  "breaking": [
    "Korte headline 1",
    "Korte headline 2",
    "Korte headline 3"
  ],

  "hero": {
    "id":          "hero",
    "titel":       "...",
    "lead":        "1-2 zinnen lead.",
    "body_md":     "Paragraaf 1.\n\nParagraaf 2.\n\nParagraaf 3.",
    "trap3_md":    null,
    "bronnen":     [{"naam": "Guardian", "url": "https://..."}],
    "foto_url":    "",
    "foto_credit": "",
    "tag":         "wereld",
    "tag_label":   "Wereld",
    "datum":       "16 apr"
  },

  "topnieuws": [
    {
      "id":       "top1",
      "titel":    "...",
      "teaser":   "1-2 korte zinnen.",
      "body_md":  "Paragraaf 1.\n\nParagraaf 2.",
      "trap3_md": null,
      "bronnen":  [{"naam": "NOS", "url": "https://..."}],
      "tag":      "nederland", "tag_label": "Nederland",
      "datum":    "16 apr, 08:00 CEST"
    }
  ],

  "secties": {
    "nederland":  {"artikelen": [...]},
    "wereld":     {"artikelen": [...]},
    "financieel": {
      "artikelen": [...],
      "koersen": [
        {"naam": "AEX",     "waarde": "876",    "delta": "-0.3%"},
        {"naam": "S&P 500", "waarde": "5234",   "delta": "-1.2%"},
        {"naam": "Brent",   "waarde": "$67.80", "delta": "+0.5%"},
        {"naam": "EUR/USD", "waarde": "1.094",  "delta": "+0.1%"}
      ]
    },
    "sport":  {"artikelen": [...]},
    "aitech": {"artikelen": [...]}
  },

  "kruisverband_md": "150-250 woorden analyse die rode draden tussen secties blootlegt.",
  "vault_connecties": ["Term1", "Term2"],
  "bronnen_lijst": ["NOS", "Guardian", "FD"]
}
```

## Artikel-schema (binnen `topnieuws` en `secties.*.artikelen`)

```json
{
  "id":       "unieke-slug",
  "titel":    "...",
  "teaser":   "1-2 zinnen.",
  "body_md":  "2 paragrafen context/duiding.",
  "trap3_md": null,
  "bronnen":  [{"naam": "NOS", "url": "https://..."}],
  "tag":      "nederland|wereld|financieel|sport|aitech",
  "tag_label":"Nederland|Wereld|Financieel|Sport|AI & Tech",
  "datum":    "16 apr, 08:00 CEST"
}
```

## Inhoudelijke regels

### Aantallen
- `topnieuws`: precies 5 artikelen
- Per sectie: 3-4 artikelen
- `trap3_md`: altijd `null` (achtergrond komt on-demand via `generate_background`-tool)
- Hero: 1 artikel met langere `body_md` (3 paragrafen)

### Prioritering
- Onderwerpen uit `~/nieuwsstation/focus.md` krijgen voorrang in topnieuws/hero
- AI/Anthropic-nieuws altijd bovenaan in de aitech-sectie
- FD-artikelen domineren financieel
- Regulatoir nieuws (EBA/ECB/DNB/AFM) hoort in een eigen sectie als die er is

### Stijl van `body_md`
- Nederlands
- `\n\n` voor nieuwe alinea's
- `**vet**` voor nadruk
- `> citaat` voor quotes

### Widgets
- Gebruik `widgets`-waarden EXACT zoals teruggegeven door `fetch_news`
- Vervang `"?"` door `"—"` in de output

## Aanvullende instructies van de gebruiker
$ARGUMENTS
