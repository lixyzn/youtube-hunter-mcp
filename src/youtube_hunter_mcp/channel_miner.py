"""Deep channel mining pipeline for YouTube Hunter MCP.

Fetches channel overview + videos, enriches top videos with thumbnails and
transcript hooks, generates structured outputs for downstream LLM analysis.
"""

from __future__ import annotations

import asyncio
import logging
import re
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .browser import scrape_channel_videos, search_youtube
from .dossier_generator import generate_channel_dossier as generate_dossier
from .mining_report import save_channel_mine
from .thumbnails import download_thumbnail
from .transcript import get_video_transcript_async
from .utils import extract_video_id, parse_relative_age_days, parse_view_count, sanitize_filename

logger = logging.getLogger("youtube_hunter.channel_miner")


def classify_outlier(view_count: int, median_views: float) -> str:
    """Classify a video relative to channel median view performance."""
    if median_views <= 0:
        return "normal"

    factor = view_count / median_views
    if factor >= 5.0:
        return "mega_outlier"
    if factor >= 2.0:
        return "strong_outlier"
    if factor >= 1.3:
        return "outlier"
    if factor <= 0.3:
        return "underperformer"
    return "normal"


def _compute_views_per_day(view_count: int, published_time: str) -> Optional[float]:
    age_days = parse_relative_age_days(published_time)
    if age_days is None or age_days <= 0:
        return None
    # Avoid extreme inflation for very recent uploads
    effective_days = max(age_days, 1.0 / 24.0)
    return round(view_count / effective_days, 2)


async def _enrich_video(
    video: Dict[str, Any],
    *,
    channel_name: str,
    median_views: float,
    semaphore: asyncio.Semaphore,
    download_thumbnails: bool = True,
    fetch_transcripts: bool = True,
    lang_preference: Optional[str] = None,
) -> Dict[str, Any]:
    video_url = video.get("url") or video.get("video_url") or ""
    video_id = extract_video_id(video_url)
    title = video.get("title", "")
    view_count = parse_view_count(video.get("views", ""))

    item_data: Dict[str, Any] = {
        "video_id": video_id,
        "title": title,
        "url": video_url,
        "views_text": video.get("views", ""),
        "views_raw": video.get("views", ""),
        "views": view_count,
        "published_time": video.get("published_time", ""),
        "duration": video.get("duration", ""),
        "enrichment": {
            "thumbnail_success": False,
            "transcript_success": False,
        },
    }

    if median_views > 0:
        factor = view_count / median_views
        item_data["outlier_factor"] = round(factor, 2)
        item_data["outlier_class"] = classify_outlier(view_count, median_views)
        item_data["performance_tag"] = classify_outlier(view_count, median_views)

    vpd = _compute_views_per_day(view_count, video.get("published_time", ""))
    if vpd is not None:
        item_data["views_per_day_est"] = vpd

    if not video_id:
        item_data["enrichment"]["error"] = "missing_video_id"
        return item_data

    async with semaphore:
        # Thumbnail download is sync/blocking; run in thread to avoid blocking event loop.
        if download_thumbnails:
            try:
                thumb_res = await asyncio.to_thread(
                    download_thumbnail,
                    video_url,
                    subfolder=sanitize_filename(channel_name),
                    custom_name=title,
                )
                if thumb_res.get("success"):
                    item_data["thumbnail_local_path"] = thumb_res.get("local_path")
                    item_data["thumbnail_url"] = thumb_res.get("thumbnail_url")
                    item_data["thumbnail_cached"] = bool(thumb_res.get("cached"))
                    item_data["enrichment"]["thumbnail_success"] = True
                else:
                    item_data["enrichment"]["thumbnail_error"] = thumb_res.get(
                        "error", "thumbnail_download_failed"
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Thumbnail enrichment failed for %s: %s", video_id, exc)
                item_data["enrichment"]["thumbnail_error"] = str(exc)

        # Transcript extraction (async; internally cached/multi-source)
        if fetch_transcripts:
            try:
                trans_res = await get_video_transcript_async(
                    video_id, include_snippets=False, lang_preference=lang_preference
                )
                if trans_res.get("success"):
                    item_data["transcript"] = {
                        "language": trans_res.get("language"),
                        "is_generated": trans_res.get("is_generated"),
                        "word_count": trans_res.get("total_words"),
                        "duration_seconds": trans_res.get("duration_seconds"),
                        "hook_first_60s": trans_res.get("hook"),
                        "full_script": trans_res.get("full_text"),
                        "extractor": trans_res.get("extractor"),
                        "cached": trans_res.get("cached", False),
                    }
                    item_data["enrichment"]["transcript_success"] = True
                else:
                    item_data["enrichment"]["transcript_error"] = trans_res.get(
                        "error", "transcript_unavailable"
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Transcript enrichment failed for %s: %s", video_id, exc)
                item_data["enrichment"]["transcript_error"] = str(exc)

    return item_data


async def get_channel_overview(
    channel_url_or_handle: str,
    session_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch lightweight channel metadata (name, url, subs, totals, description)."""
    from .browser import normalize_channel_url
    base_url = normalize_channel_url(channel_url_or_handle)

    # 1. Ultra-fast HTTP attempt (0 browser overhead, ~1s execution)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        import httpx
        from bs4 import BeautifulSoup
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            r = await client.get(base_url, headers=headers)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                channel_name = soup.title.string.replace(" - YouTube", "").strip() if soup.title else ""

                m_subs = re.search(r'"subscriberCountText":\{[^}]*"simpleText":"([^"]+)"', r.text)
                if not m_subs:
                    m_subs = re.search(r'"subscriberCountText":\{[^}]*"content":"([^"]+)"', r.text)
                if not m_subs:
                    m_subs = re.search(r'([\d.,]+[KMBkmb]?\s*(?:subscribers|inscritos|subscriber|inscrito))', r.text, re.I)
                subscribers_text = m_subs.group(1) if m_subs else ""

                m_vids = re.search(r'"videosCountText":\{[^}]*"simpleText":"([^"]+)"', r.text)
                if not m_vids:
                    m_vids = re.search(r'([\d.,]+[KMBkmb]?\s*(?:videos|vídeos|video|vídeo))', r.text, re.I)
                total_videos_text = m_vids.group(1) if m_vids else ""

                m_desc = re.search(r'"description":"([^"]+)"', r.text)
                description_snippet = m_desc.group(1) if m_desc else ""

                if channel_name:
                    return {
                        "success": True,
                        "channel_name": channel_name,
                        "channel_url": base_url,
                        "subscribers_text": subscribers_text,
                        "total_videos_text": total_videos_text,
                        "description_snippet": description_snippet,
                    }
    except Exception as exc:
        logger.debug("HTTP channel overview failed for %s: %s", base_url, exc)

    # 2. Browser fallback (only 1 browser session with media blocked)
    from .browser import YouTubeBrowser
    async with YouTubeBrowser(headless=True) as yt:
        context = await yt.create_context(block_media=True)
        page = await context.new_page()
        try:
            await page.goto(base_url, wait_until="domcontentloaded", timeout=25000)
            await yt._dismiss_consent(page)
            channel_name = (await page.title()).replace(" - YouTube", "").strip()

            subscribers_text = ""
            total_videos_text = ""
            description_snippet = ""

            spans = await page.locator("yt-formatted-string, span, yt-spec-truncated-plain-text").all_text_contents()
            for s in spans:
                text = (s or "").strip()
                if not text:
                    continue
                low = text.lower()
                if not subscribers_text and ("subscriber" in low or "inscrito" in low or re.match(r"^[\d.,]+[kmb]?$", low)):
                    subscribers_text = text
                elif not total_videos_text and ("video" in low or "vídeo" in low):
                    total_videos_text = text

            try:
                desc_el = page.locator("yt-attributed-string.description, #description").first
                if await desc_el.count() > 0:
                    description_snippet = (await desc_el.inner_text()).strip()
            except Exception:
                pass

            return {
                "success": True,
                "channel_name": channel_name or "Unknown Channel",
                "channel_url": base_url,
                "subscribers_text": subscribers_text,
                "total_videos_text": total_videos_text,
                "description_snippet": description_snippet,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to fetch channel overview: {e}"}
        finally:
            try:
                await page.close()
                await context.close()
            except Exception:
                pass


async def get_channel_videos(
    channel_url_or_handle: str,
    max_videos: int = 20,
    session_dir: Optional[str] = None,
    mode: str = "popular",
) -> Dict[str, Any]:
    """Fetch channel videos (popular or latest sort) via the new async browser engine."""
    result = await scrape_channel_videos(channel_url_or_handle, mode=mode, max_videos=max_videos)
    if not result.get("success"):
        return result
    return {
        "success": True,
        "videos": result.get("videos", []),
    }


async def deep_mine_channel(
    channel_url_or_handle: str,
    session_dir: Optional[str] = None,
    max_videos: int = 30,
    enrich_top_n: int = 10,
    generate_dossier_md: bool = True,
    enrichment_concurrency: int = 4,
    mode: str = "popular",
    download_thumbnails: bool = True,
    fetch_transcripts: bool = True,
    lang_preference: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform a full deep scan of a channel: videos, stats, thumbnails and scripts."""
    channel_url = channel_url_or_handle
    overview = await get_channel_overview(channel_url, session_dir=session_dir)
    if not overview.get("success"):
        return {"success": False, "error": overview.get("error", "Failed to fetch channel overview")}

    channel_name = overview.get("channel_name", "Unknown Channel")

    videos_result = await get_channel_videos(channel_url, max_videos=max_videos, session_dir=session_dir, mode=mode)
    if not videos_result.get("success"):
        return {"success": False, "error": videos_result.get("error", "Failed to fetch channel videos")}

    videos = videos_result.get("videos", [])
    total_found = len(videos)

    # Outlier baseline from fetched video view counts
    views_list = [parse_view_count(v.get("views", "")) for v in videos]
    views_list = [v for v in views_list if v > 0]
    median_views = float(statistics.median(views_list)) if views_list else 0.0
    mean_views = float(statistics.mean(views_list)) if views_list else 0.0

    enrich_top_n = max(0, min(int(enrich_top_n), len(videos)))
    enrichment_concurrency = max(1, min(int(enrichment_concurrency), 3))
    targets = videos[:enrich_top_n]
    remaining = videos[enrich_top_n:]

    semaphore = asyncio.Semaphore(enrichment_concurrency)
    enriched_results = await asyncio.gather(
        *[
            _enrich_video(
                v,
                channel_name=channel_name,
                median_views=median_views,
                semaphore=semaphore,
                download_thumbnails=download_thumbnails,
                fetch_transcripts=fetch_transcripts,
                lang_preference=lang_preference,
            )
            for v in targets
        ]
    )
    enriched_videos: List[Dict[str, Any]] = list(enriched_results)

    # Append non-enriched videos with lightweight metadata/classification
    for video in remaining:
        video_id = extract_video_id(video.get("url") or "")
        view_count = parse_view_count(video.get("views", ""))
        item_data: Dict[str, Any] = {
            "video_id": video_id,
            "title": video.get("title", ""),
            "url": video.get("url", ""),
            "views_text": video.get("views", ""),
            "views_raw": video.get("views", ""),
            "views": view_count,
            "published_time": video.get("published_time", ""),
            "duration": video.get("duration", ""),
        }
        if median_views > 0:
            item_data["outlier_factor"] = round(view_count / median_views, 2)
            item_data["outlier_class"] = classify_outlier(view_count, median_views)
            item_data["performance_tag"] = classify_outlier(view_count, median_views)
        vpd = _compute_views_per_day(view_count, video.get("published_time", ""))
        if vpd is not None:
            item_data["views_per_day_est"] = vpd
        enriched_videos.append(item_data)

    # Sort by views descending for reporting convenience
    enriched_videos.sort(key=lambda x: x.get("views", 0), reverse=True)

    top_outliers = [
        v
        for v in enriched_videos
        if v.get("outlier_class") in ("mega_outlier", "strong_outlier", "outlier")
    ][:10]

    hooks_found = sum(1 for v in enriched_videos if (v.get("transcript") or {}).get("hook_first_60s"))
    thumb_success = sum(1 for v in enriched_videos if v.get("enrichment", {}).get("thumbnail_success"))
    transcript_success = sum(
        1 for v in enriched_videos if v.get("enrichment", {}).get("transcript_success")
    )

    top_hooks = [
        {
            "title": v.get("title"),
            "url": v.get("url"),
            "views": v.get("views"),
            "outlier_class": v.get("outlier_class"),
            "performance_tag": v.get("performance_tag"),
            "hook": (v.get("transcript") or {}).get("hook_first_60s"),
        }
        for v in enriched_videos
        if (v.get("transcript") or {}).get("hook_first_60s")
    ][:10]

    report = {
        "success": True,
        "channel_name": channel_name,
        "channel_title": channel_name,
        "channel_url": overview.get("channel_url", channel_url),
        "mining_mode": mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overview": {
            "subscribers_text": overview.get("subscribers_text"),
            "total_videos_text": overview.get("total_videos_text"),
            "description_snippet": (overview.get("description_snippet") or "")[:500],
        },
        "stats": {
            "total_videos_found": total_found,
            "enriched_videos": enrich_top_n,
            "median_views": int(median_views) if median_views else 0,
            "mean_views": int(mean_views) if mean_views else 0,
            "average_views": int(mean_views) if mean_views else 0,
            "max_views": max(views_list) if views_list else 0,
            "min_views": min(views_list) if views_list else 0,
            "top_outliers_count": len(top_outliers),
            "outliers_found": len(top_outliers),
            "hooks_extracted": hooks_found,
            "thumbnails_downloaded": thumb_success,
            "transcripts_extracted": transcript_success,
        },
        "statistics": {
            "median_views": int(median_views) if median_views else 0,
            "mean_views": int(mean_views) if mean_views else 0,
            "average_views": int(mean_views) if mean_views else 0,
            "max_views": max(views_list) if views_list else 0,
            "min_views": min(views_list) if views_list else 0,
            "outliers_found": len(top_outliers),
        },
        "top_outliers": top_outliers,
        "top_hooks": top_hooks,
        "videos": enriched_videos,
    }

    if generate_dossier_md:
        try:
            report["dossier_markdown"] = generate_dossier(report, kind="channel_mine")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to generate channel dossier: %s", exc)
            report.setdefault("warnings", []).append(f"dossier_generation_failed: {exc}")

    # Persist the run so it can be compared and reused later.
    try:
        save_channel_mine(report)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to save channel mine run: %s", exc)
        report.setdefault("warnings", []).append(f"save_channel_mine_failed: {exc}")

    return report
