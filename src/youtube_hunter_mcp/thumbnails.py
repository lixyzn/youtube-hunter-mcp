"""
High-resolution thumbnail resolver and batch downloader for YouTube Hunter MCP.
Fetches maximum available quality (maxresdefault/hq720/hqdefault) and saves locally for vision analysis.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from PIL import Image

import os

from .utils import extract_video_id, sanitize_filename

# Base directory for storing downloaded assets on Disk D
_FALLBACK_DIR = Path(__file__).resolve().parents[2] / "downloads"
_HARDCODED_DIR = Path("/run/media/fernando/589488AB94888CE6/youtube-hunter-mcp/downloads")
BASE_DOWNLOAD_DIR = (
    Path(os.environ["YT_HUNTER_DOWNLOADS"])
    if "YT_HUNTER_DOWNLOADS" in os.environ
    else (_HARDCODED_DIR if _HARDCODED_DIR.exists() else _FALLBACK_DIR)
)
THUMBNAILS_DIR = BASE_DOWNLOAD_DIR / "thumbnails"
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)

THUMBNAIL_QUALITY_CANDIDATES = [
    "maxresdefault.jpg",  # 1920x1080 / 1280x720
    "hq720.jpg",          # 1280x720
    "sddefault.jpg",       # 640x480
    "hqdefault.jpg",       # 480x360
    "mqdefault.jpg",       # 320x180
]


def resolve_best_thumbnail_url(video_id: str) -> str:
    """Check candidate URLs and return the highest resolution working URL."""
    client = httpx.Client(timeout=10.0, follow_redirects=True)
    base = f"https://i.ytimg.com/vi/{video_id}"
    for candidate in THUMBNAIL_QUALITY_CANDIDATES:
        url = f"{base}/{candidate}"
        try:
            resp = client.head(url)
            if resp.status_code == 200 and int(resp.headers.get("content-length", 0)) > 1000:
                return url
        except Exception:
            continue
    # Default fallback
    return f"{base}/hqdefault.jpg"


def download_thumbnail(
    url_or_id: str,
    subfolder: str = "general",
    custom_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Download highest resolution thumbnail for a video and save to local disk.

    Args:
        url_or_id: YouTube video URL or ID.
        subfolder: Subfolder name (e.g. channel name or search keyword).
        custom_name: Optional prefix or name for the saved file.

    Returns:
        Dict with local file path, remote URL, dimensions, and size.
    """
    video_id = extract_video_id(url_or_id)
    if not video_id:
        return {"success": False, "error": f"Invalid video ID: '{url_or_id}'"}

    safe_subfolder = sanitize_filename(subfolder, max_length=50)
    target_dir = THUMBNAILS_DIR / safe_subfolder
    target_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{video_id}.jpg"
    if custom_name:
        filename = f"{sanitize_filename(custom_name, max_length=50)}_{video_id}.jpg"

    dest_path = target_dir / filename

    # Reuse existing thumbnail to avoid redundant downloads across mining runs
    if dest_path.exists() and dest_path.stat().st_size > 1500:
        width, height, aspect_ratio = 0, 0, "unknown"
        try:
            with Image.open(dest_path) as img:
                width, height = img.size
                if height > 0:
                    ratio_val = width / height
                    aspect_ratio = "16:9" if 1.7 < ratio_val < 1.8 else f"{width}:{height}"
        except Exception:
            pass
        return {
            "success": True,
            "video_id": video_id,
            "local_path": str(dest_path.resolve()),
            "file_uri": dest_path.resolve().as_uri(),
            "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
            "width": width,
            "height": height,
            "aspect_ratio": aspect_ratio,
            "size_bytes": dest_path.stat().st_size,
            "cached": True,
        }

    client = httpx.Client(timeout=15.0, follow_redirects=True)
    base = f"https://i.ytimg.com/vi/{video_id}"
    downloaded_url = None
    content = None

    for candidate in THUMBNAIL_QUALITY_CANDIDATES:
        cand_url = f"{base}/{candidate}"
        try:
            resp = client.get(cand_url)
            # YouTube sometimes returns 200 with tiny placeholder images (around 1000 bytes)
            if resp.status_code == 200 and len(resp.content) > 1500:
                downloaded_url = cand_url
                content = resp.content
                break
        except Exception:
            continue

    if not content:
        return {
            "success": False,
            "video_id": video_id,
            "error": "Could not download thumbnail from any known quality endpoint.",
        }

    dest_path.write_bytes(content)

    # Inspect image with Pillow
    width, height, aspect_ratio = 0, 0, "unknown"
    try:
        with Image.open(dest_path) as img:
            width, height = img.size
            if height > 0:
                ratio_val = width / height
                aspect_ratio = "16:9" if 1.7 < ratio_val < 1.8 else f"{width}:{height}"
    except Exception:
        pass

    return {
        "success": True,
        "video_id": video_id,
        "local_path": str(dest_path.resolve()),
        "file_uri": dest_path.resolve().as_uri(),
        "thumbnail_url": downloaded_url,
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
        "size_bytes": len(content),
        "cached": False,
    }


def batch_download_thumbnails(
    items: List[Dict[str, Any]],
    subfolder: str = "batch",
) -> List[Dict[str, Any]]:
    """
    Download thumbnails for a list of items (each item having 'video_id' or 'url').
    """
    results = []
    for item in items:
        vid = item.get("video_id") or item.get("url") or item.get("id")
        title = item.get("title", "")
        if not vid:
            continue
        res = download_thumbnail(vid, subfolder=subfolder, custom_name=title)
        results.append({
            "video_id": res.get("video_id", vid),
            "title": title,
            **res,
        })
    return results
