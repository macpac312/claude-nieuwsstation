#!/usr/bin/env python3
"""Vertaalmodule voor het Nieuwsstation.

Vertaalt niet-Nederlandse artikelen naar het Nederlands via claude -p.
Vertaalt in batches voor efficiëntie.

Gebruik:
    python translator.py --input /tmp/rss.json --output /tmp/rss_nl.json
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def needs_translation(text: str) -> bool:
    """Detecteer of tekst waarschijnlijk niet-Nederlands is."""
    if not text or len(text) < 20:
        return False
    # Simpele heuristiek: check op veelvoorkomende Engelse woorden
    en_markers = ["the ", " and ", " of ", " for ", " has ", " with ", " that ",
                  " from ", " this ", " which ", " will ", " have ", " been ",
                  " their ", " are ", " was ", " were ", " published ", " according "]
    nl_markers = [" de ", " het ", " van ", " een ", " voor ", " met ", " dat ",
                  " die ", " naar ", " zijn ", " wordt ", " hebben ", " werd "]
    text_lower = text.lower()
    en_count = sum(1 for m in en_markers if m in text_lower)
    nl_count = sum(1 for m in nl_markers if m in text_lower)
    return en_count > nl_count and en_count >= 2


def translate_batch(items: list[dict], claude_path: str = "claude") -> list[dict]:
    """Vertaal een batch artikelen via claude -p.

    Stuurt titels en samenvattingen in batches van max 10 naar Claude.
    """
    # Verzamel te vertalen items
    to_translate = []
    index_map = {}

    for i, item in enumerate(items):
        title = item.get("title", "")
        summary = item.get("summary", "")
        if needs_translation(title) or needs_translation(summary):
            index_map[len(to_translate)] = i
            to_translate.append({
                "id": len(to_translate),
                "title": title,
                "summary": summary,
            })

    if not to_translate:
        print("[INFO] Geen artikelen om te vertalen", file=sys.stderr)
        return items

    # Vertaal in batches van max 10 om timeouts te voorkomen
    BATCH_SIZE = 10
    all_translations = []
    for batch_start in range(0, len(to_translate), BATCH_SIZE):
        batch = to_translate[batch_start:batch_start + BATCH_SIZE]
        print(f"[INFO] Batch {batch_start // BATCH_SIZE + 1}: {len(batch)} artikelen vertalen...", file=sys.stderr)
        result = _translate_single_batch(batch, claude_path)
        all_translations.extend(result)

    # Pas vertalingen toe
    translated_count = 0
    for trans in all_translations:
        batch_idx = trans.get("id")
        if batch_idx is not None and batch_idx in index_map:
            orig_idx = index_map[batch_idx]
            orig = items[orig_idx]
            orig["title_original"] = orig["title"]
            orig["summary_original"] = orig["summary"]
            orig["title"] = trans.get("title", orig["title"])
            orig["summary"] = trans.get("summary", orig["summary"])
            orig["translated"] = True
            translated_count += 1

    print(f"[OK] {translated_count} artikelen vertaald", file=sys.stderr)
    return items

def _translate_single_batch(batch: list[dict], claude_path: str) -> list[dict]:
    """Vertaal een enkele batch via claude -p."""
    prompt = f"""Vertaal de volgende {len(batch)} nieuwsartikelen naar het Nederlands.
Behoud de zakelijke toon. Geef ALLEEN valid JSON terug, geen andere tekst.

Input:
{json.dumps(batch, ensure_ascii=False)}

Geef terug als JSON array met dezelfde structuur:
[{{"id": 0, "title": "vertaalde titel", "summary": "vertaalde samenvatting"}}, ...]

ALLEEN de JSON array, geen markdown codeblocks, geen uitleg."""

    try:
        result = subprocess.run(
            [claude_path, "-p", prompt],
            capture_output=True, text=True, timeout=120,
            env={**__import__("os").environ,
                 "PATH": f"{Path.home()}/.local/bin:/usr/local/bin:/usr/bin:/bin"}
        )

        if result.returncode != 0:
            print(f"[WARN] Claude vertaling mislukt (code {result.returncode})",
                  file=sys.stderr)
            return items

        # Parse JSON uit output (strip eventuele markdown codeblocks)
        output = result.stdout.strip()
        # Verwijder markdown code fences als die er zijn
        output = re.sub(r'^```(?:json)?\s*', '', output)
        output = re.sub(r'\s*```$', '', output)

        return json.loads(output)

    except subprocess.TimeoutExpired:
        print("[WARN] Claude vertaling timeout voor batch", file=sys.stderr)
    except json.JSONDecodeError as e:
        print(f"[WARN] Kon vertaling niet parsen: {e}", file=sys.stderr)
    except FileNotFoundError:
        print("[WARN] Claude binary niet gevonden", file=sys.stderr)

    return []


def translate_rss(rss_data: dict, claude_path: str = "claude") -> dict:
    """Vertaal alle artikelen in RSS data."""
    for topic_id, topic_data in rss_data.get("topics", {}).items():
        items = topic_data.get("items", [])
        if items:
            topic_data["items"] = translate_batch(items, claude_path)
    return rss_data


def main():
    parser = argparse.ArgumentParser(description="Nieuwsstation Vertaler")
    parser.add_argument("--input", required=True, help="RSS JSON input")
    parser.add_argument("--output", help="Vertaald JSON output (default: overschrijft input)")
    parser.add_argument("--claude", default="claude", help="Pad naar claude binary")

    args = parser.parse_args()

    rss_data = json.loads(Path(args.input).read_text())
    translated = translate_rss(rss_data, args.claude)

    output_path = Path(args.output) if args.output else Path(args.input)
    output_path.write_text(json.dumps(translated, ensure_ascii=False, indent=2))

    # Tel vertalingen
    total = sum(1 for td in translated.get("topics", {}).values()
                for it in td.get("items", []) if it.get("translated"))
    print(f"[OK] {total} artikelen vertaald, opgeslagen: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
