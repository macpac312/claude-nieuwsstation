#!/usr/bin/env python3
"""Vertaalmodule voor het Nieuwsstation.

Vertaalt niet-Nederlandse artikelen naar het Nederlands via Google Translate
(deep-translator, geen API-key nodig). Valt terug op Argos Translate als
Google niet bereikbaar is.

Gebruik:
    python translator.py --input /tmp/rss.json --output /tmp/rss_nl.json
"""

import argparse
import json
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config" / "sources.yaml"


def needs_translation(text: str) -> bool:
    """Detecteer of tekst waarschijnlijk niet-Nederlands is."""
    if not text or len(text) < 20:
        return False
    en_markers = ["the ", " and ", " of ", " for ", " has ", " with ", " that ",
                  " from ", " this ", " which ", " will ", " have ", " been ",
                  " their ", " are ", " was ", " were ", " published ", " according ",
                  "the ", "this ", "these ", "those "]
    nl_markers = [" de ", " het ", " van ", " een ", " voor ", " met ", " dat ",
                  " die ", " naar ", " zijn ", " wordt ", " hebben ", " werd "]
    text_lower = text.lower()
    en_count = sum(1 for m in en_markers if m in text_lower)
    nl_count = sum(1 for m in nl_markers if m in text_lower)
    threshold = 1 if len(text) < 120 else 2
    return en_count > nl_count and en_count >= threshold


def _get_google_translator():
    """Geef een GoogleTranslator instantie terug, of None als niet beschikbaar."""
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source="en", target="nl")
    except Exception:
        return None


def _get_argos():
    """Geef Argos translate module terug, of None als niet beschikbaar."""
    try:
        from argostranslate import translate as _at
        return _at
    except ImportError:
        return None


def _translate_text(text: str, google, argos) -> str | None:
    """Vertaal één stuk tekst. Probeert Google, valt terug op Argos."""
    if google:
        try:
            return google.translate(text)
        except Exception as e:
            print(f"[WARN] Google Translate fout: {e} — terugvallen op Argos", file=sys.stderr)
    if argos:
        try:
            return argos.translate(text, "en", "nl")
        except Exception as e:
            print(f"[WARN] Argos Translate fout: {e}", file=sys.stderr)
    return None


def translate_batch(items: list[dict], **_kwargs) -> list[dict]:
    """Vertaal een batch artikelen. Primair Google Translate, fallback Argos."""
    google = _get_google_translator()
    argos  = _get_argos()

    if google:
        print("[INFO] Vertaalmotor: Google Translate (deep-translator)", file=sys.stderr)
    elif argos:
        print("[WARN] Google niet beschikbaar, gebruik Argos Translate als fallback", file=sys.stderr)
    else:
        print("[WARN] Geen vertaalmotor beschikbaar, vertaling overgeslagen", file=sys.stderr)
        return items

    translated_count = 0
    for item in items:
        title   = item.get("title", "")
        summary = item.get("summary", "")
        changed = False

        if needs_translation(title):
            result = _translate_text(title, google, argos)
            if result:
                item["title_original"] = title
                item["title"] = result
                changed = True

        if needs_translation(summary):
            result = _translate_text(summary, google, argos)
            if result:
                item["summary_original"] = summary
                item["summary"] = result
                changed = True

        if changed:
            item["translated"] = True
            translated_count += 1

    print(f"[OK] {translated_count} artikelen vertaald", file=sys.stderr)
    return items


def translate_rss(rss_data: dict, **_kwargs) -> dict:
    """Vertaal alle artikelen in RSS data."""
    for topic_id, topic_data in rss_data.get("topics", {}).items():
        items = topic_data.get("items", [])
        if items:
            topic_data["items"] = translate_batch(items)
    return rss_data


def main():
    parser = argparse.ArgumentParser(description="Nieuwsstation Vertaler")
    parser.add_argument("--input",  required=True, help="RSS JSON input")
    parser.add_argument("--output", help="Vertaald JSON output (default: overschrijft input)")
    parser.add_argument("--claude", default="claude", help="(genegeerd)")
    parser.add_argument("--model",  help="(genegeerd)")

    args = parser.parse_args()

    rss_data = json.loads(Path(args.input).read_text())
    translated = translate_rss(rss_data)

    output_path = Path(args.output) if args.output else Path(args.input)
    output_path.write_text(json.dumps(translated, ensure_ascii=False, indent=2))

    total = sum(1 for td in translated.get("topics", {}).values()
                for it in td.get("items", []) if it.get("translated"))
    print(f"[OK] {total} artikelen vertaald, opgeslagen: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
