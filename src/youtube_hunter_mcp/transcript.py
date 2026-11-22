"""Universal transcript extractor for YouTube Hunter MCP.

Transcripts are provided by the resilient multi-stage engine in
``transcript_sources``.  The public functions and result keys remain stable
for existing MCP consumers; only provenance fields were added.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from .transcript_sources import extract_transcript
from .utils import extract_video_id

logger = logging.getLogger("youtube_hunter.transcript")


async def get_video_transcript_async(
    url_or_id: str,
    lang_preference: Optional[str] = None,
    include_snippets: bool = True,
    hook_duration_seconds: float = 60.0,
    force_browser: bool = False,
) -> Dict[str, Any]:
    """Extract a transcript using cache, HTTP API, yt-dlp and browser layers."""
    video_id = extract_video_id(url_or_id)
    if not video_id:
        return {"success": False, "error": f"Invalid YouTube video URL or ID: '{url_or_id}'"}
    result = await extract_transcript(video_id, lang_preference, include_snippets, force_browser)
    # The engine uses the standard 60 second hook contract.  Keep the argument
    # in the public API for backwards compatibility.
    if result.get("success") and hook_duration_seconds != 60.0:
        words = result.get("full_text", "").split()
        count = max(0, int(hook_duration_seconds / 60 * 140))
        result["hook"] = " ".join(words[:count])
    return result


def get_video_transcript(
    url_or_id: str,
    lang_preference: Optional[str] = None,
    include_snippets: bool = True,
    hook_duration_seconds: float = 60.0,
) -> Dict[str, Any]:
    """Synchronous wrapper around the async multi-stage engine."""
    video_id = extract_video_id(url_or_id)
    if not video_id:
        return {"success": False, "error": f"Invalid YouTube video URL or ID: '{url_or_id}'"}
    coroutine = get_video_transcript_async(video_id, lang_preference, include_snippets, hook_duration_seconds)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    # Some existing internal callers are synchronous but run inside an async
    # function.  Execute in a worker thread rather than breaking the event loop.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


def parse_raw_transcript_text(
    raw_text: str,
    video_id: str = "manual_paste",
    hook_duration_seconds: float = 60.0,
    avg_words_per_minute: float = 140.0,
) -> Dict[str, Any]:
    """Parse manually pasted transcript or text input."""
    if not raw_text or not raw_text.strip():
        return {"success": False, "error": "Provided transcript text is empty."}
    clean_lines = [" ".join(line.split()) for line in raw_text.splitlines() if line.strip()]
    full_text = " ".join(clean_lines)
    words = full_text.split()
    total_words = len(words)
    est_duration_seconds = round((total_words / avg_words_per_minute) * 60.0, 1) if avg_words_per_minute > 0 else 0.0
    hook_word_count = int((hook_duration_seconds / 60.0) * avg_words_per_minute)
    hook_text = " ".join(words[:hook_word_count]) if total_words > hook_word_count else full_text
    return {
        "success": True, "video_id": video_id, "extractor": "manual_paste",
        "duration_seconds": est_duration_seconds, "total_words": total_words,
        "hook": hook_text, "full_text": full_text, "snippets": [],
        "source_chain": [{"layer": "manual", "status": "success", "reason": "pasted text"}],
        "cached": False, "warnings": [],
    }
