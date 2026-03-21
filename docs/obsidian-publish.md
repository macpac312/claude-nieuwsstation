# Obsidian Publish Setup

Het Nieuwsstation genereert briefings als HTML-enhanced markdown die
compatible zijn met Obsidian Publish.

## Hoe het werkt

- Briefings gebruiken `<details>/<summary>` voor uitklapbare artikelen
- Inline HTML met Catppuccin Mocha styling
- CSS snippet voor animaties en hover-effecten
- Alles renderbaar in reading view en Publish

## Setup

### 1. CSS Snippet activeren

De snippet staat in `.obsidian/snippets/nieuwsstation.css`.

In Obsidian:
1. Settings → Appearance → CSS snippets
2. Activeer "nieuwsstation"

### 2. Publish configuratie

Bij Obsidian Publish:
1. Voeg `Briefings/` map toe aan published files
2. Upload de CSS snippet via Publish settings → "publish.css"
3. De `cssclasses: [nieuwsstation, ns-briefing]` in frontmatter
   zorgt ervoor dat de styling automatisch wordt toegepast

### 3. publish.css

Kopieer de inhoud van `.obsidian/snippets/nieuwsstation.css` naar
je Publish site's `publish.css` bestand.

## Wat werkt op Publish

| Feature | Publish | Reading View |
|---------|---------|-------------|
| Uitklapbare artikelen | ✅ | ✅ |
| Bronnen-pills met links | ✅ | ✅ |
| Hero nieuws-cards | ✅ | ✅ |
| Topic kleuren | ✅ | ✅ |
| Actieknoppen | ✅ | ✅ |
| SVG charts | ✅ | ✅ |
| Wikilinks | ✅ | ✅ |
| Podcast embed | ❌ (audio) | ✅ |
| CSS animaties | ✅ | ✅ |

## Wat NIET werkt op Publish

- De sidebar Command Center plugin (dat is een custom view)
- Audio player voor podcasts (mp3 embedding)
- Actieknoppen die Claude aanroepen (die zijn visueel maar niet functioneel op Publish)
