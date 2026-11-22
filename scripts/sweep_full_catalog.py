"""Sweep the complete reference-catalog sample and build a transcript corpus.

This script uses only public/internal APIs of youtube-hunter-mcp.  It does not
modify the MCP package.  Processing is deliberately sequential so the
Innertube transcript endpoint stays within its configured rate limit.

Outputs:
  D:\\pesquisa de mercado anime\\04_scripts_e_hooks\\CATALOGO_COMPLETO_<ts>.json
  D:\\pesquisa de mercado anime\\04_scripts_e_hooks\\CATALOGO_COMPLETO_<ts>.md
  D:\\pesquisa de mercado anime\\07_transcricoes\\<video_id>.json
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("YT_HUNTER_TRANSCRIPT_MIN_INTERVAL_MS", "1500")

from youtube_hunter_mcp.channel_miner import deep_mine_channel  # noqa: E402
from youtube_hunter_mcp.innertube_transcript import fetch_transcript_panel  # noqa: E402
from youtube_hunter_mcp.pacing_analyzer import analyze_narrative_pacing  # noqa: E402

RESEARCH_DIR = Path(r"D:\pesquisa de mercado anime")
DOSSIERS_DIR = RESEARCH_DIR / "03_canais_referencia"
HOOKS_DIR = RESEARCH_DIR / "04_scripts_e_hooks"
CORPUS_DIR = RESEARCH_DIR / "07_transcricoes"
VAULT_DIR = Path(r"D:\cerebro\10_Pesquisa")
YTDLP = ROOT / ".venv" / "Scripts" / "yt-dlp.exe"
OLD_JSON = HOOKS_DIR / "HOOKS_WPM_20261026_165530.json"
HEADER_RE = re.compile(r"\*\*Channel\*\*:\s*\[([^]]+)\]\((https?://[^)]+)\)")
MIN_INTERVAL = float(os.getenv("YT_HUNTER_TRANSCRIPT_MIN_INTERVAL_MS", "1500")) / 1000.0
_last_network = 0.0


def discover_channels() -> list[dict[str, str]]:
    channels: list[dict[str, str]] = []
    for dossier in sorted(DOSSIERS_DIR.glob("DOSSIER_*_TRANSCRIT.md")):
        match = HEADER_RE.search(dossier.read_text(encoding="utf-8", errors="replace"))
        if match:
            channels.append({"channel": match.group(1).strip(), "url": match.group(2).strip()})
    return channels


async def network_delay() -> None:
    global _last_network
    wait = MIN_INTERVAL - (time.monotonic() - _last_network)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_network = time.monotonic()


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_old_rows() -> dict[str, dict[str, Any]]:
    if not OLD_JSON.exists():
        return {}
    data = json.loads(OLD_JSON.read_text(encoding="utf-8"))
    return {str(row["video_id"]): row for row in data.get("videos", []) if row.get("video_id")}


def transcript_cache(video_id: str) -> dict[str, Any]:
    path = ROOT / "downloads" / "transcripts_cache" / f"{video_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("result", data)
    except (OSError, ValueError, TypeError):
        return {}


def row_from_mined(channel: str, video: dict[str, Any], mode: str) -> dict[str, Any]:
    trans = video.get("transcript") or {}
    full = trans.get("full_script") or ""
    hook = trans.get("hook_first_60s") or ""
    duration = as_float(trans.get("duration_seconds"))
    metrics: dict[str, Any] = {}
    loops: dict[str, Any] = {}
    if full and duration > 0:
        pacing = analyze_narrative_pacing(full, duration_seconds=duration, hook_text=hook)
        if pacing.get("success"):
            metrics = pacing.get("metrics", {})
            loops = pacing.get("engagement_loops", {})
    cached = transcript_cache(str(video.get("video_id")))
    extractor = cached.get("extractor") if cached.get("success") else None
    chain = cached.get("source_chain", []) if cached.get("success") else []
    factor = as_float(video.get("outlier_score"), 1.0)
    views = int(video.get("views") or 0)
    return {
        "channel": channel,
        "title": video.get("title", ""),
        "video_id": video.get("video_id", ""),
        "url": video.get("url", f"https://www.youtube.com/watch?v={video.get('video_id', '')}"),
        "views": views,
        "views_raw": video.get("views_raw", ""),
        "outlier_factor": factor,
        "duration_seconds": duration or None,
        "word_count": trans.get("word_count") or metrics.get("total_words") or 0,
        "overall_wpm": metrics.get("overall_wpm"),
        "hook_wpm": metrics.get("hook_wpm"),
        "pacing_classification": metrics.get("pacing_classification"),
        "velocity_pattern": metrics.get("velocity_pattern"),
        "curiosity_frequency_per_minute": loops.get("curiosity_frequency_per_minute"),
        "curiosity_triggers_detected": loops.get("curiosity_triggers_detected"),
        "language": trans.get("language") or cached.get("language"),
        "is_generated": trans.get("is_generated") if trans.get("is_generated") is not None else cached.get("is_generated"),
        "extractor": extractor or ("innertube_panel" if full else None),
        "source_chain": chain or ([{"layer": "L1B", "status": "success", "reason": "innertube get_panel transcript"}] if full else []),
        "hook_first_60s": hook,
        "has_transcript": bool(full),
        "transcript_error": trans.get("error"),
        "failure_reason": None,
        "diagnostic_output": None,
        "discovered_modes": [mode],
    }


def merge_row(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Merge a newly mined row, retaining useful fields from the L1B round."""
    result = dict(old)
    result.update({k: v for k, v in new.items() if v is not None and v != []})
    modes = list(old.get("discovered_modes") or [])
    for mode in new.get("discovered_modes") or []:
        if mode not in modes:
            modes.append(mode)
    result["discovered_modes"] = modes
    # Popular baseline is the requested canonical baseline when both modes hit.
    if "popular" in modes and new.get("discovered_modes") == ["latest"]:
        result["outlier_factor"] = old.get("outlier_factor", new.get("outlier_factor"))
    result["hook_strength_score"] = round(as_float(result.get("views")) * as_float(result.get("outlier_factor"), 1.0), 2)
    return result


def classify_diagnostic(video_id: str) -> tuple[str, str]:
    cmd = [
        str(YTDLP), "--skip-download", "--no-warnings", "--js-runtimes", "node",
        "--extractor-args", "youtube:player_client=android_vr",
        "--print", "%(automatic_captions.keys)s|%(subtitles.keys)s",
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        output = "\n".join(x.strip() for x in (proc.stdout, proc.stderr) if x and x.strip())
    except subprocess.TimeoutExpired:
        return "erro_tecnico", "yt-dlp timeout após 90s"
    except Exception as exc:
        return "erro_tecnico", f"{type(exc).__name__}: {exc}"

    low = output.lower()
    if "members-only" in low or "members only" in low or "level:" in low:
        return "members_only", output[-1200:]
    if re.search(r"\b(private|removed|unavailable|not available)\b", low):
        return "indisponivel", output[-1200:]
    if "na|na" in low.replace(" ", "").lower():
        return "sem_faixa", output[-1200:]
    return "erro_tecnico", output[-1200:]


async def fetch_corpus(row: dict[str, Any]) -> bool:
    """Fetch timed snippets and persist the complete raw transcript."""
    video_id = row["video_id"]
    await network_delay()
    panel = await fetch_transcript_panel(video_id, None)
    cached = transcript_cache(video_id)
    snippets = panel.get("snippets") or []
    full_text = " ".join(str(s.get("text", "")) for s in snippets).strip()
    if not full_text:
        full_text = str(cached.get("full_text") or "").strip()
    if not full_text:
        return False
    payload = {
        "video_id": video_id,
        "channel": row.get("channel"),
        "title": row.get("title"),
        "url": row.get("url"),
        "language": panel.get("language_code") or cached.get("language") or row.get("language"),
        "is_generated": panel.get("is_generated") if panel.get("success") else cached.get("is_generated", row.get("is_generated")),
        "extractor": "innertube_panel" if panel.get("success") else cached.get("extractor"),
        "source_chain": [{"layer": "L1B", "status": "success", "reason": "innertube get_panel transcript"}] if panel.get("success") else cached.get("source_chain", []),
        "duration_seconds": panel.get("duration_seconds") or cached.get("duration_seconds") or row.get("duration_seconds"),
        "total_words": len(full_text.split()),
        "full_text": full_text,
        "snippets": snippets,
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    (CORPUS_DIR / f"{video_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    row["has_transcript"] = True
    row["language"] = payload["language"]
    row["is_generated"] = payload["is_generated"]
    row["extractor"] = payload["extractor"]
    row["source_chain"] = payload["source_chain"]
    row["word_count"] = payload["total_words"]
    if not row.get("duration_seconds"):
        row["duration_seconds"] = payload.get("duration_seconds")
    return True


def duration_band(wpm: float) -> str:
    if wpm < 140:
        return "<140"
    if wpm < 160:
        return "140–160"
    if wpm < 180:
        return "160–180"
    return ">180"


def build_summary(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    by_channel: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_channel.setdefault(row.get("channel") or "N/A", []).append(row)
    summaries = []
    for channel, items in sorted(by_channel.items()):
        transcribed = [r for r in items if r.get("has_transcript") and r.get("overall_wpm") is not None]
        wpms = [as_float(r.get("overall_wpm")) for r in transcribed]
        loops = [as_float(r.get("curiosity_frequency_per_minute")) for r in transcribed if r.get("curiosity_frequency_per_minute") is not None]
        summaries.append({
            "channel": channel,
            "videos_total": len(items),
            "videos_with_transcript": sum(1 for r in items if r.get("has_transcript")),
            "wpm_samples": len(wpms),
            "mean_wpm": round(statistics.mean(wpms), 1) if wpms else None,
            "median_wpm": round(statistics.median(wpms), 1) if wpms else None,
            "wpm_range": f"{min(wpms):.1f}–{max(wpms):.1f}" if wpms else "N/A",
            "mean_loops_per_min": round(statistics.mean(loops), 2) if loops else None,
        })
    bands = {"<140": 0, "140–160": 0, "160–180": 0, ">180": 0}
    for row in rows:
        if row.get("has_transcript") and row.get("overall_wpm") is not None:
            bands[duration_band(as_float(row.get("overall_wpm")))] += 1
    return summaries, bands


def failure_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in ("members_only", "sem_faixa", "indisponivel", "erro_tecnico")}
    for row in rows:
        if not row.get("has_transcript"):
            reason = row.get("failure_reason") or "erro_tecnico"
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def first_two_sentences(text: str) -> str:
    clean = " ".join((text or "").split())
    parts = re.split(r"(?<=[.!?])\s+", clean)
    return " ".join(parts[:2])[:500]


def build_candidates(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Heuristic shortlist: strong character/topic promise, strong hook, usable pace."""
    candidates = []
    for row in rows:
        if not row.get("has_transcript") or not row.get("hook_first_60s"):
            continue
        title = str(row.get("title") or "")
        hook = str(row.get("hook_first_60s"))
        score = as_float(row.get("hook_strength_score"))
        wpm = as_float(row.get("overall_wpm"))
        character_markers = ["character", "villain", "hero", "protagonist", "psycholog", "personagem", "vilão", "herói"]
        topic_markers = ["why", "meaning", "explained", "power", "death", "ending", "lore", "secret", "truth"]
        if not any(x in title.lower() for x in character_markers + topic_markers):
            continue
        if wpm < 120 or wpm > 260:
            continue
        candidates.append({
            "channel": str(row.get("channel") or ""),
            "title": title,
            "thesis": first_two_sentences(hook),
            "why": f"gancho forte ({score:,.0f} de alcance relativo), WPM {wpm:.1f}; promessa específica e Loop/min {row.get('curiosity_frequency_per_minute')}",
            "score": score,
        })
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:10]


def write_reports(rows: list[dict[str, Any]], summaries: list[dict[str, Any]], bands: dict[str, int], timestamp: str,
                  channel_errors: list[dict[str, str]], corpus_count: int) -> tuple[Path, Path]:
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = HOOKS_DIR / f"CATALOGO_COMPLETO_{timestamp}.json"
    md_path = HOOKS_DIR / f"CATALOGO_COMPLETO_{timestamp}.md"
    valid = [r for r in rows if r.get("has_transcript") and r.get("overall_wpm") is not None]
    valid.sort(key=lambda r: (as_float(r.get("hook_strength_score")), as_float(r.get("views"))), reverse=True)
    wpms = [as_float(r.get("overall_wpm")) for r in valid]
    failures = failure_counts(rows)
    coverage = (sum(1 for r in rows if r.get("has_transcript")) / len(rows) * 100) if rows else 0.0
    ranked_channels = sorted([s for s in summaries if s.get("mean_wpm") is not None], key=lambda s: s["mean_wpm"])
    candidates = build_candidates(rows)

    payload = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "timestamp": timestamp,
        "scope": {"channels": len(summaries), "videos_scanned": len(rows), "videos_with_transcript": sum(1 for r in rows if r.get("has_transcript")), "coverage_percent": round(coverage, 2), "corpus_files": corpus_count},
        "summary_by_channel": summaries,
        "wpm_distribution": bands,
        "wpm_overall": {"mean": round(statistics.mean(wpms), 1) if wpms else None, "median": round(statistics.median(wpms), 1) if wpms else None, "min": min(wpms) if wpms else None, "max": max(wpms) if wpms else None},
        "failure_counts": failures,
        "channel_errors": channel_errors,
        "top_hooks": valid[:25],
        "roteiro_01_candidates": candidates,
        "videos": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# CATÁLOGO COMPLETO — transcrições, hooks e WPM (24 canais)",
        "",
        f"- **Coleta**: {payload['generated_at']}",
        f"- **Cobertura**: {len(summaries)}/24 canais; {len(rows)} vídeos varridos; {sum(1 for r in rows if r.get('has_transcript'))} com transcrição ({coverage:.1f}%)",
        f"- **Corpus bruto**: `{CORPUS_DIR}` ({corpus_count} arquivos)",
        f"- **WPM geral**: média {payload['wpm_overall']['mean']}; mediana {payload['wpm_overall']['median']}; faixa {payload['wpm_overall']['min']}–{payload['wpm_overall']['max']}",
        "",
        "## Cobertura e WPM por canal",
        "",
        "| Canal | Varridos | Transcritos | WPM médio | Mediana | Faixa | Loops/min |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in summaries:
        lines.append(f"| {s['channel']} | {s['videos_total']} | {s['videos_with_transcript']} | {s['mean_wpm'] or 'N/A'} | {s['median_wpm'] or 'N/A'} | {s['wpm_range']} | {s['mean_loops_per_min'] if s['mean_loops_per_min'] is not None else 'N/A'} |")
    lines += ["", "## Distribuição de WPM", "", "| Faixa | Vídeos |", "|---|---:|"]
    lines += [f"| {label} | {count} |" for label, count in bands.items()]
    lines += ["", "## Canais mais rápidos e mais lentos", ""]
    lines += ["### Mais rápidos", "", "| Canal | WPM médio |", "|---|---:|"]
    lines += [f"| {s['channel']} | {s['mean_wpm']} |" for s in ranked_channels[:5]]
    lines += ["", "### Mais lentos", "", "| Canal | WPM médio |", "|---|---:|"]
    lines += [f"| {s['channel']} | {s['mean_wpm']} |" for s in list(reversed(ranked_channels))[:5]]
    lines += ["", "## Falhas por motivo", "", "| Motivo | Vídeos |", "|---|---:|"]
    lines += [f"| {key} | {value} |" for key, value in failures.items()]
    members = [r for r in rows if r.get("failure_reason") == "members_only"]
    lines += ["", "## Vídeos members-only", ""]
    if members:
        lines += [f"- **{r['channel']}** — [{r['title']}]({r.get('url')}) (`{r['video_id']}`)" for r in members]
    else:
        lines.append("- Nenhum.")
    lines += ["", "## Top 25 hooks (views × outlier_factor)", ""]
    for i, r in enumerate(valid[:25], 1):
        lines += [
            f"### {i}. {r.get('title')}",
            f"- **Canal**: {r.get('channel')}",
            f"- **Views**: {int(r.get('views') or 0):,} ({as_float(r.get('outlier_factor')):.2f}x)",
            f"- **WPM**: geral {r.get('overall_wpm')}; gancho {r.get('hook_wpm')}",
            f"- **Hook**: > {first_two_sentences(r.get('hook_first_60s', ''))}",
            "",
        ]
    lines += ["## Candidatos naturais para o Roteiro 01", ""]
    for i, c in enumerate(candidates, 1):
        lines += [f"### {i}. {c['title']}", f"- **Canal**: {c['channel']}", f"- **Tese/hook**: {c['thesis']}", f"- **Por que**: {c['why']}", ""]
    if channel_errors:
        lines += ["## Erros de canal", ""] + [f"- {e['channel']}: {e['reason']}" for e in channel_errors]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def append_vault_section(note: Path, marker: str, section: str) -> None:
    text = note.read_text(encoding="utf-8") if note.exists() else ""
    if marker not in text:
        with note.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n\n" + section.strip() + "\n")


async def main() -> int:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    channels = discover_channels()
    if len(channels) != 24:
        raise RuntimeError(f"Expected 24 dossiers, found {len(channels)}")
    old = load_old_rows()
    rows: dict[str, dict[str, Any]] = {vid: dict(row) for vid, row in old.items()}
    channel_errors: list[dict[str, str]] = []
    corpus_count = len(list(CORPUS_DIR.glob("*.json"))) if CORPUS_DIR.exists() else 0
    print(f"[START] 24 canais; intervalo={MIN_INTERVAL:.2f}s; reused={len(old)}", flush=True)

    for index, channel in enumerate(channels, 1):
        channel_name = channel["channel"]
        before = len(rows)
        for mode in ("popular", "latest"):
            try:
                print(f"[CANAL {index}/24] {channel_name} | modo={mode} | max=25", flush=True)
                mined = await deep_mine_channel(
                    channel["url"], mode=mode, max_videos=25,
                    download_thumbnails=False, fetch_transcripts=True,
                    lang_preference=None,
                )
                if not mined.get("success"):
                    raise RuntimeError(str(mined.get("error") or "deep_mine_channel failure"))
                actual_channel = str(mined.get("channel_title") or channel_name)
                for video in mined.get("videos", []):
                    vid = str(video.get("video_id") or "")
                    if not vid:
                        continue
                    new = row_from_mined(actual_channel, video, mode)
                    rows[vid] = merge_row(rows.get(vid, {}), new)
                ok = sum(1 for v in mined.get("videos", []) if (v.get("transcript") or {}).get("full_script"))
                print(f"[CANAL {index}/24] {channel_name} | modo={mode} | vídeos={len(mined.get('videos', []))} | ok={ok}", flush=True)
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                print(f"[ERRO] {channel_name} | {mode} | {reason}", flush=True)
                channel_errors.append({"channel": channel_name, "mode": mode, "reason": reason})
        print(f"[PROGRESSO] canal {index}/24 | vídeos únicos={len(rows)} (+{len(rows)-before})", flush=True)

    # Diagnose every transcript failure exactly once, sequentially.
    missing = [r for r in rows.values() if not r.get("has_transcript")]
    print(f"[DIAGNÓSTICO] {len(missing)} falhas; executando yt-dlp sequencial", flush=True)
    for i, row in enumerate(missing, 1):
        reason, output = classify_diagnostic(row["video_id"])
        row["failure_reason"] = reason
        row["diagnostic_output"] = output
        print(f"[DIAG {i}/{len(missing)}] {row['video_id']} -> {reason}", flush=True)

    # Build the complete raw corpus.  This is separate from the mined JSON so
    # the latter never carries the full script text.
    transcribed = [r for r in rows.values() if r.get("has_transcript")]
    print(f"[CORPUS] buscando texto + snippets para {len(transcribed)} transcrições", flush=True)
    for i, row in enumerate(transcribed, 1):
        target = CORPUS_DIR / f"{row['video_id']}.json"
        if not target.exists():
            await fetch_corpus(row)
        else:
            try:
                payload = json.loads(target.read_text(encoding="utf-8"))
                row["has_transcript"] = True
                row["word_count"] = row.get("word_count") or payload.get("total_words")
                row["language"] = row.get("language") or payload.get("language")
                row["is_generated"] = row.get("is_generated") if row.get("is_generated") is not None else payload.get("is_generated")
            except Exception:
                await fetch_corpus(row)
        if i % 25 == 0 or i == len(transcribed):
            print(f"[CORPUS] {i}/{len(transcribed)}", flush=True)
    corpus_count = len(list(CORPUS_DIR.glob("*.json")))

    all_rows = list(rows.values())
    summaries, bands = build_summary(all_rows)
    json_path, md_path = write_reports(all_rows, summaries, bands, timestamp, channel_errors, corpus_count)
    valid = [r for r in all_rows if r.get("has_transcript") and r.get("overall_wpm") is not None]
    wpms = [as_float(r.get("overall_wpm")) for r in valid]
    general = f"{statistics.mean(wpms):.1f}" if wpms else "N/A"
    coverage = (len(valid) / len(all_rows) * 100) if all_rows else 0.0
    ranges = "; ".join(f"{s['channel']}: {s['wpm_range']} WPM" for s in summaries if s["wpm_range"] != "N/A")
    section = f"""<!-- CATALOGO_COMPLETO_L1B -->
## Catálogo completo — corpus L1B

- **Cobertura**: {len(all_rows)} vídeos varridos em {len(summaries)}/24 canais; {len(valid)} com transcrição ({coverage:.1f}%).
- **WPM geral do conjunto**: {general} WPM.
- **Faixas por canal**: {ranges}.
- **Corpus bruto**: `{CORPUS_DIR}` ({corpus_count} transcrições completas com texto + snippets).
- **Relatório**: `{md_path}`.
"""
    append_vault_section(VAULT_DIR / "04_CANAIS_REFERENCIA.md", "<!-- CATALOGO_COMPLETO_L1B -->", section)
    append_vault_section(VAULT_DIR / "_INDEX_PESQUISA.md", "<!-- CATALOGO_COMPLETO_L1B -->", section)

    print(f"DONE JSON={json_path}", flush=True)
    print(f"DONE MD={md_path}", flush=True)
    print(f"COVERAGE channels={len(summaries)}/24 videos={len(all_rows)} transcripts={len(valid)} ({coverage:.1f}%)", flush=True)
    print(f"FAILURES {failure_counts(all_rows)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
