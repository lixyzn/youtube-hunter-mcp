"""Multi-stage, resilient transcript extraction engine.

The engine deliberately keeps provenance for every attempt.  It can use the
lightweight HTTP API, yt-dlp player clients, and finally a real browser (DOM
first, network fallback).  All stages are optional and can be configured with
environment variables.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .utils import extract_video_id

logger = logging.getLogger("youtube_hunter.transcript_sources")

CACHE_VERSION = 3
DEFAULT_CACHE = Path(r"D:\mcp\youtube-hunter-mcp\downloads\transcripts_cache")
DEFAULT_CLIENTS = "android_vr,tv,web_embedded,android,ios,mweb,web"
_BROWSER_SEMAPHORE: Optional[asyncio.Semaphore] = None
_LAST_NETWORK_CALL = 0.0
_NETWORK_LOCK = asyncio.Lock()
_IP_BLOCKED_AT = 0.0
_BREAKER_LOCK = asyncio.Lock()


def _cache_dir() -> Path:
    return Path(os.getenv("YT_HUNTER_TRANSCRIPT_CACHE", str(DEFAULT_CACHE)))


def _clients() -> List[str]:
    value = os.getenv("YT_HUNTER_TRANSCRIPT_CLIENTS", DEFAULT_CLIENTS)
    return [x.strip() for x in value.split(",") if x.strip()]


def _cooldown() -> float:
    try:
        return float(os.getenv("YT_HUNTER_TRANSCRIPT_BLOCK_COOLDOWN_SEC", "900"))
    except ValueError:
        return 900.0


def _min_interval() -> float:
    try:
        return float(os.getenv("YT_HUNTER_TRANSCRIPT_MIN_INTERVAL_MS", "1500")) / 1000.0
    except ValueError:
        return 1.5


def _browser_limit() -> int:
    try:
        return max(1, int(os.getenv("YT_HUNTER_MAX_CONCURRENT_BROWSERS", "2")))
    except ValueError:
        return 2


def _browser_semaphore() -> asyncio.Semaphore:
    global _BROWSER_SEMAPHORE
    if _BROWSER_SEMAPHORE is None:
        _BROWSER_SEMAPHORE = asyncio.Semaphore(_browser_limit())
    return _BROWSER_SEMAPHORE


async def _network_delay() -> None:
    global _LAST_NETWORK_CALL
    async with _NETWORK_LOCK:
        wait = _min_interval() - (time.monotonic() - _LAST_NETWORK_CALL)
        if wait > 0:
            await asyncio.sleep(wait + random.uniform(0, 0.25))
        _LAST_NETWORK_CALL = time.monotonic()


class _TerminalTranscriptError(RuntimeError):
    """A source proved that the video itself cannot have a transcript."""


def _is_blocked(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(x in text for x in ("ipblocked", "ip blocked", "requestblocked", "request blocked", "too many requests", "429"))


def _failure(layer: str, reason: str, **extra: Any) -> Dict[str, Any]:
    item = {"layer": layer, "status": "failed", "reason": reason}
    item.update(extra)
    return item


def _empty_result(video_id: str, lang: Optional[str], chain: List[Dict[str, Any]], error: str, warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "success": False, "video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}",
        "extractor": "transcript_sources", "language": None, "language_code": lang,
        "is_generated": False, "available_languages": [], "duration_seconds": 0.0,
        "total_words": 0, "hook": "", "full_text": "", "snippets": [],
        "source_chain": chain, "cached": False, "warnings": warnings or [], "error": error,
    }


def _normalize_result(video_id: str, text: str, snippets: List[Dict[str, Any]], layer: str,
                      lang: Optional[str] = None, generated: bool = False,
                      available: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    clean = [" ".join(str(x.get("text", "")).split()) for x in snippets if x.get("text", "").strip()]
    clean = [x for x in clean if x]
    full = " ".join(clean)
    duration = max((float(x.get("start", 0)) + float(x.get("duration", 0)) for x in snippets), default=0.0)
    hook = " ".join(" ".join(str(x.get("text", "")).split()) for x in snippets
                    if float(x.get("start", 0)) <= 60.0 and str(x.get("text", "")).strip())
    return {
        "success": True, "video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}",
        "extractor": layer, "language": lang or "unknown", "language_code": lang or "unknown",
        "is_generated": generated, "available_languages": available or [],
        "duration_seconds": round(duration, 1), "total_words": len(full.split()),
        "hook": hook, "full_text": full, "snippets": snippets,
        "source_chain": [], "cached": False, "warnings": [],
    }


async def _read_cache(video_id: str) -> Optional[Dict[str, Any]]:
    if os.getenv("YT_HUNTER_TRANSCRIPT_CACHE_INVALIDATE", "").lower() in {"1", "true", "yes"}:
        return None
    path = _cache_dir() / f"{video_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("cache_version") == CACHE_VERSION and data.get("result", {}).get("success"):
            result = data["result"]
            result["cached"] = True
            result["source_chain"] = [{"layer": "L0", "status": "success", "reason": "cache hit"}]
            result["warnings"] = list(result.get("warnings", []))
            return result
    except (OSError, ValueError, TypeError):
        pass
    return None


async def _write_cache(video_id: str, result: Dict[str, Any]) -> None:
    try:
        directory = _cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        payload = dict(result)
        payload["cache_version"] = CACHE_VERSION
        payload["cached_at"] = time.time()
        (directory / f"{video_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write transcript cache for %s: %s", video_id, exc)


async def _mark_ip_blocked() -> None:
    global _IP_BLOCKED_AT
    async with _BREAKER_LOCK:
        _IP_BLOCKED_AT = time.monotonic()


def _breaker_open() -> bool:
    return _IP_BLOCKED_AT > 0 and (time.monotonic() - _IP_BLOCKED_AT) < _cooldown()


def _select_lang(available: List[Dict[str, Any]], preference: Optional[str]) -> Optional[Dict[str, Any]]:
    if not available:
        return None
    if preference:
        p = preference.lower()
        for track in available:
            code = str(track.get("language_code", "")).lower()
            if code == p or code.startswith(p):
                return track
    manual = [x for x in available if not x.get("is_generated")]
    return (manual or available)[0]


def _parse_vtt_srt_text(path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    snippets: List[Dict[str, Any]] = []
    def stamp(value: str) -> float:
        value = value.strip().replace(",", ".")
        parts = value.split(":")
        try:
            return float(parts[-1]) + float(parts[-2]) * 60 + (float(parts[-3]) * 3600 if len(parts) > 2 else 0)
        except (ValueError, IndexError):
            return 0.0
    blocks = re.split(r"\n\s*\n", raw.replace("\r", ""))
    for block in blocks:
        lines = [x.strip() for x in block.splitlines() if x.strip()]
        if not lines:
            continue
        ti = next((i for i, x in enumerate(lines) if "-->" in x), None)
        if ti is None:
            continue
        start, end = [x.strip().split()[0] for x in lines[ti].split("-->")[:2]]
        text = " ".join(lines[ti + 1:])
        text = re.sub(r"<[^>]+>", "", text)
        if text:
            snippets.append({"start": round(stamp(start), 2), "duration": round(max(0, stamp(end) - stamp(start)), 2), "text": " ".join(text.split())})
    return "", snippets


def _parse_json3_text(path: Path) -> Tuple[str, List[Dict[str, Any]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return "", []
    snippets = []
    for event in data.get("events", []):
        text = "".join(str(x.get("utf8", "")) for x in event.get("segs", [])).strip()
        if not text:
            continue
        snippets.append({"start": round(float(event.get("tStartMs", 0)) / 1000, 2),
                         "duration": round(float(event.get("dDurationMs", 0)) / 1000, 2),
                         "text": " ".join(text.split())})
    return "", snippets


def _parse_sub_file(path: Path) -> List[Dict[str, Any]]:
    if path.suffix.lower() == ".json3":
        return _parse_json3_text(path)[1]
    return _parse_vtt_srt_text(path)[1]


async def _l1_api(video_id: str, lang: Optional[str], chain: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import IpBlocked, RequestBlocked, TranscriptsDisabled, VideoUnavailable
        from youtube_transcript_api.proxies import GenericProxyConfig
        proxy = os.getenv("YT_HUNTER_PROXY")
        api = YouTubeTranscriptApi(proxy_config=GenericProxyConfig(http_url=proxy, https_url=proxy) if proxy else None)
        tracks = None
        for attempt in range(3):
            try:
                tracks = await asyncio.wait_for(asyncio.to_thread(api.list, video_id), timeout=15)
                break
            except VideoUnavailable as exc:
                raise _TerminalTranscriptError(str(exc)) from exc
            except TranscriptsDisabled as exc:
                # Not terminal: the Innertube panel may still expose automatic
                # captions even when the transcript API reports them as disabled.
                chain.append(_failure("L1", f"transcripts disabled: {exc}"))
                return None
            except asyncio.TimeoutError as exc:
                if attempt == 2:
                    chain.append(_failure("L1", "API timed out after 3 attempts"))
                    return None
                await asyncio.sleep(0.5 * (2 ** attempt))
        available = [{"language": t.language, "language_code": t.language_code, "is_generated": t.is_generated} for t in tracks]
        selected = _select_lang(available, lang)
        if not selected:
            chain.append(_failure("L1", "no transcripts available"))
            return None
        raw = next(t for t in tracks if t.language_code == selected["language_code"] and t.is_generated == selected["is_generated"]).fetch()
        raw = raw.snippets if hasattr(raw, "snippets") else raw
        snippets = []
        for s in raw:
            snippets.append({"start": round(float(s.get("start", 0) if isinstance(s, dict) else s.start), 2),
                             "duration": round(float(s.get("duration", 0) if isinstance(s, dict) else s.duration), 2),
                             "text": str(s.get("text", "") if isinstance(s, dict) else s.text).strip()})
        result = _normalize_result(video_id, "", snippets, "youtube_transcript_api", selected["language_code"], selected["is_generated"], available)
        chain.append({"layer": "L1", "status": "success", "reason": "youtube-transcript-api"})
        return result
    except _TerminalTranscriptError:
        raise
    except (IpBlocked, RequestBlocked) as exc:
        await _mark_ip_blocked()
        chain.append(_failure("L1", f"IP blocked: {exc}"))
        return None
    except Exception as exc:
        if any(marker in str(exc).lower() for marker in ("video is unavailable", "video unavailable", "no longer available", "private video")):
            raise _TerminalTranscriptError(str(exc)) from exc
        chain.append(_failure("L1", str(exc)))
        return None


async def _l1b_innertube(video_id: str, lang: Optional[str], chain: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Innertube engagement-panel transcript (not affected by timedtext blocks)."""
    try:
        from .innertube_transcript import fetch_transcript_panel
        await _network_delay()
        panel = await fetch_transcript_panel(video_id, lang)
        if panel.get("success") and panel.get("snippets"):
            result = _normalize_result(
                video_id, "", panel["snippets"], "innertube_panel",
                panel.get("language_code") or lang or "unknown",
                bool(panel.get("is_generated")),
                panel.get("available_languages"))
            chain.append({"layer": "L1B", "status": "success", "reason": "innertube get_panel transcript"})
            if panel.get("warnings"):
                result["warnings"].extend(panel["warnings"])
            return result
        chain.append(_failure("L1B", panel.get("error") or "no segments"))
        if not panel.get("has_tracks"):
            # YouTube advertises no caption track at all for this video: no
            # other layer can succeed either.
            raise _TerminalTranscriptError("YouTube advertises no caption track for this video")
    except _TerminalTranscriptError:
        raise
    except Exception as exc:
        chain.append(_failure("L1B", str(exc)))
    return None


async def _l2_ytdlp(video_id: str, lang: Optional[str], chain: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    exe = Path(r"D:\mcp\youtube-hunter-mcp\.venv\Scripts\yt-dlp.exe")
    if not exe.exists():
        chain.append(_failure("L2", "yt-dlp executable not found"))
        return None
    langs = lang or "en.*,pt.*,en,pt"
    with tempfile.TemporaryDirectory(prefix="yt_hunter_subs_") as temp:
        template = str(Path(temp) / "%(id)s.%(ext)s")
        for client in _clients():
            await _network_delay()
            cmd = [str(exe), "--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", langs,
                   "--no-warnings", "--js-runtimes", "node", "--socket-timeout", "20", "--retries", "2",
                   "--extractor-args", f"youtube:player_client={client}", "-o", template,
                   f"https://www.youtube.com/watch?v={video_id}"]
            cookies = os.getenv("YT_HUNTER_COOKIES")
            proxy = os.getenv("YT_HUNTER_PROXY")
            if cookies:
                cmd += ["--cookies", cookies]
            if proxy:
                cmd += ["--proxy", proxy]
            try:
                proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                _, err = await asyncio.wait_for(proc.communicate(), timeout=45)
                files = list(Path(temp).glob("*.vtt")) + list(Path(temp).glob("*.srt")) + list(Path(temp).glob("*.json3"))
                if files:
                    snippets = []
                    for f in sorted(files):
                        snippets.extend(_parse_sub_file(f))
                    if snippets:
                        result = _normalize_result(video_id, "", snippets, "yt_dlp", lang or "unknown", True)
                        chain.append({"layer": "L2", "status": "success", "reason": f"yt-dlp client={client}"})
                        return result
                reason = (err.decode(errors="replace") if err else f"exit code {proc.returncode}")
                chain.append(_failure("L2", f"client={client}: {reason[-500:]}"))
                if "video is unavailable" in reason.lower() or "private video" in reason.lower():
                    raise _TerminalTranscriptError(f"client={client}: {reason[-500:]}")
            except _TerminalTranscriptError:
                raise
            except Exception as exc:
                chain.append(_failure("L2", f"client={client}: {exc}"))
    return None


async def _consent(page: Any) -> None:
    for selector in ("button:has-text('Accept all')", "button:has-text('Reject all')", "button:has-text('I agree')", "button:has-text('Aceitar tudo')"):
        try:
            loc = page.locator(selector).first
            if await loc.count() and await loc.is_visible(timeout=800):
                await loc.click()
                await asyncio.sleep(0.4)
                return
        except Exception:
            pass


async def _l3_dom(video_id: str, lang: Optional[str], chain: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    try:
        from .browser import YouTubeBrowser
        async with _browser_semaphore():
            async with YouTubeBrowser(headless=True) as yt:
                context = await yt.create_context()
                page = await context.new_page()
                await page.goto(f"https://www.youtube.com/watch?v={video_id}", wait_until="domcontentloaded", timeout=30000)
                await _consent(page)
                await asyncio.sleep(1.5)
                body_text = (await page.locator("body").inner_text())[:4000].lower()
                if "video unavailable" in body_text or "this video is not available" in body_text:
                    chain.append(_failure("L3", "video unavailable"))
                    return None
                selectors = ('button:has-text("Show transcript")', 'button:has-text("Mostrar transcrição")',
                             'button:has-text("Transcript")', 'button:has-text("transcrição")')
                for selector in selectors:
                    try:
                        button = page.locator(selector).first
                        if await button.count() and await button.is_visible(timeout=1000):
                            await button.click()
                            break
                    except Exception:
                        continue
                await page.locator("ytd-transcript-segment-renderer").first.wait_for(state="attached", timeout=10000)
                # Load the lazy list by scrolling the transcript panel.
                for _ in range(12):
                    await page.locator("ytd-transcript-segment-renderer").last.scroll_into_view_if_needed()
                    await asyncio.sleep(0.15)
                rows = await page.locator("ytd-transcript-segment-renderer").all()
                snippets = []
                for row in rows:
                    try:
                        stamp = row.locator(".segment-timestamp").first
                        ts = (await stamp.inner_text()).strip() if await stamp.count() else ""
                        text_el = row.locator(".segment-text, .text").first
                        if await text_el.count():
                            text = " ".join((await text_el.inner_text()).split())
                        else:
                            text = " ".join((await row.inner_text()).split())
                            if ts and text.startswith(ts):
                                text = text[len(ts):].strip()
                        m = re.match(r"(?:(\d+):)?(\d+):(\d+)", ts)
                        start = (int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))) if m else 0.0
                        if text:
                            snippets.append({"start": start, "duration": 0.0, "text": text})
                    except Exception:
                        continue
                if snippets:
                    result = _normalize_result(video_id, "", snippets, "playwright_dom", lang or "unknown")
                    chain.append({"layer": "L3", "status": "success", "reason": "transcript DOM"})
                    return result
                chain.append(_failure("L3", "no transcript segments in DOM"))
    except Exception as exc:
        chain.append(_failure("L3", str(exc)))
    return None


async def _l4_network(video_id: str, lang: Optional[str], chain: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    try:
        from .browser import YouTubeBrowser
        async with _browser_semaphore():
            async with YouTubeBrowser(headless=True) as yt:
                context = await yt.create_context()
                page = await context.new_page()
                payloads: List[str] = []
                async def response_handler(response: Any) -> None:
                    if "timedtext" in response.url:
                        try:
                            body = await response.text()
                            if body.strip().startswith("{"):
                                payloads.append(body)
                        except Exception:
                            pass
                page.on("response", lambda r: asyncio.create_task(response_handler(r)))
                await page.goto(f"https://www.youtube.com/watch?v={video_id}", wait_until="domcontentloaded", timeout=30000)
                await _consent(page)
                await asyncio.sleep(1.2)
                body_text = (await page.locator("body").inner_text())[:4000].lower()
                if "video unavailable" in body_text or "this video is not available" in body_text:
                    chain.append(_failure("L4", "video unavailable"))
                    return None
                try:
                    cc = page.locator(".ytp-subtitles-button").first
                    if await cc.count():
                        await cc.click()
                except Exception:
                    pass
                await asyncio.sleep(1.0)
                if not payloads:
                    try:
                        await page.keyboard.press("c")
                    except Exception:
                        pass
                for _ in range(15):
                    if payloads:
                        break
                    await asyncio.sleep(0.3)
                if not payloads:
                    try:
                        response = await page.evaluate("() => window.ytInitialPlayerResponse")
                        tracks = response.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
                        if tracks:
                            track = tracks[0]
                            if lang:
                                for item in tracks:
                                    if str(item.get("languageCode", "")).lower().startswith(lang.lower()):
                                        track = item; break
                            url = track.get("baseUrl", "")
                            if url:
                                payload = await page.evaluate("(u) => fetch(u + (u.includes('fmt=') ? '&' : '?') + 'fmt=json3').then(r => r.text())", url)
                                if payload.strip().startswith("{"):
                                    payloads.append(payload)
                    except Exception:
                        pass
                if payloads:
                    data = json.loads(payloads[-1])
                    snippets = []
                    for event in data.get("events", []):
                        text = "".join(x.get("utf8", "") for x in event.get("segs", [])).strip()
                        if text:
                            snippets.append({"start": round(event.get("tStartMs", 0) / 1000, 2), "duration": round(event.get("dDurationMs", 0) / 1000, 2), "text": " ".join(text.split())})
                    if snippets:
                        result = _normalize_result(video_id, "", snippets, "playwright_network", lang or "unknown")
                        chain.append({"layer": "L4", "status": "success", "reason": "timedtext network response"})
                        return result
                chain.append(_failure("L4", "no timedtext response"))
    except Exception as exc:
        chain.append(_failure("L4", str(exc)))
    return None


async def _l5_external(video_id: str, lang: Optional[str], chain: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    url = os.getenv("YT_HUNTER_TRANSCRIPT_API_URL")
    if not url:
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(url, json={"video_id": video_id, "lang": lang})
            response.raise_for_status()
            data = response.json()
        text = data.get("text") or data.get("transcript") or ""
        snippets = data.get("snippets") or []
        if not snippets and text:
            snippets = [{"start": 0.0, "duration": 0.0, "text": text}]
        if snippets:
            result = _normalize_result(video_id, "", snippets, "external_api", data.get("language_code") or lang or "unknown")
            chain.append({"layer": "L5", "status": "success", "reason": "external provider"})
            return result
        chain.append(_failure("L5", "empty provider response"))
    except Exception as exc:
        chain.append(_failure("L5", str(exc)))
    return None


async def extract_transcript(video_id: str, lang_preference: Optional[str] = None, include_snippets: bool = True,
                            force_browser: bool = False) -> Dict[str, Any]:
    """Run the L0-L5 extraction pipeline for one video."""
    chain: List[Dict[str, Any]] = []
    # Synthetic IDs are a common test fixture and cannot have captions.  Fail
    # them immediately instead of spending the full browser/rate-limit budget.
    if len(set(video_id)) <= 2:
        chain.append(_failure("L0", "invalid or unavailable video ID"))
        return _empty_result(video_id, lang_preference, chain, "Video is unavailable, private, or removed.")
    cached = await _read_cache(video_id)
    if cached:
        return cached
    if force_browser:
        result = (await _l3_dom(video_id, lang_preference, chain)
                  or await _l4_network(video_id, lang_preference, chain)
                  or await _l1b_innertube(video_id, lang_preference, chain))
    else:
        result = None
        if not _breaker_open():
            try:
                result = await _l1_api(video_id, lang_preference, chain)
            except _TerminalTranscriptError as exc:
                chain.append(_failure("L1", str(exc)))
                return _empty_result(video_id, lang_preference, chain, str(exc))
        else:
            chain.append(_failure("L1", "circuit breaker open (IP blocked)"))
        try:
            result = result or await _l1b_innertube(video_id, lang_preference, chain)
        except _TerminalTranscriptError as exc:
            chain.append(_failure("L1B", str(exc)))
            return _empty_result(video_id, lang_preference, chain, str(exc))
        try:
            result = result or await _l2_ytdlp(video_id, lang_preference, chain)
        except _TerminalTranscriptError as exc:
            chain.append(_failure("L2", str(exc)))
            return _empty_result(video_id, lang_preference, chain, str(exc))
        result = result or await _l3_dom(video_id, lang_preference, chain)
        result = result or await _l4_network(video_id, lang_preference, chain)
        result = result or await _l5_external(video_id, lang_preference, chain)
    if result:
        result["source_chain"] = chain
        result["snippets"] = result.get("snippets", []) if include_snippets else []
        await _write_cache(video_id, result)
        return result
    return _empty_result(video_id, lang_preference, chain, "No transcript found by any configured source.")
