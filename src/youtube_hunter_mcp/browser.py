"""
Playwright-based browser engine for YouTube Hunter MCP.
Provides stealth, anonymous browsing, video harvesting, scrolling, and visual screenshot capture.

ASYNC: uses playwright.async_api so it runs cleanly inside FastMCP's asyncio event loop.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .thumbnails import BASE_DOWNLOAD_DIR
from .utils import (
    extract_video_id,
    normalize_channel_url,
    parse_view_count,
    sanitize_filename,
)

logger = logging.getLogger("youtube_hunter.browser")

SCREENSHOTS_DIR = BASE_DOWNLOAD_DIR / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def _looks_like_views(text: str) -> bool:
    """Return True only for a view count, never for an age such as '8mo ago'."""
    value = (text or "").strip().lower()
    if not value or re.search(r"\b(ago|moments?|hours?|days?|weeks?|months?|years?|streamed)\b", value):
        return False
    return bool(re.search(r"(?:\d[\d.,]*\s*(?:[kmb]|mil|milh(?:o|õ)es|million|billion)\b|\d[\d.,]*\s*(?:views?|visualiza(?:ç|c)(?:õ|o)es))", value, re.I))


# ---------------------------------------------------------------------------
# Sync compatibility shims (used by niche_outliers.py which runs sync Playwright)
# ---------------------------------------------------------------------------

DEFAULT_CHROME_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-gpu",
    "--mute-audio",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-default-apps",
    "--no-first-run",
    "--disable-features=AudioServiceOutOfProcess,IsolateOrigins,site-per-process",
]


def _get_browser_context(pw, session_dir: Optional[str] = None):
    """Legacy sync API: create a plain (non-persistent) browser context.

    Returns (context, using_persistent=False). The caller is responsible for
    closing the returned browser via context.browser.close().
    """
    browser = pw.chromium.launch(
        headless=True,
        args=DEFAULT_CHROME_ARGS,
    )
    context = browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    # Block heavy media streams from degrading host system
    def _block_sync(route):
        if route.request.resource_type in ("image", "media", "font"):
            route.abort()
        else:
            route.continue_()
    context.route("**/*", _block_sync)
    return context, False


def scrape_youtube_search(
    query: str,
    max_results: int = 15,
    capture_screenshot: bool = False,
) -> Dict[str, Any]:
    """Legacy sync wrapper around the async search_youtube engine."""
    coroutine = search_youtube(query, max_results=max_results, capture_screenshot=capture_screenshot)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(coroutine)
        except Exception as e:
            return {"success": False, "error": str(e)}
    from concurrent.futures import ThreadPoolExecutor
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coroutine).result()
    except Exception as e:
        return {"success": False, "error": str(e)}


class YouTubeBrowser:
    """Manages headless browser sessions for YouTube scraping and visual analysis."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=DEFAULT_CHROME_ARGS,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def create_context(self, block_media: bool = True) -> BrowserContext:
        """Create a fresh context configured with en-US locale for consistent metrics."""
        ctx = await self._browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        if block_media:
            async def _abort_heavy(route):
                if route.request.resource_type in ("image", "media", "font"):
                    await route.abort()
                else:
                    await route.continue_()
            await ctx.route("**/*", _abort_heavy)
        return ctx

    async def _dismiss_consent(self, page: Page):
        """Dismiss Google/YouTube consent modal if present."""
        consent_buttons = page.locator(
            'button:has-text("Accept all"), button:has-text("Reject all"), '
            'button:has-text("I agree"), button:has-text("Concordo"), '
            'button:has-text("Aceitar tudo")'
        )
        try:
            if await consent_buttons.count() > 0 and await consent_buttons.first.is_visible(timeout=1500):
                await consent_buttons.first.click()
                await asyncio.sleep(1)
        except Exception:
            pass


async def scrape_channel_videos(
    channel_url_or_handle: str,
    mode: str = "popular",
    max_videos: int = 20,
) -> Dict[str, Any]:
    """
    Deep-scrape channel video tab, sort by popular or latest, and extract top N videos.

    Args:
        channel_url_or_handle: Channel @handle or URL.
        mode: 'popular' (highest views), 'latest' (recent uploads), or 'oldest'.
        max_videos: Target number of videos to harvest (e.g. 20).

    Returns:
        Dict with channel metadata and list of video items.
    """
    base_url = normalize_channel_url(channel_url_or_handle)
    videos_url = f"{base_url}/videos"

    async with YouTubeBrowser(headless=True) as yt:
        context = await yt.create_context(block_media=True)
        page = await context.new_page()

        try:
            await page.goto(videos_url, wait_until="domcontentloaded", timeout=25000)
            await yt._dismiss_consent(page)
            await asyncio.sleep(2.5)

            channel_title = (await page.title()).replace(" - YouTube", "").strip()

            # Handle sorting tabs: 'Popular', 'Latest', 'Oldest'
            target_tab = mode.capitalize()
            if target_tab in ["Popular", "Latest", "Oldest"]:
                try:
                    tab_btn = page.locator(
                        f'button:has-text("{target_tab}"), '
                        f'yt-chip-cloud-chip-renderer:has-text("{target_tab}")'
                    ).first
                    if await tab_btn.is_visible(timeout=3000):
                        await tab_btn.click()
                        await asyncio.sleep(2.5)
                except Exception as e:
                    logger.warning(f"Could not click tab '{target_tab}': {e}")

            # Collect videos by scrolling
            collected_videos = []
            seen_ids = set()
            scroll_attempts = 0
            max_scrolls = max(8, max_videos // 4)

            while len(collected_videos) < max_videos and scroll_attempts < max_scrolls:
                lockups = await page.locator("yt-lockup-view-model, ytd-rich-grid-media, ytd-rich-item-renderer").all()

                for el in lockups:
                    try:
                        # Extract link with video ID
                        link_el = el.locator('a[href*="/watch?v="]').first
                        if await link_el.count() == 0:
                            continue

                        href = (await link_el.get_attribute("href")) or ""
                        vid = extract_video_id(href)
                        if not vid or vid in seen_ids:
                            continue

                        # Extract title
                        title = ""
                        title_el = el.locator('h3 a, a[title], [role="heading"] a').first
                        if await title_el.count() > 0:
                            title = (await title_el.inner_text()).strip() or ((await title_el.get_attribute("title")) or "")
                        if not title:
                            title = (await link_el.inner_text()).strip() or ((await link_el.get_attribute("aria-label")) or "")

                        # Duration
                        duration = ""
                        dur_el = el.locator('span.yt-badge-shape, [aria-label*="minute"], [aria-label*="second"]').first
                        if await dur_el.count() > 0:
                            dur_txt = (await dur_el.inner_text()).strip()
                            if re.match(r"^(\d+:)?\d+:\d+$", dur_txt):
                                duration = dur_txt

                        # Extract metadata spans (views, time ago)
                        spans = await el.locator("span").all_text_contents()
                        clean_spans = [s.strip() for s in spans if s.strip()]

                        raw_views = ""
                        time_ago = ""
                        for s in clean_spans:
                            if _looks_like_views(s):
                                raw_views = s
                            elif re.search(r"(ago|há|atrás|streamed|transmissão)", s, re.I):
                                time_ago = s

                        views_num = parse_view_count(raw_views)

                        seen_ids.add(vid)
                        collected_videos.append({
                            "video_id": vid,
                            "title": title,
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "views_raw": raw_views,
                            "views": views_num,
                            "published_time": time_ago,
                            "duration": duration,
                            "thumbnail_url": f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
                        })

                        if len(collected_videos) >= max_videos:
                            break
                    except Exception:
                        continue

                # Scroll down to load more
                await page.evaluate("window.scrollBy(0, 1500)")
                await asyncio.sleep(1.8)
                scroll_attempts += 1

            return {
                "success": True,
                "channel_title": channel_title,
                "channel_url": base_url,
                "mode": mode,
                "total_harvested": len(collected_videos),
                "videos": collected_videos,
            }

        except Exception as e:
            return {
                "success": False,
                "channel_url": base_url,
                "error": f"Failed to harvest channel videos: {str(e)}",
            }


async def search_youtube(
    query: str,
    max_results: int = 15,
    capture_screenshot: bool = False,
) -> Dict[str, Any]:
    """
    Search YouTube for a topic or niche, extract ranked results, and optionally take a visual screenshot.

    Args:
        query: Search term (e.g. 'faceless youtube automation 2026').
        max_results: Max items to return.
        capture_screenshot: If True, captures a screenshot of the search results page for AI vision inspection.

    Returns:
        Dict with search query, items list, and optional screenshot path.
    """
    encoded_query = query.replace(" ", "+")
    search_url = f"https://www.youtube.com/results?search_query={encoded_query}"

    async with YouTubeBrowser(headless=True) as yt:
        context = await yt.create_context(block_media=not capture_screenshot)
        page = await context.new_page()

        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
            await yt._dismiss_consent(page)
            await asyncio.sleep(2.5)

            screenshot_path = None
            if capture_screenshot:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"search_{sanitize_filename(query, 30)}_{timestamp}.png"
                out_file = SCREENSHOTS_DIR / filename
                await page.screenshot(path=str(out_file), full_page=False)
                screenshot_path = str(out_file.resolve())

            collected = []
            seen_ids = set()
            scroll_attempts = 0

            while len(collected) < max_results and scroll_attempts < 4:
                cards = await page.locator("ytd-video-renderer, yt-lockup-view-model").all()

                for card in cards:
                    try:
                        link_el = card.locator('a[href*="/watch?v="]').first
                        if await link_el.count() == 0:
                            continue

                        href = (await link_el.get_attribute("href")) or ""
                        vid = extract_video_id(href)
                        if not vid or vid in seen_ids:
                            continue

                        # Title
                        title_el = card.locator("#video-title, h3 a").first
                        title = (await title_el.inner_text()).strip() if await title_el.count() > 0 else (await link_el.inner_text()).strip()

                        # Channel Name & URL
                        channel_el = card.locator("#channel-name a, ytd-channel-name a, a[href*='/@'], a[href*='/channel/']").first
                        channel_name = ""
                        channel_url = ""
                        if await channel_el.count() > 0:
                            channel_name = (await channel_el.inner_text()).strip()
                            c_href = (await channel_el.get_attribute("href")) or ""
                            if c_href:
                                channel_url = f"https://www.youtube.com{c_href}" if c_href.startswith("/") else c_href
                                channel_url = channel_url.split("?")[0]

                        # Metadata spans
                        spans = await card.locator("#metadata-line span, span").all_text_contents()
                        clean_spans = [s.strip() for s in spans if s.strip()]

                        raw_views = ""
                        time_ago = ""
                        for s in clean_spans:
                            if _looks_like_views(s):
                                raw_views = s
                            elif re.search(r"(ago|há|atrás)", s, re.I):
                                time_ago = s

                        views_num = parse_view_count(raw_views)

                        seen_ids.add(vid)
                        collected.append({
                            "rank": len(collected) + 1,
                            "video_id": vid,
                            "title": title,
                            "channel": channel_name,
                            "channel_name": channel_name,
                            "channel_url": channel_url,
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "views_raw": raw_views,
                            "views": views_num,
                            "published_time": time_ago,
                            "thumbnail_url": f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
                        })

                        if len(collected) >= max_results:
                            break
                    except Exception:
                        continue

                await page.evaluate("window.scrollBy(0, 1500)")
                await asyncio.sleep(1.5)
                scroll_attempts += 1

            result = {
                "success": True,
                "query": query,
                "total_results": len(collected),
                "items": collected,
                "results": collected,
            }
            if screenshot_path:
                result["screenshot_path"] = screenshot_path
                result["screenshot_uri"] = out_file.resolve().as_uri()

            return result

        except Exception as e:
            return {
                "success": False,
                "query": query,
                "error": f"Search failed: {str(e)}",
            }


async def scrape_video_page(
    url_or_id: str,
    max_comments: int = 25,
) -> Dict[str, Any]:
    """
    Open a video page, inspect description, tags, channel, and extract top comments.
    """
    video_id = extract_video_id(url_or_id)
    if not video_id:
        return {"success": False, "error": f"Invalid video URL or ID: '{url_or_id}'"}

    video_url = f"https://www.youtube.com/watch?v={video_id}"

    async with YouTubeBrowser(headless=True) as yt:
        context = await yt.create_context(block_media=True)
        page = await context.new_page()

        try:
            await page.goto(video_url, wait_until="domcontentloaded", timeout=25000)
            await yt._dismiss_consent(page)
            await asyncio.sleep(2)

            title = (await page.title()).replace(" - YouTube", "").strip()

            # Expand description
            try:
                expand_btn = page.locator("#expand, tp-yt-paper-button#expand, #description-inline-expander").first
                if await expand_btn.is_visible(timeout=2000):
                    await expand_btn.click()
                    await asyncio.sleep(0.5)
            except Exception:
                pass

            # Extract description
            description = ""
            for desc_sel in ["ytd-text-inline-expander", "#description-inner"]:
                try:
                    desc_loc = page.locator(desc_sel).first
                    if await desc_loc.count() > 0:
                        txt = (await desc_loc.inner_text()).strip()
                        if txt:
                            description = txt
                            break
                except Exception:
                    continue

            # Channel info
            channel_el = page.locator("ytd-channel-name a, #owner #channel-name a").first
            channel_name = (await channel_el.inner_text()).strip() if await channel_el.count() > 0 else ""
            channel_url = (await channel_el.get_attribute("href")) if await channel_el.count() > 0 else ""

            # Tags & metadata extraction from ytInitialPlayerResponse and DOM
            meta_data = {}
            try:
                meta_data = await page.evaluate("""() => {
                    let tags = [];
                    let hashtags = [];
                    let views = null;
                    let uploadDate = null;
                    let category = null;

                    try {
                        const jsKw = window.ytInitialPlayerResponse?.videoDetails?.keywords;
                        if (Array.isArray(jsKw) && jsKw.length > 0) {
                            tags = jsKw;
                        }
                    } catch(e) {}

                    if (!tags || tags.length === 0) {
                        try {
                            const metaKw = document.querySelector('meta[name="keywords"]');
                            if (metaKw && metaKw.content) {
                                tags = metaKw.content.split(',').map(s => s.trim()).filter(Boolean);
                            }
                        } catch(e) {}
                    }

                    try {
                        hashtags = Array.from(document.querySelectorAll('a[href*="/hashtag/"]'))
                            .map(a => a.textContent.trim())
                            .filter((v, i, a) => v && a.indexOf(v) === i);
                    } catch(e) {}

                    try {
                        views = window.ytInitialPlayerResponse?.videoDetails?.viewCount || null;
                        uploadDate = window.ytInitialPlayerResponse?.microformat?.playerMicroformatRenderer?.publishDate || null;
                        category = window.ytInitialPlayerResponse?.microformat?.playerMicroformatRenderer?.category || null;
                    } catch(e) {}

                    return { tags, hashtags, views, uploadDate, category };
                }""")
            except Exception:
                meta_data = {}

            # Comments extraction
            comments = []
            if max_comments > 0:
                # Scroll down to load comments section
                await page.evaluate("window.scrollBy(0, 1200)")
                await asyncio.sleep(2.5)

                comment_elements = await page.locator("ytd-comment-thread-renderer").all()
                for ce in comment_elements[:max_comments]:
                    try:
                        author_el = ce.locator("#author-text span").first
                        author = (await author_el.inner_text()).strip() if await author_el.count() > 0 else "Anonymous"

                        text_el = ce.locator("#content-text").first
                        text = (await text_el.inner_text()).strip() if await text_el.count() > 0 else ""

                        likes_el = ce.locator("#vote-count-middle").first
                        likes = (await likes_el.inner_text()).strip() if await likes_el.count() > 0 else "0"

                        time_el = ce.locator(".published-time-text a").first
                        comment_time = (await time_el.inner_text()).strip() if await time_el.count() > 0 else ""

                        if text:
                            comments.append({
                                "author": author,
                                "text": text,
                                "likes": likes,
                                "time": comment_time,
                            })
                    except Exception:
                        continue

            return {
                "success": True,
                "video_id": video_id,
                "url": video_url,
                "title": title,
                "channel_name": channel_name,
                "channel_url": f"https://www.youtube.com{channel_url}" if channel_url.startswith("/") else channel_url,
                "description": description,
                "tags": meta_data.get("tags", []) if isinstance(meta_data, dict) else [],
                "hashtags": meta_data.get("hashtags", []) if isinstance(meta_data, dict) else [],
                "views": meta_data.get("views") if isinstance(meta_data, dict) else None,
                "upload_date": meta_data.get("uploadDate") if isinstance(meta_data, dict) else None,
                "category": meta_data.get("category") if isinstance(meta_data, dict) else None,
                "total_comments_extracted": len(comments),
                "comments": comments,
            }

        except Exception as e:
            return {
                "success": False,
                "video_id": video_id,
                "error": f"Failed to scrape video page: {str(e)}",
            }


async def capture_screenshot(url: str, output_name: Optional[str] = None) -> Dict[str, Any]:
    """Capture a high-res screenshot of any YouTube page for AI visual analysis."""
    async with YouTubeBrowser(headless=True) as yt:
        context = await yt.create_context(block_media=True)
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await yt._dismiss_consent(page)
            await asyncio.sleep(2)

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_name = sanitize_filename(output_name or "yt_page", 40)
            filename = f"{safe_name}_{timestamp}.png"
            dest = SCREENSHOTS_DIR / filename

            await page.screenshot(path=str(dest), full_page=False)

            return {
                "success": True,
                "url": url,
                "local_path": str(dest.resolve()),
                "file_uri": f"file://{dest.resolve()}",
            }
        except Exception as e:
            return {
                "success": False,
                "url": url,
                "error": f"Failed to capture screenshot: {str(e)}",
            }


async def scrape_video_transcript_browser(
    video_url_or_id: str,
    lang_preference: Optional[str] = None,
    include_snippets: bool = True,
    hook_duration_seconds: float = 60.0,
    timeout_ms: int = 30000,
) -> Dict[str, Any]:
    """
    Extract YouTube video transcript directly using Playwright headless browser session.
    Bypasses YouTube IP rate limits (HTTP 429) on python transcript APIs by capturing
    captions and timedtext events in the real browser execution environment.
    """
    video_id = extract_video_id(video_url_or_id)
    if not video_id:
        return {"success": False, "error": f"Invalid video URL or ID: '{video_url_or_id}'"}

    video_url = f"https://www.youtube.com/watch?v={video_id}"

    async with YouTubeBrowser(headless=True) as yt:
        context = await yt.create_context(block_media=True)
        page = await context.new_page()

        timedtext_payloads: List[str] = []

        async def _on_response(response):
            if "timedtext" in response.url:
                try:
                    body = await response.text()
                    if body and body.strip().startswith("{"):
                        timedtext_payloads.append(body)
                except Exception:
                    pass

        page.on("response", lambda r: asyncio.create_task(_on_response(r)))

        try:
            await page.goto(video_url, wait_until="domcontentloaded", timeout=timeout_ms)
            await yt._dismiss_consent(page)
            await asyncio.sleep(2.0)

            # Trigger subtitles via native CC button or keyboard shortcut
            try:
                cc_btn = page.locator(".ytp-subtitles-button").first
                if await cc_btn.count() > 0:
                    await cc_btn.click()
                    await asyncio.sleep(1.5)
            except Exception:
                pass

            if not timedtext_payloads:
                await page.keyboard.press("c")
                await asyncio.sleep(1.5)

            # Wait briefly for timedtext network payload to arrive
            for _ in range(10):
                if timedtext_payloads:
                    break
                await asyncio.sleep(0.4)

            # Also attempt to click transcript button if timedtext wasn't captured yet
            if not timedtext_payloads:
                try:
                    expand_btn = page.locator("#expand, tp-yt-paper-button#expand, #description-inline-expander").first
                    if await expand_btn.count() > 0:
                        await expand_btn.click()
                        await asyncio.sleep(0.5)

                    t_btn = page.locator(
                        'button:has-text("Show transcript"), button:has-text("Mostrar transcrição"), button:has-text("Transcript")'
                    ).first
                    if await t_btn.count() > 0:
                        await t_btn.click()
                        for _ in range(8):
                            if timedtext_payloads:
                                break
                            await asyncio.sleep(0.4)
                except Exception:
                    pass

            if not timedtext_payloads:
                # Check ytInitialPlayerResponse as a fallback in page context
                try:
                    pr = await page.evaluate("() => window.ytInitialPlayerResponse")
                    captions = pr.get("captions", {}) if pr else {}
                    tracks = captions.get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
                    if tracks:
                        track_to_use = tracks[0]
                        if lang_preference:
                            for tr in tracks:
                                lc = tr.get("languageCode", "").lower()
                                if lc == lang_preference.lower() or lc.startswith(lang_preference.lower()):
                                    track_to_use = tr
                                    break
                        base_url = track_to_use.get("baseUrl")
                        if base_url:
                            # Fetch as json3 format
                            fmt_url = base_url if "fmt=json3" in base_url else f"{base_url}&fmt=json3"
                            content_json = await page.evaluate(
                                "(url) => fetch(url).then(r => r.text()).catch(() => '')", fmt_url
                            )
                            if content_json and content_json.strip().startswith("{"):
                                timedtext_payloads.append(content_json)
                except Exception:
                    pass

            if not timedtext_payloads:
                return {
                    "success": False,
                    "video_id": video_id,
                    "error": "No transcript or captions found for this video in browser.",
                }

            import json

            # Parse captured timedtext json3 format
            raw_data = json.loads(timedtext_payloads[-1])
            events = raw_data.get("events", [])

            snippets = []
            full_text_parts = []
            hook_parts = []
            total_duration = 0.0

            for ev in events:
                t_start = ev.get("tStartMs", 0) / 1000.0
                d_dur = ev.get("dDurationMs", 0) / 1000.0
                text = "".join([seg.get("utf8", "") for seg in ev.get("segs", []) if "utf8" in seg]).strip()

                if not text or text == "\n":
                    continue

                clean_text = " ".join(text.split())
                full_text_parts.append(clean_text)

                if t_start <= hook_duration_seconds:
                    hook_parts.append(clean_text)

                if t_start + d_dur > total_duration:
                    total_duration = t_start + d_dur

                if include_snippets:
                    snippets.append({
                        "start": round(t_start, 2),
                        "duration": round(d_dur, 2),
                        "text": clean_text,
                    })

            full_text = " ".join(full_text_parts)
            hook = " ".join(hook_parts)

            return {
                "success": True,
                "video_id": video_id,
                "url": video_url,
                "extractor": "playwright_browser",
                "duration_seconds": round(total_duration, 1),
                "total_words": len(full_text.split()),
                "hook": hook,
                "full_text": full_text,
                "snippets": snippets if include_snippets else [],
            }

        except Exception as e:
            return {
                "success": False,
                "video_id": video_id,
                "error": f"Playwright browser transcript extraction failed: {str(e)}",
            }

