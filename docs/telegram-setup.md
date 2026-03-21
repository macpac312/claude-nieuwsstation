# Telegram Bot Setup

## Stap 1: Bot aanmaken

1. Open Telegram, zoek **@BotFather**
2. Stuur `/newbot`
3. Naam: `Nieuwsstation`
4. Username: kies iets unieks, bijv. `mvm_nieuwsstation_bot`
5. Kopieer de bot token

## Stap 2: Claude Code Telegram plugin installeren

```bash
claude /plugin install telegram@claude-plugins-official
```

## Stap 3: Sessie starten

```bash
tmux new -s newsstation
claude --channels plugin:telegram@claude-plugins-official --dangerously-skip-permissions
```

## Stap 4: Pairing

1. DM je bot op Telegram — hij antwoordt met een pairing code
2. Voer de code in Claude Code in
3. Klaar — berichten vanuit Telegram bereiken nu je Claude Code sessie

## Stap 5: Persistent maken (optioneel)

systemd user service is al geïnstalleerd:

```bash
systemctl --user daemon-reload
systemctl --user enable --now nieuwsstation
```

## Gebruik via Telegram

- `/briefing` → volledige briefing alle topics
- `/briefing regulatoir huizenmarkt` → specifieke topics
- `/briefing "ECB rentebesluit analyse"` → met focus
- `Wat staat er in mijn vault over LGD floors?` → vault doorzoeken
- `Status?` → huidige sessie status
