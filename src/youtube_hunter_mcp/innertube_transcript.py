"""Innertube transcript extraction (YouTube engagement-panel API).

Why this exists
---------------
Since 2025/2026 YouTube requires a PO Token (BotGuard) for ``/api/timedtext``
subtitle requests and aggressively reputation-blocks datacenter IPs (HTTP 429
``Sorry...``).  Every classic route dies on a blocked IP:

* ``youtube-transcript-api``  -> RequestBlocked / IpBlocked
* ``yt-dlp`` subtitles        -> HTTP 429 even with a valid PO Token
* the real YouTube UI         -> its own caption request also gets 429

The transcript *panel* however is served by the Innertube JSON API
(``POST /youtubei/v1/get_panel``) which is **not** reputation-blocked.  The
request only needs:

* ``context.client`` (WEB client, visitor data, client version)
* ``panelId`` = ``PAmodern_transcript_view``
* ``params`` = a small protobuf blob that embeds the video id

The ``params`` blob is deterministic, so it can be built locally:

    aa 09 0f | 0a <len(video_id)> <video_id> | 18 07

The response contains one ``transcriptSegmentViewModel`` per caption line
(timestamp + text), which covers the whole video in a single request.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("youtube_hunter.innertube_transcript")

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
PANEL_ID = "PAmodern_transcript_view"
PANEL_URL = "https://www.youtube.com/youtubei/v1/get_panel?prettyPrint=false"
WATCH_URL = "https://www.youtube.com/watch?v={video_id}"


_STOPWORDS = {
    "en": {"the", "and", "that", "have", "for", "not", "with", "you", "this", "but", "his", "from",
           "they", "she", "will", "would", "there", "their", "what", "about", "which", "when", "just",
           "like", "know", "really", "think", "going", "because", "people", "video", "channel"},
    "pt": {"que", "não", "uma", "para", "com", "como", "mais", "por", "mas", "isso", "você", "está",
           "são", "dos", "das", "ele", "ela", "muito", "quando", "porque", "gente", "aqui", "você",
           "então", "também", "sobre", "nós", "eles", "ser", "ter", "fazer", "vez"},
    "es": {"que", "como", "para", "una", "los", "las", "pero", "más", "este", "esta", "todo", "muy",
           "porque", "cuando", "gente", "video", "canal", "nos", "ya", "sin", "sobre", "está", "su",
           "también", "hace", "hay", "ser", "hacer", "puede"},
    "fr": {"que", "les", "des", "pour", "dans", "une", "est", "pas", "plus", "vous", "avec", "sur",
           "mais", "c'est", "nous", "comme", "tout", "bien", "très", "vidéo", "chaîne"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "ein", "eine", "mit", "für", "auf", "sich",
           "dass", "wir", "auch", "aber", "wenn", "oder", "wie", "war", "mehr", "video", "kanal"},
    "it": {"che", "per", "con", "del", "una", "sono", "non", "più", "come", "anche", "questo", "molto",
           "questi", "alla", "nel", "perché", "gente", "video", "canale", "fare"},
}


def detect_language(text: str) -> str:
    """Very small stopword based language detector (en/pt/es/fr/de/it).

    It is intentionally conservative: when no signal is found it returns
    ``"und"`` instead of guessing.
    """
    sample = " ".join(text.split()[:600]).lower()
    words = re.findall(r"[a-zà-ÿ']+", sample)
    if not words:
        return "und"
    if any(0xAC00 <= ord(ch) <= 0xD7A3 for ch in sample):
        return "ko"
    if any(0x4E00 <= ord(ch) <= 0x9FFF for ch in sample):
        return "ja"
    if any(0x0400 <= ord(ch) <= 0x04FF for ch in sample):
        return "ru"
    counts = {code: sum(1 for w in words if w in stops) for code, stops in _STOPWORDS.items()}
    best = max(counts, key=lambda k: counts[k])
    if counts[best] < 3:
        return "und"
    return best


def build_panel_params(video_id: str) -> str:
    """Build the ``params`` blob expected by the modern transcript panel."""
    raw = bytes([0xAA, 0x09, 0x0F, 0x0A, len(video_id)]) + video_id.encode("utf-8") + bytes([0x18, 0x07])
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def parse_timestamp(value: str) -> Optional[float]:
    """Parse ``M:SS`` / ``H:MM:SS`` / ``MM:SS.mmm`` into seconds."""
    if not value:
        return None
    parts = value.strip().split(":")
    try:
        numbers = [float(p) for p in parts]
    except ValueError:
        return None
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def _collect_segments(payload: Any) -> List[Dict[str, Any]]:
    """Recursively collect ``transcriptSegmentViewModel`` entries."""
    found: List[Dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            model = node.get("transcriptSegmentViewModel")
            if isinstance(model, dict):
                text = model.get("simpleText")
                if not text:
                    runs = model.get("runs")
                    if isinstance(runs, list):
                        text = "".join(str(r.get("text", "")) for r in runs if isinstance(r, dict))
                text = (text or "").strip()
                stamp = model.get("timestamp")
                if text:
                    found.append({"timestamp": stamp or "", "text": text})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found


def _extract_client_version(html: str) -> str:
    match = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', html)
    return match.group(1) if match else "2.20261026.01.00"


def _extract_visitor_data(html: str) -> str:
    match = re.search(r'"visitorData":"([^"]+)"', html)
    return match.group(1) if match else ""


def _extract_caption_tracks(html: str) -> List[Dict[str, Any]]:
    """Best-effort list of available caption tracks from the watch page."""
    tracks: List[Dict[str, Any]] = []
    match = re.search(r'"captionTracks":(\[.*?\]),"audioTracks"', html, re.S)
    if not match:
        return tracks
    try:
        raw = json.loads(match.group(1))
    except Exception:
        return tracks
    for track in raw:
        if not isinstance(track, dict):
            continue
        vss = str(track.get("vssId", ""))
        tracks.append({
            "language_code": track.get("languageCode"),
            "name": (track.get("name") or {}).get("simpleText") or track.get("languageCode"),
            "is_generated": vss.startswith("a."),
        })
    return tracks


def _load_cookies() -> Dict[str, str]:
    """Load a Netscape ``cookies.txt`` (as produced by 'Get cookies.txt LOCALLY')."""
    path = os.getenv("YT_HUNTER_COOKIES")
    if not path:
        return {}
    file = Path(path)
    if not file.exists():
        return {}
    cookies: Dict[str, str] = {}
    try:
        for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) < 7:
                continue
            name, value = fields[-2], fields[-1]
            cookies[name] = value
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Could not read cookies file %s: %s", file, exc)
    return cookies


def _client_kwargs() -> Dict[str, Any]:
    proxy = os.getenv("YT_HUNTER_PROXY")
    kwargs: Dict[str, Any] = {
        "timeout": httpx.Timeout(30.0, connect=15.0),
        "follow_redirects": True,
        "headers": {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    }
    if proxy:
        kwargs["proxy"] = proxy
    cookies = _load_cookies()
    if cookies:
        kwargs["cookies"] = cookies
    return kwargs


async def fetch_transcript_panel(video_id: str, lang: Optional[str] = None) -> Dict[str, Any]:
    """Fetch a transcript through the Innertube engagement panel API.

    Returns a dict with ``success``, ``snippets`` and metadata.  Never raises
    for ordinary failures - the caller decides what to do next.
    """
    result: Dict[str, Any] = {
        "success": False,
        "video_id": video_id,
        "snippets": [],
        "available_languages": [],
        "language_code": lang or "unknown",
        "is_generated": True,
        "warnings": [],
        "has_tracks": False,
        "error": None,
    }
    try:
        async with httpx.AsyncClient(**_client_kwargs()) as client:
            page = await client.get(WATCH_URL.format(video_id=video_id))
            if page.status_code != 200:
                result["error"] = f"watch page HTTP {page.status_code}"
                return result
            html = page.text
            if "Sign in to confirm" in html and "not a bot" in html:
                result["error"] = "YouTube served a bot-check page"
                return result

            client_version = _extract_client_version(html)
            visitor_data = _extract_visitor_data(html)
            tracks = _extract_caption_tracks(html)
            result["available_languages"] = tracks

            context = {
                "client": {
                    "hl": "en",
                    "gl": "BR",
                    "clientName": "WEB",
                    "clientVersion": client_version,
                    "visitorData": visitor_data,
                    "userAgent": USER_AGENT,
                    "osName": "Windows",
                    "osVersion": "10.0",
                    "platform": "DESKTOP",
                    "browserName": "Chrome",
                    "browserVersion": "140.0.0.0",
                    "timeZone": "America/Sao_Paulo",
                    "originalUrl": WATCH_URL.format(video_id=video_id),
                }
            }
            headers = {
                "Content-Type": "application/json",
                "X-Youtube-Client-Name": "1",
                "X-Youtube-Client-Version": client_version,
                "Origin": "https://www.youtube.com",
                "Referer": WATCH_URL.format(video_id=video_id),
            }
            if visitor_data:
                headers["X-Goog-Visitor-Id"] = visitor_data
            body = {
                "context": context,
                "panelId": PANEL_ID,
                "params": build_panel_params(video_id),
            }
            response = await client.post(PANEL_URL, headers=headers, content=json.dumps(body).encode("utf-8"))
            if response.status_code != 200:
                result["error"] = f"get_panel HTTP {response.status_code}"
                return result
            payload = response.json()
            segments = _collect_segments(payload)
            if not segments:
                result["error"] = "panel returned no transcript segments"
                result["has_tracks"] = bool(tracks)
                return result

            snippets: List[Dict[str, Any]] = []
            parsed: List[Tuple[float, str]] = []
            for segment in segments:
                seconds = parse_timestamp(segment.get("timestamp", ""))
                if seconds is None:
                    seconds = float(len(snippets))
                parsed.append((seconds, segment["text"]))
            for index, (start, text) in enumerate(parsed):
                end = parsed[index + 1][0] if index + 1 < len(parsed) else start + 3.0
                snippets.append({
                    "start": round(start, 2),
                    "duration": round(max(0.0, end - start), 2),
                    "text": text,
                })
            result["success"] = True
            result["snippets"] = snippets
            # The panel serves the player's default caption track and does not
            # expose which track it is.  Detect the language from the text and
            # cross-check against the tracks advertised by the watch page.
            full_text = " ".join(segment["text"] for segment in segments)
            detected = detect_language(full_text)
            result["language_code"] = detected
            same_lang = [t for t in tracks if str(t.get("language_code", "")).lower().startswith(detected)]
            if same_lang:
                result["is_generated"] = all(bool(t.get("is_generated")) for t in same_lang)
            else:
                result["is_generated"] = True
            if lang and detected != "und" and not lang.lower().startswith(detected):
                result["warnings"] = [f"requested language '{lang}' unavailable; got '{detected}'"]
            return result
    except Exception as exc:
        result["error"] = str(exc)
        return result
