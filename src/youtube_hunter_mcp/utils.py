"""
Utility functions for YouTube Hunter MCP.
Handles video ID extraction, channel URL normalization, view count parsing, and sanitization.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Tuple


def extract_video_id(url_or_id: str) -> Optional[str]:
    """Extract 11-character YouTube video ID from various URL formats or raw ID."""
    if not url_or_id:
        return None
    url_or_id = url_or_id.strip()

    # If it's already an 11-char ID
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", url_or_id):
        return url_or_id

    patterns = [
        r"(?:v=|\/v\/|embed\/|shorts\/|live\/)([a-zA-Z0-9_-]{11})",
        r"youtu\.be\/([a-zA-Z0-9_-]{11})",
        r"[?&]v=([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    return None


def normalize_channel_url(channel_url_or_handle: str) -> str:
    """Normalize any channel identifier into a valid YouTube URL."""
    c = channel_url_or_handle.strip()
    if c.startswith("http://") or c.startswith("https://"):
        # Remove trailing slash and /videos or /featured
        c = re.sub(r"/(videos|featured|shorts|playlists|community|about)/?$", "", c)
        return c

    # If it starts with @ (handle)
    if c.startswith("@"):
        return f"https://www.youtube.com/{c}"

    # If it's a channel ID (UC...)
    if c.startswith("UC") and len(c) == 24:
        return f"https://www.youtube.com/channel/{c}"

    # Default to handle with @
    return f"https://www.youtube.com/@{c}"


def parse_view_count(view_str: Any) -> int:
    """
    Parse view count string or integer into integer.
    Supports formats like:
      - '4.3M views' -> 4300000
      - '164K' -> 164000
      - '1.2B' -> 1200000000
      - '4,3 mi' -> 4300000 (pt-BR)
      - '520 mil' -> 520000 (pt-BR)
      - '1,234 views' -> 1234
    """
    if not view_str:
        return 0
    if isinstance(view_str, (int, float)):
        return int(view_str)

    s = str(view_str).strip().lower()
    # Remove 'views', 'visualizações', 'visualizacoes', 'view'
    s = re.sub(r"\s*(views|visualizações|visualizacoes|view)\b", "", s).strip()

    # Handle billion first
    b_match = re.search(r"([\d\.,]+)\s*(?:b|bi|bilh[oõ]es|billion)\b", s)
    if b_match:
        val = b_match.group(1).replace(",", ".")
        try:
            return int(float(val) * 1_000_000_000)
        except ValueError:
            pass

    # Handle million (ensure 'mil' is not mistakenly matched as 'm')
    m_match = re.search(r"([\d\.,]+)\s*(?:m(?!il)|mi\b|milh[oõ]es|million\b)", s)
    if m_match:
        val = m_match.group(1).replace(",", ".")
        try:
            return int(float(val) * 1_000_000)
        except ValueError:
            pass

    # Handle thousand (k / mil / thousand)
    k_match = re.search(r"([\d\.,]+)\s*(?:k|mil|thousand)\b", s)
    if k_match:
        val = k_match.group(1).replace(",", ".")
        try:
            return int(float(val) * 1_000)
        except ValueError:
            pass

    # Standard clean number with commas or dots
    digits_only = re.sub(r"[^\d]", "", s)
    if digits_only:
        try:
            return int(digits_only)
        except ValueError:
            return 0

    return 0


def format_seconds(seconds: int) -> str:
    """Format seconds into MM:SS or HH:MM:SS."""
    if seconds < 0:
        return "00:00"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def parse_relative_age_days(published_time: str) -> Optional[float]:
    """Parse a relative YouTube age string (e.g. '3 days ago', 'Streamed 2 weeks ago') into approximate days.

    Returns None when age cannot be determined.
    """
    if not published_time:
        return None
    s = published_time.strip().lower()
    s = re.sub(r"^(streamed|premiered|estreou|transmitido(?:\s+ao\s+vivo)?)\s+", "", s)
    m = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\b", s)
    if not m:
        # Portuguese/common short forms fallback
        m = re.search(r"(\d+)\s*(segundo|minuto|hora|dia|semana|m[eê]s|meses|ano)s?\b", s)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2)
    if unit.startswith(("second", "segundo")):
        return value / 86400.0
    if unit.startswith(("minute", "minuto")):
        return value / 1440.0
    if unit.startswith(("hour", "hora")):
        return value / 24.0
    if unit.startswith(("day", "dia")):
        return value
    if unit.startswith(("week", "semana")):
        return value * 7.0
    if unit.startswith(("month", "mês", "mes")):
        return value * 30.4375
    if unit.startswith(("year", "ano")):
        return value * 365.25
    return None


def sanitize_filename(name: str, max_length: int = 60) -> str:
    """Sanitize string to be safe as a filename."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = re.sub(r"\s+", "_", clean).strip("._")
    return clean[:max_length] or "untitled"
