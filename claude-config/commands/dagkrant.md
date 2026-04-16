Genereer een redactioneel plan voor De Dagkrant als JSON-bestand.

## Input — data staat al klaar, haal NIETS op

Lees de volgende bestanden:
1. `/tmp/dagkrant-selected.json` — voorgeselecteerde nieuwsartikelen
2. `/tmp/dagkrant-widgets.json` — pre-gefetchte widgets (weer, markten)
3. `~/nieuwsstation/focus.md` — focus-onderwerpen

Voer GEEN WebFetch of WebSearch uit. Gebruik uitsluitend de gelezen data.
Foto's: gebruik `foto_url: ""` en `foto_credit: ""`.

## Output: schrijf JSON naar /tmp/dagkrant-plan.json

Schrijf het onderstaande JSON-object naar `/tmp/dagkrant-plan.json` via de Write tool.
Schrijf ALLEEN het JSON-object, geen toelichting, geen markdown opmaak.

Vereist JSON-schema:
```
{
  "datum":     "zondag 6 april 2026",
  "datum_iso": "2026-04-06",
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
    "datum":       "6 apr"
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
      "datum":    "6 apr, 08:00 CEST"
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

  "kruisverband_md": "150-250 woorden analyse.",
  "vault_connecties": ["Term1", "Term2"],
  "bronnen_lijst": ["NOS", "Guardian", "FD"]
}
```

## Artikel-schema

Elk artikel in `topnieuws` en `secties`:
```
{
  "id":       "unieke-slug",
  "titel":    "...",
  "teaser":   "1-2 zinnen.",
  "body_md":  "2 paragrafen context/duiding.",
  "trap3_md": null,
  "bronnen":  [{"naam": "NOS", "url": "https://..."}],
  "tag":      "nederland|wereld|financieel|sport|aitech",
  "tag_label":"Nederland|Wereld|Financieel|Sport|AI & Tech",
  "datum":    "6 apr, 08:00 CEST"
}
```

## Inhoudelijke instructies

### Aantallen
- `topnieuws`: precies 5 artikelen
- Per sectie: 3-4 artikelen
- `trap3_md`: altijd `null` (achtergrond op aanvraag via knoppen in de HTML)
- Hero: 1 artikel met langere `body_md` (3 paragrafen)

### Prioritering
- Focus-onderwerpen uit focus.md krijgen prioriteit
- AI/Anthropic-nieuws altijd in aitech-sectie bovenaan
- FD-artikelen voor financieel

### Stijl body_md
- Schrijf in het Nederlands
- Gebruik `\n\n` voor nieuwe alinea's
- Nadruk: `**vet**`
- Citaten: `> tekst`

### Widgets
- Gebruik de waarden uit `/tmp/dagkrant-widgets.json` exact zoals ze zijn
- Als een waarde "?" is, gebruik dan "—"

## Secties en aanpassingen
$ARGUMENTS
