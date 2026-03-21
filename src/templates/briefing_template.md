---
date: {{DATE}}
type: briefing
topics: [{{TOPICS}}]
podcast: {{HAS_PODCAST}}
bronnen: {{SOURCE_COUNT}}
generated: {{TIMESTAMP}}
---

# Ochtend Briefing — {{DATE_NL}}

{{TOPIC_TAGS}}

> [!podcast] Podcast
> ![[Briefings/podcast/audio/{{DATE}}.mp3]]
> NotebookLM · 2 hosts · {{DURATION}}

{{#each TOPIC_SECTIONS}}

## {{icon}} {{name}}

{{#each articles}}

### {{title}}

{{summary}}

> [!{{callout_type}}] {{callout_title}}
> {{callout_content}}

**Bronnen**: {{#each sources}}[{{name}}]({{url}}){{/each}}

{{/each}}

{{/each}}

## 🔗 Kruisverband-analyse

> [!analysis]
> {{CROSS_ANALYSIS}}

## Bronnen

{{#each ALL_SOURCES}}
{{index}}. [{{name}}]({{url}}) — {{type}}
{{/each}}

## Gerelateerde vault notes

{{#each VAULT_LINKS}}
[[{{name}}]]
{{/each}}
