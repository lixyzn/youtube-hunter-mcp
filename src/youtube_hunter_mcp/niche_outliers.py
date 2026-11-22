"""Niche outlier mining pipeline for YouTube Hunter MCP.

Scrapes YouTube search results for a keyword, inspects creators for subscriber
counts (reusing a single browser session), computes outlier factors, and
enriches the strongest candidates with thumbnails, OCR, and transcript hooks.
"""

from __future__ import annotations

import asyncio
import httpx
import logging
import math
import re
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from playwright.sync_api import sync_playwright

from .browser import _get_browser_context, scrape_youtube_search, search_youtube
from .dossier_generator import generate_channel_dossier as generate_dossier
from .mining_report import save_outlier_mine
from .thumbnail_ocr import extract_thumbnail_text as analyze_thumbnail_image
from .thumbnails import download_thumbnail
from .transcript import get_video_transcript_async
from .utils import extract_video_id, parse_relative_age_days, parse_view_count, sanitize_filename

logger = logging.getLogger("youtube_hunter.niche_outliers")


def parse_subscriber_count(sub_str: Any) -> int:
    """Parse subscriber text (e.g. '4.3M subscribers', '164K', '520 mil inscritos') into an integer."""
    if not sub_str:
        return 0
    if isinstance(sub_str, (int, float)):
        return int(sub_str)
    s = str(sub_str).strip().lower()
    s = re.sub(r"\s*(subscribers|subscriber|inscritos|inscrito|subs)\b", "", s).strip()

    b_match = re.search(r"([\d\.,]+)\s*(?:b|bi|bilh[oõ]es|billion)\b", s)
    if b_match:
        try:
            return int(float(b_match.group(1).replace(",", ".")) * 1_000_000_000)
        except ValueError:
            pass

    m_match = re.search(r"([\d\.,]+)\s*(?:m(?!il)|mi\b|milh[oõ]es|million\b)", s)
    if m_match:
        try:
            return int(float(m_match.group(1).replace(",", ".")) * 1_000_000)
        except ValueError:
            pass

    k_match = re.search(r"([\d\.,]+)\s*(?:k|mil|thousand)\b", s)
    if k_match:
        try:
            return int(float(k_match.group(1).replace(",", ".")) * 1_000)
        except ValueError:
            pass

    digits = re.sub(r"[^\d]", "", s)
    if digits:
        try:
            return int(digits)
        except ValueError:
            return 0
    return 0


def _extract_channel_href(page, video_url: str) -> Optional[str]:
    try:
        page.goto(video_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        selectors = [
            'ytd-channel-name a[href*="/@"]',
            'ytd-channel-name a[href*="/channel/"]',
            '#owner ytd-video-owner-renderer a[href*="/@"]',
            '#owner ytd-video-owner-renderer a[href*="/channel/"]',
            'a.yt-simple-endpoint[href*="/@"]',
            'a.yt-simple-endpoint[href*="/channel/"]',
        ]
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if not el:
                    continue
                href = (el.get_attribute("href") or "").split("?")[0]
                if "/@" in href or "/channel/" in href:
                    if href.startswith("http"):
                        return href
                    return "https://www.youtube.com" + href
            except Exception:
                continue

        # Fallback: parse from page content
        try:
            content = page.content() or ""
            m = re.search(
                r'"ownerProfileUrl":"(https://www\.youtube\.com/(?:@|channel/)[^"]+)"',
                content,
            )
            if m:
                return m.group(1).split("?")[0]
        except Exception:
            pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to extract channel href for %s: %s", video_url, exc)
    return None


def _read_subscribers_text(page, channel_url: str) -> str:
    try:
        page.goto(channel_url + "/about", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
        selectors = [
            "yt-formatted-string#subscriber-count",
            "#subscriber-count",
            "yt-content-metadata-view-model span",
            "span.yt-core-attributed-string",
        ]
        for sel in selectors:
            try:
                elements = page.query_selector_all(sel)
            except Exception:
                elements = []
            for el in elements:
                try:
                    text = (el.inner_text() or "").strip()
                except Exception:
                    text = ""
                if text and re.search(r"(subscriber|inscrito)", text, re.IGNORECASE):
                    return text
        # Fallback regex over rendered text
        try:
            body = page.inner_text("body") or ""
            m = re.search(
                r"([\d\.,]+\s*(?:[KMBkmb]|mil|mi|bi)?\s*(?:subscribers|inscritos))",
                body,
                re.IGNORECASE,
            )
            if m:
                return m.group(1)
        except Exception:
            pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to read subscribers for %s: %s", channel_url, exc)
    return ""


HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


async def _fetch_channel_subs_http(client: httpx.AsyncClient, channel_url: str) -> Dict[str, Any]:
    try:
        r = await client.get(channel_url, headers=HTTP_HEADERS, timeout=10.0, follow_redirects=True)
        if r.status_code == 200:
            m_subs = re.search(r'"subscriberCountText":\{[^}]*"simpleText":"([^"]+)"', r.text)
            if not m_subs:
                m_subs = re.search(r'"subscriberCountText":\{[^}]*"content":"([^"]+)"', r.text)
            if not m_subs:
                m_subs = re.search(r'([\d.,]+[KMBkmb]?\s*(?:subscribers|inscritos|subscriber|inscrito))', r.text, re.I)
            subs_text = m_subs.group(1) if m_subs else ""
            subs_count = parse_subscriber_count(subs_text)
            return {
                "success": bool(subs_count > 0 or subs_text),
                "channel_url": channel_url,
                "subscribers_text": subs_text,
                "subscribers": subs_count,
            }
    except Exception as exc:
        logger.debug("HTTP subscriber fetch failed for %s: %s", channel_url, exc)
    return {
        "success": False,
        "channel_url": channel_url,
        "subscribers_text": "",
        "subscribers": 0,
    }


async def inspect_channels_subscribers_fast(
    items_or_urls: List[Any],
    session_dir: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Ultra-fast HTTP-first channel and subscriber resolver.
    Uses connection pooling to resolve subscriber counts in ~1-2s with zero browser overhead.
    Falls back to Playwright only for channels that fail via HTTP.
    """
    results: Dict[str, Dict[str, Any]] = {}
    channel_cache: Dict[str, Dict[str, Any]] = {}
    missing_items: List[Dict[str, str]] = []

    normalized: List[Dict[str, str]] = []
    seen_urls = set()
    for item in items_or_urls:
        if isinstance(item, dict):
            v_url = item.get("url") or item.get("video_url") or ""
            c_url = item.get("channel_url") or ""
        else:
            v_url = str(item)
            c_url = ""
        if v_url and v_url not in seen_urls:
            seen_urls.add(v_url)
            normalized.append({"video_url": v_url, "channel_url": c_url})

    # Fast HTTP resolution for known channel URLs
    unique_channel_urls = {item["channel_url"] for item in normalized if item["channel_url"]}
    if unique_channel_urls:
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
        async with httpx.AsyncClient(limits=limits, timeout=12.0) as client:
            sem = asyncio.Semaphore(4)
            async def _task(curl: str):
                async with sem:
                    res = await _fetch_channel_subs_http(client, curl)
                    channel_cache[curl] = res

            await asyncio.gather(*[_task(curl) for curl in unique_channel_urls])

    # Assign resolved HTTP results
    for item in normalized:
        v_url = item["video_url"]
        c_url = item["channel_url"]
        if c_url and c_url in channel_cache and channel_cache[c_url].get("success"):
            info = dict(channel_cache[c_url])
            info["video_url"] = v_url
            results[v_url] = info
        else:
            missing_items.append(item)

    # Fallback to browser ONLY for items not resolved via HTTP
    if missing_items:
        logger.info("Using browser fallback for %d channels...", len(missing_items))
        try:
            with sync_playwright() as pw:
                context, _ = _get_browser_context(pw, session_dir)
                page = context.new_page()
                try:
                    for m in missing_items:
                        v_url = m["video_url"]
                        c_url = m["channel_url"] or _extract_channel_href(page, v_url)
                        if not c_url:
                            results[v_url] = {
                                "success": False,
                                "video_url": v_url,
                                "channel_url": None,
                                "subscribers_text": "",
                                "subscribers": 0,
                                "error": "channel_not_found",
                            }
                            continue
                        if c_url in channel_cache:
                            info = dict(channel_cache[c_url])
                            info["video_url"] = v_url
                            results[v_url] = info
                            continue
                        subs_text = _read_subscribers_text(page, c_url)
                        subs_count = parse_subscriber_count(subs_text)
                        info = {
                            "success": bool(subs_count > 0 or subs_text),
                            "video_url": v_url,
                            "channel_url": c_url,
                            "subscribers_text": subs_text,
                            "subscribers": subs_count,
                        }
                        channel_cache[c_url] = info
                        results[v_url] = info
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
                    if context.browser is not None:
                        try:
                            context.browser.close()
                        except Exception:
                            pass
        except Exception as exc:
            logger.warning("Browser fallback failed: %s", exc)
            for m in missing_items:
                results.setdefault(
                    m["video_url"],
                    {
                        "success": False,
                        "video_url": m["video_url"],
                        "channel_url": None,
                        "subscribers_text": "",
                        "subscribers": 0,
                        "error": str(exc),
                    },
                )

    return results


def inspect_channels_subscribers_batch(
    video_urls: List[str],
    session_dir: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Legacy sync wrapper (calls the fast HTTP-first inspector)."""
    coroutine = inspect_channels_subscribers_fast(video_urls, session_dir=session_dir)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


def inspect_channel_subscribers(
    video_url: str,
    session_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Backward-compatible single-video subscriber inspector (uses batch logic)."""
    result = inspect_channels_subscribers_batch([video_url], session_dir=session_dir)
    return result.get(
        video_url,
        {
            "success": False,
            "video_url": video_url,
            "channel_url": None,
            "subscribers_text": "",
            "subscribers": 0,
            "error": "inspection_failed",
        },
    )


def _compute_views_per_day(view_count: int, published_time: str) -> Optional[float]:
    age_days = parse_relative_age_days(published_time)
    if age_days is None or age_days <= 0:
        return None
    effective_days = max(age_days, 1.0 / 24.0)
    return round(view_count / effective_days, 2)


async def _enrich_outlier(
    item: Dict[str, Any],
    *,
    keyword: str,
    semaphore: asyncio.Semaphore,
) -> Dict[str, Any]:
    video_url = item.get("url") or ""
    video_id = extract_video_id(video_url)
    title = item.get("title", "")

    enriched = dict(item)
    enriched.setdefault(
        "enrichment",
        {"thumbnail_success": False, "transcript_success": False, "ocr_success": False},
    )

    if not video_id:
        enriched["enrichment"]["error"] = "missing_video_id"
        return enriched

    async with semaphore:
        # Thumbnail
        thumb_path = None
        try:
            thumb_res = await asyncio.to_thread(
                download_thumbnail,
                video_url,
                subfolder=sanitize_filename(f"outliers_{keyword}"),
                custom_name=title,
            )
            if thumb_res.get("success"):
                thumb_path = thumb_res.get("local_path")
                enriched["thumbnail_local_path"] = thumb_path
                enriched["thumbnail_url"] = thumb_res.get("thumbnail_url")
                enriched["thumbnail_cached"] = bool(thumb_res.get("cached"))
                enriched["enrichment"]["thumbnail_success"] = True
            else:
                enriched["enrichment"]["thumbnail_error"] = thumb_res.get(
                    "error", "thumbnail_download_failed"
                )
        except Exception as exc:  # noqa: BLE001
            enriched["enrichment"]["thumbnail_error"] = str(exc)

        # OCR / thumbnail forensics (sync)
        if thumb_path:
            try:
                ocr_res = await asyncio.to_thread(analyze_thumbnail_image, thumb_path, True)
                if ocr_res.get("success"):
                    enriched["thumbnail_ocr"] = ocr_res
                    enriched["enrichment"]["ocr_success"] = True
                else:
                    enriched["enrichment"]["ocr_error"] = ocr_res.get("error", "ocr_failed")
            except Exception as exc:  # noqa: BLE001
                enriched["enrichment"]["ocr_error"] = str(exc)

        # Transcript hook
        try:
            trans_res = await get_video_transcript_async(video_id, include_snippets=False)
            if trans_res.get("success"):
                enriched["transcript"] = {
                    "language": trans_res.get("language"),
                    "is_generated": trans_res.get("is_generated"),
                    "word_count": trans_res.get("total_words"),
                    "hook_first_60s": trans_res.get("hook"),
                    "extractor": trans_res.get("extractor"),
                    "cached": trans_res.get("cached", False),
                }
                enriched["enrichment"]["transcript_success"] = True
            else:
                enriched["enrichment"]["transcript_error"] = trans_res.get(
                    "error", "transcript_unavailable"
                )
        except Exception as exc:  # noqa: BLE001
            enriched["enrichment"]["transcript_error"] = str(exc)

    return enriched


async def find_niche_outliers(
    query: str,
    max_search_results: int = 15,
    min_multiplier: float = 2.0,
    max_channel_subscribers: Optional[int] = 150000,
    enrich_top_n: int = 5,
) -> Dict[str, Any]:
    """Server-facing wrapper mapping yt_find_viral_outliers kwargs onto mine_niche_outliers."""
    result = await mine_niche_outliers(
        keyword=query,
        max_videos=max_search_results,
        enrich_top_n=enrich_top_n,
        subscriber_cap=int(max_channel_subscribers or 150000),
    )

    if not result.get("success"):
        return result

    # Apply the views/subs multiplier filter requested by the caller.
    filtered = [
        v
        for v in result.get("videos", [])
        if (v.get("outlier_factor") or 0) >= float(min_multiplier)
    ]
    result["top_outliers"] = filtered[:10]
    result["videos"] = filtered
    stats = result.setdefault("stats", {})
    stats["qualified_outliers"] = len(filtered)
    stats["min_multiplier"] = float(min_multiplier)
    result["outliers_found"] = len(filtered)
    return result


async def mine_niche_outliers(
    keyword: str,
    session_dir: Optional[str] = None,
    max_videos: int = 20,
    enrich_top_n: int = 5,
    subscriber_cap: int = 100000,
    generate_dossier_md: bool = True,
    enrichment_concurrency: int = 3,
) -> Dict[str, Any]:
    """Search a keyword, score outliers, and enrich the strongest small-channel hits."""
    search_res = await search_youtube(keyword, max_results=max_videos)
    if not search_res.get("success"):
        return {"success": False, "error": search_res.get("error", "Search failed")}

    items = search_res.get("items") or search_res.get("results") or []
    if not items:
        return {
            "success": True,
            "keyword": keyword,
            "message": "No results found",
            "stats": {
                "total_analyzed": 0,
                "qualified_outliers": 0,
                "enriched_videos": 0,
                "subscriber_cap": int(subscriber_cap),
                "median_outlier_factor": 0.0,
                "max_outlier_factor": 0.0,
            },
            "top_outliers": [],
            "videos": [],
        }

    # Fast HTTP-first channel subscriber lookup (zero browser lag, no leaked processes)
    channel_info_map = await inspect_channels_subscribers_fast(items, session_dir=session_dir)

    candidates: List[Dict[str, Any]] = []
    for item in items:
        video_url = item.get("url", "")
        views = parse_view_count(item.get("views", ""))
        channel_info = channel_info_map.get(video_url, {}) or {}
        subs = int(channel_info.get("subscribers") or 0)

        # Only consider channels with known subscribers under cap (and >0 for meaningful ratio)
        if 0 < subs <= int(subscriber_cap) and views > 0:
            outlier_factor = views / subs
            # A light "surprise" score: factor scaled by magnitude, damped for tiny samples
            magnitude_bonus = math.log10(max(views, 10)) / 6.0
            score = outlier_factor * (0.7 + 0.3 * max(0.0, min(magnitude_bonus, 1.5)))
            row = {
                "video_id": extract_video_id(video_url),
                "title": item.get("title", ""),
                "url": video_url,
                "views_text": item.get("views", ""),
                "views": views,
                "published_time": item.get("published_time", ""),
                "duration": item.get("duration", ""),
                "channel_name": item.get("channel_name", ""),
                "channel_url": channel_info.get("channel_url"),
                "subscribers": subs,
                "subscribers_text": channel_info.get("subscribers_text", ""),
                "outlier_factor": round(outlier_factor, 2),
                "outlier_score": round(score, 2),
            }
            vpd = _compute_views_per_day(views, item.get("published_time", ""))
            if vpd is not None:
                row["views_per_day_est"] = vpd
            candidates.append(row)

    candidates.sort(
        key=lambda x: (x.get("outlier_score", 0), x.get("outlier_factor", 0), x.get("views", 0)),
        reverse=True,
    )

    enrich_top_n = max(0, min(int(enrich_top_n), len(candidates)))
    enrichment_concurrency = max(1, min(int(enrichment_concurrency), 6))
    semaphore = asyncio.Semaphore(enrichment_concurrency)

    if enrich_top_n > 0:
        enriched_subset = await asyncio.gather(
            *[
                _enrich_outlier(c, keyword=keyword, semaphore=semaphore)
                for c in candidates[:enrich_top_n]
            ]
        )
        candidates = list(enriched_subset) + candidates[enrich_top_n:]

    factors = [c.get("outlier_factor", 0.0) for c in candidates if c.get("outlier_factor") is not None]
    median_factor = float(statistics.median(factors)) if factors else 0.0

    report = {
        "success": True,
        "keyword": keyword,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "total_analyzed": len(items),
            "qualified_outliers": len(candidates),
            "enriched_videos": enrich_top_n,
            "subscriber_cap": int(subscriber_cap),
            "median_outlier_factor": round(median_factor, 2) if median_factor else 0.0,
            "max_outlier_factor": round(max(factors), 2) if factors else 0.0,
        },
        "top_outliers": candidates[:10],
        "videos": candidates,
    }

    if generate_dossier_md:
        try:
            report["dossier_markdown"] = generate_dossier(report, kind="niche_outliers")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to generate outlier dossier: %s", exc)
            report.setdefault("warnings", []).append(f"dossier_generation_failed: {exc}")

    try:
        save_outlier_mine(report)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to save outlier mine run: %s", exc)
        report.setdefault("warnings", []).append(f"save_outlier_mine_failed: {exc}")

    return report
