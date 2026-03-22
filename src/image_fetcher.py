#!/usr/bin/env python3
"""Image Fetcher — haalt og:image meta tags op voor artikelen zonder afbeelding.

Gebruik:
    python image_fetcher.py --input /tmp/rss.json --output /tmp/rss_images.json
"""

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

HEADERS = {"User-Agent": "Nieuwsstation/1.0 (Image Fetcher)"}
TIMEOUT = 8


def fetch_og_image(url: str) -> str:
    """Haal og:image meta tag op van een URL."""
    try:
        # Alleen de head ophalen, niet de hele pagina
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT,
                            allow_redirects=True, stream=True)
        # Lees max 50KB
        content = resp.raw.read(50000).decode("utf-8", errors="ignore")

        # Zoek og:image
        match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            content, re.IGNORECASE
        )
        if match:
            return match.group(1)

        # Fallback: twitter:image
        match = re.search(
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
            content, re.IGNORECASE
        )
        if match:
            return match.group(1)

    except Exception:
        pass

    return ""


def enrich_images(rss_data: dict, max_workers: int = 5) -> dict:
    """Voeg og:image toe aan artikelen zonder afbeelding."""
    tasks = []

    for topic_data in rss_data.get("topics", {}).values():
        for item in topic_data.get("items", []):
            if not item.get("image_url") and item.get("link"):
                tasks.append(item)

    if not tasks:
        print("[INFO] Alle artikelen hebben al een afbeelding", file=sys.stderr)
        return rss_data

    print(f"[INFO] og:image ophalen voor {len(tasks)} artikelen...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_og_image, item["link"]): item for item in tasks}
        found = 0
        for future in as_completed(futures):
            item = futures[future]
            img = future.result()
            if img:
                item["image_url"] = img
                found += 1

    print(f"[OK] {found}/{len(tasks)} og:images gevonden", file=sys.stderr)
    return rss_data


def main():
    p = argparse.ArgumentParser(description="Nieuwsstation Image Fetcher")
    p.add_argument("--input", required=True, help="RSS JSON input")
    p.add_argument("--output", help="Output (default: overschrijft input)")

    a = p.parse_args()
    data = json.loads(Path(a.input).read_text())
    enriched = enrich_images(data)

    out = Path(a.output) if a.output else Path(a.input)
    out.write_text(json.dumps(enriched, ensure_ascii=False, indent=2))

    total_img = sum(1 for td in enriched.get("topics", {}).values()
                    for it in td.get("items", []) if it.get("image_url"))
    total = sum(len(td.get("items", [])) for td in enriched.get("topics", {}).values())
    print(f"[OK] {total_img}/{total} artikelen hebben nu een afbeelding", file=sys.stderr)


if __name__ == "__main__":
    main()
