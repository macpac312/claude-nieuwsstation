#!/usr/bin/env python3
"""
NotebookLM Uploader — stuurt podcast paper automatisch naar NotebookLM.

Gebruik:
    python3 notebooklm_uploader.py --setup
        Eerste keer: opent browser voor eenmalige Google-login

    python3 notebooklm_uploader.py --file /pad/naar/podcast.md --title "Dagkrant 2026-04-06"
        Upload en start Audio Overview generatie. Print notebook-URL naar stdout.

    python3 notebooklm_uploader.py --latest
        Upload het meest recente podcast paper uit ~/Documents/WorkMvMOBS/Briefings/podcast/

Sessie wordt opgeslagen in ~/.config/notebooklm-session/ (aparte Chromium, raakt Chrome niet aan).
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

SESSION_DIR = Path.home() / ".config" / "notebooklm-session"
PODCAST_DIR = Path.home() / "Documents" / "WorkMvMOBS" / "Briefings" / "podcast"
NLM_URL = "https://notebooklm.google.com"


def find_latest_podcast() -> Path | None:
    """Zoek het meest recente podcast .md bestand."""
    if not PODCAST_DIR.exists():
        return None
    files = sorted(PODCAST_DIR.glob("*.md"), reverse=True)
    return files[0] if files else None


async def _get_context(playwright):
    """Maak of herstel persistent browser context."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    # Verwijder eventuele lock-bestanden van vorige sessies
    for lock in SESSION_DIR.glob("Singleton*"):
        try:
            lock.unlink()
        except Exception:
            pass
    return await playwright.chromium.launch_persistent_context(
        user_data_dir=str(SESSION_DIR),
        headless=False,
        channel=None,   # Playwright's eigen Chromium
        args=[
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
        ],
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
        locale="nl-NL",
    )


async def setup_login():
    """Eenmalige setup: open browser zodat gebruiker kan inloggen."""
    from playwright.async_api import async_playwright
    print("[NotebookLM] Setup: browser openen voor eenmalige Google-login...")
    print(f"[NotebookLM] Sessiemap: {SESSION_DIR}")

    async with async_playwright() as p:
        ctx = await _get_context(p)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(NLM_URL)
        print("[NotebookLM] Log in met je Google-account en druk dan op Enter hier.")
        input("[NotebookLM] Klaar met inloggen? Druk Enter om door te gaan: ")
        await ctx.close()
    print("[NotebookLM] Sessie opgeslagen. Je kunt nu de uploader gebruiken.")


async def upload_and_generate(file_path: Path, title: str, focus: str = "") -> str:
    """
    Upload podcast paper naar NotebookLM en start Audio Overview.
    Returns: notebook URL
    """
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout

    if not file_path.exists():
        raise FileNotFoundError(f"Bestand niet gevonden: {file_path}")

    print(f"[NotebookLM] Uploaden: {file_path.name}", file=sys.stderr)
    print(f"[NotebookLM] Titel: {title}", file=sys.stderr)

    async with async_playwright() as p:
        ctx = await _get_context(p)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # ── Navigeer naar NotebookLM ──────────────────────────────────────
        await page.goto(NLM_URL, wait_until="domcontentloaded", timeout=60000)

        # Check ingelogd (redirect naar login als niet)
        if "accounts.google.com" in page.url or "signin" in page.url:
            await ctx.close()
            raise RuntimeError(
                "Niet ingelogd bij Google. Voer eerst uit:\n"
                "  python3 notebooklm_uploader.py --setup"
            )

        # ── Maak nieuw notebook ───────────────────────────────────────────
        print("[NotebookLM] Nieuw notebook aanmaken...", file=sys.stderr)

        # Zoek "Create" of "New notebook" knop (tekst varieert per versie)
        new_btn = None
        for selector in [
            'button:has-text("Create")',
            'button:has-text("New notebook")',
            '[aria-label="Create new notebook"]',
            '[data-test-id="create-notebook-button"]',
        ]:
            try:
                new_btn = page.locator(selector).first
                await new_btn.wait_for(state="visible", timeout=5000)
                break
            except PWTimeout:
                new_btn = None

        if not new_btn:
            await ctx.close()
            raise RuntimeError("Kon 'New notebook' knop niet vinden. Mogelijk UI-wijziging.")

        await new_btn.click()

        # Wacht tot URL verandert van /creating naar een echte notebook-UUID
        print("[NotebookLM] Wachten op notebook aanmaak...", file=sys.stderr)
        try:
            await page.wait_for_url(lambda u: "/notebook/" in u and "creating" not in u, timeout=20000)
        except PWTimeout:
            pass
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
        await page.wait_for_timeout(2000)

        notebook_url = page.url
        print(f"[NotebookLM] Notebook URL: {notebook_url}", file=sys.stderr)

        # ── Upload bestand als bron ───────────────────────────────────────
        print("[NotebookLM] Bron uploaden...", file=sys.stderr)

        # NotebookLM opent automatisch een popup na aanmaken (addSource=true)
        # Of we klikken zelf op "Add sources"
        # Wacht eerst tot de pagina klaar is
        await page.wait_for_timeout(2000)

        # Probeer popup te openen als die nog niet open is
        upload_btn_visible = False
        try:
            await page.get_by_role("button", name="Upload files").wait_for(state="visible", timeout=4000)
            upload_btn_visible = True
            print("[NotebookLM] Upload popup al open.", file=sys.stderr)
        except PWTimeout:
            # Klik op Add sources om popup te openen
            for selector in [
                'button:has-text("Add source")',
                'button:has-text("Add sources")',
                '[aria-label="Add source"]',
            ]:
                try:
                    btn = page.locator(selector).first
                    await btn.wait_for(state="visible", timeout=5000)
                    await btn.click()
                    await page.wait_for_timeout(2000)
                    break
                except PWTimeout:
                    continue

        # Upload via file chooser — klik "Upload files" knop
        print("[NotebookLM] Zoeken naar Upload files knop...", file=sys.stderr)
        uploaded = False

        # Probeer get_by_role eerst (meest stabiel)
        for attempt in range(3):
            try:
                upload_btn = page.get_by_role("button", name="Upload files")
                await upload_btn.wait_for(state="visible", timeout=5000)
                async with page.expect_file_chooser(timeout=10000) as fc_info:
                    await upload_btn.click()
                fc = await fc_info.value
                await fc.set_files(str(file_path))
                print(f"[NotebookLM] Bestand geselecteerd via get_by_role (poging {attempt+1}).", file=sys.stderr)
                uploaded = True
                break
            except Exception as e:
                print(f"[NotebookLM] Poging {attempt+1} mislukt: {e}", file=sys.stderr)
                await page.wait_for_timeout(2000)

        # Fallback: direct via hidden file input
        if not uploaded:
            try:
                file_input = page.locator('input[type="file"]').first
                await file_input.wait_for(state="attached", timeout=8000)
                await file_input.set_input_files(str(file_path))
                print("[NotebookLM] Bestand via file input geselecteerd.", file=sys.stderr)
                uploaded = True
            except Exception as e:
                print(f"[NotebookLM] File input fallback mislukt: {e}", file=sys.stderr)

        if not uploaded:
            print("[NotebookLM] WAARSCHUWING: bestand kon niet worden geüpload.", file=sys.stderr)

        # Wacht op verwerking bron (spinner verdwijnt, status verschijnt)
        print("[NotebookLM] Wachten op bronverwerking (max 2 min)...", file=sys.stderr)
        await page.wait_for_timeout(3000)

        # Wacht tot source-kaartje zichtbaar is
        for _ in range(24):  # max 2 minuten (24 × 5s)
            try:
                # Zoek op bestandsnaam of "source" status indicator
                src = page.locator(f'text="{file_path.stem}"').first
                await src.wait_for(state="visible", timeout=5000)
                print("[NotebookLM] Bron verwerkt.", file=sys.stderr)
                break
            except PWTimeout:
                await page.wait_for_timeout(5000)

        # ── Start Audio Overview via Studio-panel ─────────────────────────
        print("[NotebookLM] Audio Overview starten...", file=sys.stderr)
        await page.wait_for_timeout(3000)

        # Screenshot voor debugging
        try:
            await page.screenshot(path="/tmp/nlm_debug.png", full_page=False)
            print("[NotebookLM] Screenshot: /tmp/nlm_debug.png", file=sys.stderr)
        except Exception:
            pass

        audio_started = False

        # Stap 1: klik op de "Audio Overview" kaart in het Studio-panel (rechts).
        # De kaart is geen <button> maar een klikbare div/Angular component.
        # Gebruik JavaScript voor de meest betrouwbare aanpak.
        audio_overview_opened = False

        # Probeer eerst standaard Playwright-selectors
        for selector in [
            ':text-is("Audio Overview")',
            ':text("Audio Overview")',
            '[aria-label*="Audio Overview"]',
            'button:has-text("Audio Overview")',
        ]:
            try:
                el = page.locator(selector).first
                await el.wait_for(state="visible", timeout=4000)
                await el.click()
                audio_overview_opened = True
                print(f"[NotebookLM] Audio Overview geopend via selector: {selector}", file=sys.stderr)
                await page.wait_for_timeout(2000)
                break
            except Exception:
                continue

        # JavaScript fallback: klik eerste element met exacte tekst "Audio Overview"
        if not audio_overview_opened:
            try:
                clicked = await page.evaluate("""
                    () => {
                        // Zoek element met exact tekst "Audio Overview"
                        const walker = document.createTreeWalker(
                            document.body, NodeFilter.SHOW_TEXT, null, false);
                        let node;
                        while ((node = walker.nextNode())) {
                            if (node.textContent.trim() === 'Audio Overview') {
                                let el = node.parentElement;
                                // Loop omhoog naar klikbaar element
                                for (let i = 0; i < 5; i++) {
                                    if (el && el.offsetParent !== null) {
                                        el.click();
                                        return el.tagName + '.' + (el.className||'').slice(0,40);
                                    }
                                    el = el && el.parentElement;
                                }
                            }
                        }
                        return null;
                    }
                """)
                if clicked:
                    audio_overview_opened = True
                    print(f"[NotebookLM] Audio Overview geklikt via JS: {clicked}", file=sys.stderr)
                    await page.wait_for_timeout(2000)
                else:
                    # Debug: alle elementen met "audio" tekst
                    audio_els = await page.evaluate("""
                        () => {
                            const found = [];
                            document.querySelectorAll('*').forEach(el => {
                                const t = (el.textContent||'').trim();
                                if (t.toLowerCase().includes('audio') && t.length < 80
                                    && el.children.length <= 2 && el.offsetParent !== null) {
                                    found.push({tag:el.tagName, text:t.slice(0,60),
                                               cls:(el.className||'').slice(0,40)});
                                }
                            });
                            return found.slice(0, 20);
                        }
                    """)
                    print(f"[NotebookLM] Audio-elementen op pagina: {audio_els}", file=sys.stderr)
            except Exception as e:
                print(f"[NotebookLM] JS Audio Overview fout: {e}", file=sys.stderr)

        # Stap 2: na openen Audio Overview kaart → Customize dialog
        # Debug knoppen na eventueel openen
        try:
            all_btns = await page.locator("button").all()
            btn_info = []
            for btn in all_btns[:30]:
                text = (await btn.text_content() or "").strip()[:20]
                aria = (await btn.get_attribute("aria-label") or "")[:40]
                if text or aria:
                    btn_info.append(f"[{text}|{aria}]")
            print(f"[NotebookLM] Knoppen na Audio Overview klik: {btn_info}", file=sys.stderr)
        except Exception:
            pass

        # Zoek Customize knop (opent dialog met focus-veld, taal, Deep Dive)
        customize_found = False
        for selector in [
            'button:has-text("Customize")',
            '[aria-label="Customize audio overview"]',
            '[aria-label*="Customize"]',
            '[aria-label*="ustomize"]',
        ]:
            try:
                cust_btn = page.locator(selector).first
                await cust_btn.wait_for(state="visible", timeout=6000)
                await cust_btn.click()
                customize_found = True
                print(f"[NotebookLM] Customize geopend via: {selector}", file=sys.stderr)
                await page.wait_for_timeout(2000)
                break
            except Exception:
                continue

        # Stap 3: in de Customize-dialog (of direct Generate)
        async def _fill_and_generate():
            """Vul focus in en klik Generate. Return True als gelukt."""
            # Deep Dive selecteren (optioneel)
            for sel in ['button:has-text("Deep Dive")', '[aria-label="Deep Dive"]']:
                try:
                    await page.locator(sel).first.click()
                    print("[NotebookLM] Deep Dive geselecteerd.", file=sys.stderr)
                    break
                except Exception:
                    pass

            # Taal instellen op Nederlands (optioneel)
            for sel in ['select', '[role="combobox"]']:
                try:
                    lang = page.locator(sel).first
                    await lang.wait_for(state="visible", timeout=2000)
                    await lang.select_option(label="Nederlands")
                    print("[NotebookLM] Taal: Nederlands.", file=sys.stderr)
                    break
                except Exception:
                    pass

            # Focus tekst invullen
            if focus:
                print(f"[NotebookLM] Focus invullen: {focus[:60]}…", file=sys.stderr)
                focus_filled = False
                for sel in [
                    'textarea[placeholder*="focus"]',
                    'textarea[placeholder*="What should"]',
                    'textarea[placeholder*="hosts"]',
                    'textarea',
                ]:
                    try:
                        tf = page.locator(sel).first
                        await tf.wait_for(state="visible", timeout=5000)
                        await tf.click()
                        await tf.fill(focus)
                        focus_filled = True
                        print(f"[NotebookLM] Focus ingevuld via: {sel}", file=sys.stderr)
                        break
                    except Exception:
                        continue
                if not focus_filled:
                    print("[NotebookLM] Focus niet ingevuld (geen textarea gevonden).", file=sys.stderr)

            # Generate knop klikken
            for sel in [
                'button:has-text("Generate")',
                '[aria-label="Generate"]',
                'button:has-text("Genereer")',
            ]:
                try:
                    gb = page.locator(sel).first
                    await gb.wait_for(state="visible", timeout=6000)
                    await gb.click()
                    print(f"[NotebookLM] Generate geklikt via: {sel}", file=sys.stderr)
                    return True
                except Exception:
                    continue
            return False

        if customize_found:
            audio_started = await _fill_and_generate()

        # Fallback: geen Customize dialog → direct Generate proberen
        if not audio_started:
            print("[NotebookLM] Geen Customize dialog, probeer directe Generate...", file=sys.stderr)
            audio_started = await _fill_and_generate()

        if not audio_started:
            try:
                await page.screenshot(path="/tmp/nlm_generate_fail.png", full_page=True)
                print("[NotebookLM] Fail screenshot: /tmp/nlm_generate_fail.png", file=sys.stderr)
            except Exception:
                pass
            print("[NotebookLM] Kon Generate-knop niet vinden — mogelijk al gegenereerd "
                  "of UI-wijziging.", file=sys.stderr)

        # Geef browser even de tijd voor URL-update
        await page.wait_for_timeout(2000)
        final_url = page.url

        await ctx.close()
        return final_url


def main():
    parser = argparse.ArgumentParser(description="NotebookLM Uploader")
    parser.add_argument("--setup", action="store_true",
                        help="Eenmalige login-setup")
    parser.add_argument("--file", type=Path,
                        help="Pad naar podcast .md bestand")
    parser.add_argument("--latest", action="store_true",
                        help="Upload meest recente podcast paper")
    parser.add_argument("--title",
                        help="Notebook titel (default: bestandsnaam)")
    parser.add_argument("--focus", default="",
                        help="Focus-tekst voor NotebookLM Audio Overview")
    args = parser.parse_args()

    if args.setup:
        asyncio.run(setup_login())
        return

    # Bepaal bestand
    file_path = None
    if args.file:
        file_path = args.file
    elif args.latest:
        file_path = find_latest_podcast()
        if not file_path:
            print(json.dumps({"error": f"Geen podcast papers gevonden in {PODCAST_DIR}"}))
            sys.exit(1)
    else:
        parser.error("Geef --file, --latest of --setup op")

    # Bepaal titel
    title = args.title
    if not title:
        # Probeer datum uit bestandsnaam: 2026-04-06.md → "Dagkrant 6 april 2026"
        stem = file_path.stem  # "2026-04-06"
        try:
            d = datetime.strptime(stem, "%Y-%m-%d")
            title = f"Dagkrant {d.strftime('%-d %B %Y')}"
        except ValueError:
            title = f"Dagkrant {stem}"

    try:
        url = asyncio.run(upload_and_generate(file_path, title, focus=args.focus))
        # Print JSON naar stdout zodat api_server het kan parsen
        print(json.dumps({"url": url, "title": title, "file": str(file_path)}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
