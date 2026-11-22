import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        page = await context.new_page()

        # 1. Inspect About Page
        print("=== 1. ACESSANDO SOBRE / ABOUT ===")
        await page.goto("https://www.youtube.com/@ESeocifial", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        
        # Click more info / about if available
        title = await page.title()
        print("Titulo da pagina:", title)
        
        # Extract description and links
        about_text = ""
        try:
            # Let's open the description modal / about
            more_btn = page.locator("#description-inner, #channel-header, ytd-channel-tagline-renderer")
            all_text = await page.locator("ytd-channel-metadata-renderer, ytd-about-channel-renderer, #channel-header").all_text_contents()
            print("Channel Header Text:", "\n".join(all_text))
        except Exception as e:
            print("Erro ao ler header:", e)

        # 2. Inspect specific videos
        video_ids = ["9vUdppDD_Kw", "yschJT3LzQY", "reli3mNDgiQ", "aKL6HYK0mGs"]
        video_data = []

        for vid in video_ids:
            url = f"https://www.youtube.com/watch?v={vid}"
            print(f"\n=== INSPECTION VÍDEO: {url} ===")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)

            # Extract title
            v_title = await page.title()

            # Expand description
            desc_text = ""
            try:
                expand_btn = page.locator("#expand, tp-yt-paper-button#expand")
                if await expand_btn.count() > 0:
                    await expand_btn.first.click()
                    await asyncio.sleep(1)
                desc_el = page.locator("#description-inline-expander, #description")
                if await desc_el.count() > 0:
                    desc_text = await desc_el.first.inner_text()
            except Exception as e:
                print("Erro expandindo desc:", e)

            # Comments / Pinned comment
            comments = []
            try:
                # scroll down to load comments
                await page.evaluate("window.scrollBy(0, 600)")
                await asyncio.sleep(2)
                comment_els = page.locator("ytd-comment-thread-renderer #content-text")
                count = await comment_els.count()
                for i in range(min(count, 5)):
                    ctext = await comment_els.nth(i).inner_text()
                    comments.append(ctext)
            except Exception as e:
                print("Erro lendo comentarios:", e)

            # Capture screenshot of player at current moment
            out_img = Path(f"D:/mcp/youtube-hunter-mcp/downloads/screenshots/frame_{vid}.png")
            out_img.parent.mkdir(parents=True, exist_ok=True)
            try:
                # pause and seek
                await page.evaluate("let v = document.querySelector('video'); if (v) { v.currentTime = 15; v.pause(); }")
                await asyncio.sleep(1)
                player = page.locator("#player, .html5-video-player")
                if await player.count() > 0:
                    await player.first.screenshot(path=str(out_img))
                    print(f"Screenshot salvo: {out_img}")
            except Exception as e:
                print("Erro capturando frame:", e)

            video_data.append({
                "video_id": vid,
                "title": v_title,
                "description": desc_text,
                "comments": comments,
                "screenshot": str(out_img) if out_img.exists() else None
            })

        await browser.close()
        
        # Save output
        out_json = Path(r"D:\mcp\youtube-hunter-mcp\downloads\mines\ese_deep_investigation.json")
        out_json.write_text(json.dumps(video_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\nInvestigacao salva em:", out_json)

if __name__ == "__main__":
    asyncio.run(inspect())
