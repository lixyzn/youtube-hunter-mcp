#!/usr/bin/env python3
"""
YouTube Hunter MCP Server
Empowers AI agents with eyes, deep scraping, niche mining, transcript extraction,
OCR on thumbnails, narrative pacing analysis, and automated intelligence dossiers.

Transport: stdio (FastMCP)
Location: /run/media/fernando/589488AB94888CE6/youtube-hunter-mcp
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from .browser import (
    capture_screenshot,
    scrape_video_page,
    scrape_video_transcript_browser,
    search_youtube,
)
from .channel_miner import deep_mine_channel
from .dossier_generator import generate_channel_dossier
from .mining_report import generate_mining_dashboard, get_mining_catalog
from .niche_outliers import find_niche_outliers
from .pacing_analyzer import analyze_narrative_pacing
from .packaging_analyzer import dissect_packaging
from .thumbnail_grid import build_thumbnail_grid
from .thumbnail_ocr import extract_thumbnail_text
from .thumbnails import batch_download_thumbnails, download_thumbnail
from .transcript import (
    get_video_transcript,
    get_video_transcript_async,
    parse_raw_transcript_text,
)
from .utils import extract_video_id

# Configure logging to stderr so stdio JSON-RPC isn't polluted
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("youtube-hunter-mcp")

mcp = FastMCP("youtube-hunter-mcp")


@mcp.tool()
async def yt_deep_mine_channel(
    channel_url_or_handle: str,
    mode: str = "popular",
    max_videos: int = 20,
    download_thumbnails: bool = True,
    fetch_transcripts: bool = True,
    generate_dossier: bool = True,
    lang_preference: Optional[str] = None,
) -> str:
    """
    Perform deep end-to-end intelligence mining on any YouTube channel.

    What it does:
    1. Harvests video cards from the channel (sorted by 'popular' for viral winners or 'latest' for recent output).
    2. Calculates channel average views and assigns Outlier Scores (e.g. 5.4x channel baseline).
    3. Downloads highest resolution thumbnails to disk for AI visual analysis.
    4. Extracts complete scripts and opening hooks in ANY language without restriction.
    5. Optionally generates a publication-ready Markdown Dossier (Obsidian compatible) with embedded photos and formulas.

    Args:
        channel_url_or_handle: Channel @handle (e.g. '@hubermanlab') or URL (e.g. 'https://www.youtube.com/@AlexHormozi').
        mode: 'popular' (top viewed videos) or 'latest' (most recent). Default is 'popular'.
        max_videos: Number of videos to analyze (default 20).
        download_thumbnails: If True, downloads all thumbnails locally and returns file paths (default True).
        fetch_transcripts: If True, extracts full transcripts and hooks for top videos (default True).
        generate_dossier: If True, automatically creates a Markdown research dossier file in dossiers/ (default True).
        lang_preference: Optional language code (e.g. 'en', 'pt'). If omitted, extracts whatever language is available.

    Returns:
        JSON string containing channel metrics, outlier analysis, script hooks, local thumbnail paths, and dossier path.
    """
    try:
        data = await deep_mine_channel(
            channel_url_or_handle=channel_url_or_handle,
            mode=mode,
            max_videos=max_videos,
            download_thumbnails=download_thumbnails,
            fetch_transcripts=fetch_transcripts,
            lang_preference=lang_preference,
        )

        if generate_dossier and data.get("success"):
            dossier_res = generate_channel_dossier(data)
            data["dossier"] = dossier_res

        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error in yt_deep_mine_channel")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def yt_find_viral_outliers(
    query: str,
    max_search_results: int = 15,
    min_multiplier: float = 2.0,
    max_channel_subscribers: Optional[int] = 150000,
    enrich_top_n: int = 5,
) -> str:
    """
    Find small channels that went viral on a specific topic or niche (The '1of10' Growth Secret).

    Identifies videos where the view count significantly exceeds the channel subscriber base (e.g. 10x or 50x subscribers),
    which proves the topic, title, and thumbnail are independently viral without brand authority.
    Automatically downloads the winning thumbnails, runs OCR to read the cover text, and extracts the opening hooks.

    Args:
        query: Search term or niche topic (e.g. 'ai automation agency', 'faceless channel guide').
        max_search_results: Number of search results to inspect (default 15).
        min_multiplier: Minimum views-to-subscribers ratio (default 2.0x).
        max_channel_subscribers: Cap on channel size to exclude megastars (default 150,000 subs).
        enrich_top_n: Number of top winners to enrich with thumbnails, OCR, and script hooks (default 5).

    Returns:
        JSON string with verified viral topics, multipliers, thumbnail OCR text, and script hooks.
    """
    try:
        data = await find_niche_outliers(
            query=query,
            max_search_results=max_search_results,
            min_multiplier=min_multiplier,
            max_channel_subscribers=max_channel_subscribers,
            enrich_top_n=enrich_top_n,
        )
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error in yt_find_viral_outliers")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def yt_extract_thumbnail_text(
    image_path_or_video_url: str,
) -> str:
    """
    Extract text written directly on a thumbnail image using high-speed OCR.
    Detects typography styles (ALL CAPS, numbers, trigger phrases) to help analyze what drives clicks.

    Args:
        image_path_or_video_url: Local image path, video URL, or 11-char video ID.

    Returns:
        JSON string containing detected text lines, confidence scores, and typography features.
    """
    try:
        data = extract_thumbnail_text(image_path_or_video_url)
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error in yt_extract_thumbnail_text")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def yt_analyze_pacing(
    video_url_or_id: str,
    lang_preference: Optional[str] = None,
    pasted_transcript: Optional[str] = None,
) -> str:
    """
    Analyze narrative rhythm, Words Per Minute (WPM), question density, and engagement loops for any video.
    Helps determine whether speech pacing is optimized for high retention.

    Can analyze via video URL/ID (with automatic Playwright fallback) OR directly from pasted script text.

    Args:
        video_url_or_id: YouTube video URL or ID (can be 'custom' if pasted_transcript is provided).
        lang_preference: Optional language code preference.
        pasted_transcript: Optional manually provided script/transcript text to bypass all YouTube requests.

    Returns:
        JSON string with WPM, hook tempo, curiosity loop frequency per minute, and pacing recommendations.
    """
    try:
        if pasted_transcript and pasted_transcript.strip():
            trans_res = parse_raw_transcript_text(pasted_transcript, video_id=video_url_or_id)
        else:
            trans_res = await get_video_transcript_async(
                video_url_or_id,
                lang_preference=lang_preference,
                include_snippets=False,
            )

        if not trans_res.get("success"):
            return json.dumps(trans_res, ensure_ascii=False)

        pacing_data = analyze_narrative_pacing(
            transcript_text=trans_res.get("full_text", ""),
            duration_seconds=trans_res.get("duration_seconds", 300),
            hook_text=trans_res.get("hook"),
        )
        pacing_data["video_id"] = trans_res.get("video_id")
        pacing_data["language"] = trans_res.get("language")

        return json.dumps(pacing_data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error in yt_analyze_pacing")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def yt_search(
    query: str,
    max_results: int = 15,
    capture_screenshot: bool = False,
) -> str:
    """
    Search YouTube for a topic, niche, or competitor keywords.

    Extracts ranked search cards (title, video ID, channel name, views, age, thumbnail URL).
    Can also capture a real screenshot of the search results page so the agent can visually inspect thumbnail competition.

    Args:
        query: Search term (e.g. 'faceless youtube automation tutorial').
        max_results: Number of results to return (default 15).
        capture_screenshot: If True, saves a PNG screenshot of the search page to disk and returns local path.

    Returns:
        JSON string with list of ranked search results and optional screenshot path.
    """
    try:
        data = await search_youtube(
            query=query,
            max_results=max_results,
            capture_screenshot=capture_screenshot,
        )
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error in yt_search")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def yt_get_transcript(
    url_or_id: str,
    lang_preference: Optional[str] = None,
    include_timestamps: bool = False,
    force_browser: bool = False,
) -> str:
    """
    Extract video transcript and opening hook in ANY language without restriction.

    Supports English, Portuguese, Spanish, German, Japanese, etc.
    Automatically handles manual subtitles and auto-generated captions.
    Multi-stage engine: cache -> youtube-transcript-api -> Innertube transcript
    panel (survives the HTTP 429 block on /api/timedtext) -> yt-dlp -> Playwright
    DOM/network -> optional external provider.

    Args:
        url_or_id: YouTube video URL or 11-character video ID.
        lang_preference: Optional language code (e.g. 'en', 'pt'). If unavailable, falls back to available track.
            Note: the Innertube route (the one that works on blocked IPs) serves the
            player's default track; when it differs from the request, a warning is
            returned alongside the detected language.
        include_timestamps: If True, returns detailed timestamped segments [start, duration, text].
        force_browser: If True, skips API and uses headless Playwright browser to extract directly from video page.

    Returns:
        JSON string containing the hook (first 60s), full clean script, language metadata, extractor used,
        the source_chain (which layers were tried) and timestamps.
    """
    try:
        data = await get_video_transcript_async(
            url_or_id=url_or_id,
            lang_preference=lang_preference,
            include_snippets=include_timestamps,
            force_browser=force_browser,
        )
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error in yt_get_transcript")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def yt_parse_custom_transcript(
    transcript_text: str,
    video_id: str = "custom_video",
    hook_duration_seconds: float = 60.0,
    words_per_minute: float = 140.0,
) -> str:
    """
    Ingest, clean, and analyze a manually pasted transcript or script.

    Allows AI agents to process any raw script copied from YouTube or external sources
    without making network requests, computing estimated duration, word counts, and opening hooks.

    Args:
        transcript_text: The full raw text of the video transcript/subtitles.
        video_id: Optional reference video ID or label.
        hook_duration_seconds: Duration in seconds to extract as opening hook (default 60s).
        words_per_minute: Average speaking tempo (default 140 WPM).

    Returns:
        JSON string containing cleaned script, extracted hook, word count, and estimated duration.
    """
    try:
        data = parse_raw_transcript_text(
            raw_text=transcript_text,
            video_id=video_id,
            hook_duration_seconds=hook_duration_seconds,
            avg_words_per_minute=words_per_minute,
        )
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error in yt_parse_custom_transcript")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def yt_inspect_video(
    url_or_id: str,
    download_thumbnail_file: bool = True,
    max_comments: int = 25,
) -> str:
    """
    Deeply inspect a single video: metadata, description, tags, high-res thumbnail, and audience comments.

    Great for analyzing why a video performed well, validating ideas, and discovering audience questions/pains.

    Args:
        url_or_id: YouTube video URL or ID.
        download_thumbnail_file: If True, saves maximum resolution thumbnail to disk for vision analysis.
        max_comments: Number of top audience comments to extract (default 25).

    Returns:
        JSON string with title, description, channel, comments list, and local thumbnail path.
    """
    try:
        page_data = await scrape_video_page(url_or_id=url_or_id, max_comments=max_comments)
        vid = extract_video_id(url_or_id)

        if download_thumbnail_file and vid:
            thumb_res = download_thumbnail(vid, subfolder="inspect", custom_name=page_data.get("title", ""))
            if thumb_res.get("success"):
                page_data["thumbnail"] = thumb_res

        return json.dumps(page_data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error in yt_inspect_video")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def yt_download_thumbnails(
    video_urls_or_ids: List[str],
    folder_name: str = "batch",
) -> str:
    """
    Batch download maximum resolution thumbnails (maxresdefault/hq720/hqdefault) for a list of videos.

    Args:
        video_urls_or_ids: List of video URLs or IDs.
        folder_name: Subfolder name inside downloads/thumbnails/ to organize the files.

    Returns:
        JSON string with local file paths, dimensions (width x height), and file URIs for vision models.
    """
    try:
        items = [{"url": u} for u in video_urls_or_ids]
        results = batch_download_thumbnails(items=items, subfolder=folder_name)
        return json.dumps({"success": True, "count": len(results), "thumbnails": results}, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error in yt_download_thumbnails")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def yt_capture_screenshot(
    url: str,
    output_name: Optional[str] = None,
) -> str:
    """
    Capture a high-resolution 1080p screenshot of any YouTube page (channel, home, video, search).
    Gives the AI agent literal eyes to visually inspect layouts, banners, or design elements.

    Args:
        url: Any valid YouTube URL.
        output_name: Optional label for the screenshot file.

    Returns:
        JSON string with local file path and file URI.
    """
    try:
        data = await capture_screenshot(url=url, output_name=output_name)
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error in yt_capture_screenshot")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
async def yt_generate_mining_report(output_name: Optional[str] = None) -> str:
    """
    Gera um painel/relatório HTML bonito com todos os canais e nichos já minerados.
    Reúne dados salvos automaticamente (downloads/mines/), mostra links dos canais/vídeos,
    prints/thumbnails, métricas e tabelas para análise e comparação.
    Permite ordenar vídeos por maiores/menores views e por outlier/multiplicador no próprio HTML.
    Retorna o caminho local (report_path/report_uri) para abrir no navegador.
    """
    try:
        result = generate_mining_dashboard(output_name=output_name)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.exception("Error in yt_generate_mining_report")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def yt_build_thumbnail_grid(
    video_urls_or_ids: Optional[List[str]] = None,
    subfolder_or_query: Optional[str] = None,
    grid_title: Optional[str] = None,
    max_items: int = 6,
    columns: int = 3,
    output_name: Optional[str] = None,
) -> str:
    """
    Build a visual moodboard / comparison grid stitching winning thumbnails in high-res.
    Overlays rank badges (#1, #2), metrics (views/multipliers), and title captions.
    Perfect for multimodal AI vision inspection (analyzing cover trends in a single glance)
    or for quick human visual comparison without opening multiple image files.

    Args:
        video_urls_or_ids: List of video URLs or IDs to fetch and stitch.
        subfolder_or_query: Optional existing folder name or niche query in downloads/thumbnails/.
        grid_title: Header title to render at the top of the grid.
        max_items: Maximum thumbnails to include in the grid (default 6).
        columns: Number of grid columns (default 3).
        output_name: Optional custom output file name.

    Returns:
        JSON string with local file path, URI, dimensions, and items metadata.
    """
    try:
        data = build_thumbnail_grid(
            items_or_urls=video_urls_or_ids,
            subfolder_or_query=subfolder_or_query,
            grid_title=grid_title,
            max_items=max_items,
            columns=columns,
            output_name=output_name,
        )
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error in yt_build_thumbnail_grid")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def yt_get_mining_catalog() -> str:
    """
    Query the central intelligence catalog and executive summary of all data mined so far.
    Eliminates messy raw JSON by delivering a structured, high-level summary of:
    - All channels investigated (with median views and top outliers)
    - All niche outlier searches performed (with peak multipliers)
    - Total thumbnails, cached scripts, visual moodboard grids, and dossiers on disk
    - Direct links to the latest interactive HTML dashboard

    Returns:
        JSON string containing the structured catalog and a pre-formatted 'markdown_overview' table.
    """
    try:
        data = get_mining_catalog()
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error in yt_get_mining_catalog")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def yt_dissect_packaging(
    title: str,
    thumbnail_path_or_url: Optional[str] = None,
    thumbnail_text: Optional[str] = None,
) -> str:
    """
    Dissect YouTube packaging synergy between the video Title and Thumbnail cover.
    Tests for the #1 mistake in YouTube packaging: redundancy (repeating title words on cover).
    Analyzes mobile cutoff risk (> 50 chars), curiosity gaps, emotional power words,
    and returns a definitive verdict (S-Tier, Solid, or Sub-Optimal) with actionable CTR tips.

    Args:
        title: Video title to evaluate.
        thumbnail_path_or_url: Optional local thumbnail image path, remote URL, or video ID.
        thumbnail_text: Optional manually provided thumbnail OCR text.

    Returns:
        JSON string with redundancy percentage, word overlap, psychological triggers, and recommendations.
    """
    try:
        data = dissect_packaging(
            title=title,
            thumbnail_path_or_url=thumbnail_path_or_url,
            thumbnail_text=thumbnail_text,
        )
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Error in yt_dissect_packaging")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def main():
    """Run FastMCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
