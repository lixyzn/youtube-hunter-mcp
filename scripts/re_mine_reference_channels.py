"""Re-mine the 24 reference channels with transcript/pacing data.

This script intentionally lives outside the MCP package: it uses the internal
Python API and writes research artifacts without changing MCP source code.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import shutil
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("YT_HUNTER_TRANSCRIPT_MIN_INTERVAL_MS", "1500")

from youtube_hunter_mcp.channel_miner import deep_mine_channel  # noqa: E402
from youtube_hunter_mcp.dossier_generator import generate_channel_dossier  # noqa: E402
from youtube_hunter_mcp.pacing_analyzer import analyze_narrative_pacing  # noqa: E402
from youtube_hunter_mcp.transcript import get_video_transcript_async  # noqa: E402
from youtube_hunter_mcp.utils import sanitize_filename  # noqa: E402

RESEARCH_DIR = Path(r"D:\pesquisa de mercado anime")
DOSSIERS_DIR = RESEARCH_DIR / "03_canais_referencia"
HOOKS_DIR = RESEARCH_DIR / "04_scripts_e_hooks"
VAULT_DIR = Path(r"D:\cerebro\10_Pesquisa")
VAULT_DOSSIERS_DIR = VAULT_DIR / "Canais Referencia"
HEADER_RE = re.compile(r"\*\*Channel\*\*:\s*\[([^]]+)\]\((https?://[^)]+)\)")


def discover_channels() -> list[dict[str, str]]:
    channels: list[dict[str, str]] = []
    for dossier in sorted(DOSSIERS_DIR.glob("DOSSIER_*.md")):
        if dossier.name.endswith("_TRANSCRIT.md"):
            continue
        match = HEADER_RE.search(dossier.read_text(encoding="utf-8", errors="replace"))
        if match:
            channels.append({"channel": match.group(1).strip(), "url": match.group(2).strip()})
    return channels


def seconds_from_duration(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    parts = value.strip().split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


def fmt_views(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{int(value):,}"
    return str(value or "N/A")


def fmt_range(values: list[float]) -> str:
    if not values:
        return "N/A"
    lo, hi = min(values), max(values)
    if lo == hi:
        return f"{lo:.0f}s"
    return f"{lo:.0f}–{hi:.0f}s"


def duration_band(wpm: float) -> str:
    if wpm < 140:
        return "<140"
    if wpm <= 160:
        return "140–160"
    if wpm <= 180:
        return "160–180"
    return ">180"


async def enrich_extractor(video_id: str) -> tuple[str | None, list[dict[str, Any]]]:
    """Read provenance from the transcript cache/API without changing the MCP."""
    try:
        result = await get_video_transcript_async(video_id, include_snippets=False)
        return result.get("extractor"), result.get("source_chain", [])
    except Exception:
        return None, []


async def mine_one(channel: dict[str, str], timestamp: str) -> dict[str, Any]:
    print(f"[START] {channel['channel']} — {channel['url']}", flush=True)
    mined = await deep_mine_channel(
        channel["url"],
        mode="popular",
        max_videos=6,
        download_thumbnails=False,
        fetch_transcripts=True,
    )
    if not mined.get("success"):
        raise RuntimeError(str(mined.get("error") or "deep_mine_channel returned failure"))

    channel_title = str(mined.get("channel_title") or channel["channel"])
    safe = sanitize_filename(channel_title, 40)
    dossier_name = f"DOSSIER_{safe}_{timestamp}_TRANSCRIT.md"
    generated = generate_channel_dossier(mined, output_filename=dossier_name)
    generated_path = Path(generated["local_path"])
    final_dossier = DOSSIERS_DIR / dossier_name
    final_dossier.write_text(generated_path.read_text(encoding="utf-8"), encoding="utf-8")
    # The generator has its own default directory; do not leave a duplicate there.
    generated_path.unlink(missing_ok=True)

    rows: list[dict[str, Any]] = []
    for video in mined.get("videos", []):
        trans = video.get("transcript") or {}
        full_script = trans.get("full_script") or ""
        hook = trans.get("hook_first_60s") or ""
        duration = trans.get("duration_seconds")
        if not duration:
            duration = seconds_from_duration(video.get("duration"))
        has_transcript = bool(full_script and hook)
        metrics: dict[str, Any] = {}
        loops: dict[str, Any] = {}
        if has_transcript and duration and duration > 0:
            pacing = analyze_narrative_pacing(full_script, duration_seconds=duration, hook_text=hook)
            if pacing.get("success"):
                metrics = pacing.get("metrics", {})
                loops = pacing.get("engagement_loops", {})

        extractor, source_chain = (None, [])
        if has_transcript:
            extractor, source_chain = await enrich_extractor(str(video.get("video_id")))
        views_num = video.get("views")
        factor = video.get("outlier_score")
        try:
            factor_num = float(factor)
        except (TypeError, ValueError):
            factor_num = 1.0
        views_num = int(views_num or 0)
        row = {
            "channel": channel_title,
            "title": video.get("title", ""),
            "video_id": video.get("video_id", ""),
            "views": views_num,
            "views_raw": video.get("views_raw", ""),
            "outlier_factor": factor_num,
            "duration_seconds": duration,
            "word_count": trans.get("word_count") or metrics.get("total_words") or 0,
            "overall_wpm": metrics.get("overall_wpm"),
            "hook_wpm": metrics.get("hook_wpm"),
            "pacing_classification": metrics.get("pacing_classification"),
            "velocity_pattern": metrics.get("velocity_pattern"),
            "curiosity_frequency_per_minute": loops.get("curiosity_frequency_per_minute"),
            "curiosity_triggers_detected": loops.get("curiosity_triggers_detected"),
            "language": trans.get("language"),
            "extractor": extractor or ("transcript" if has_transcript else None),
            "source_chain": source_chain,
            "hook_first_60s": hook,
            "has_transcript": has_transcript,
            "transcript_error": trans.get("error"),
        }
        # A useful deterministic hook strength: reach relative to channel mean,
        # weighted by absolute views. Ties are resolved by views.
        row["hook_strength_score"] = round(views_num * factor_num, 2)
        rows.append(row)

    return {
        "channel": channel_title,
        "url": channel["url"],
        "dossier_path": str(final_dossier),
        "rows": rows,
    }


def build_channel_summary(channel_data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for channel in channel_data:
        rows = channel["rows"]
        transcribed = [r for r in rows if r["has_transcript"]]
        wpms = [float(r["overall_wpm"]) for r in transcribed if r["overall_wpm"] is not None]
        loop_rates = [float(r["curiosity_frequency_per_minute"]) for r in transcribed if r["curiosity_frequency_per_minute"] is not None]
        durations = [float(r["duration_seconds"]) for r in transcribed if r["duration_seconds"]]
        summaries.append({
            "channel": channel["channel"],
            "videos_total": len(rows),
            "videos_with_transcript": len(transcribed),
            "mean_wpm": round(statistics.mean(wpms), 1) if wpms else None,
            "wpm_range": f"{min(wpms):.1f}–{max(wpms):.1f}" if wpms else "N/A",
            "mean_loops_per_min": round(statistics.mean(loop_rates), 2) if loop_rates else None,
            "duration_range": fmt_range(durations),
        })
    return summaries


def write_hooks_report(summaries: list[dict[str, Any]], rows: list[dict[str, Any]], timestamp: str) -> tuple[Path, Path]:
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = HOOKS_DIR / f"HOOKS_WPM_{timestamp}.md"
    json_path = HOOKS_DIR / f"HOOKS_WPM_{timestamp}.json"

    valid = [r for r in rows if r["has_transcript"] and r["hook_first_60s"] and r["overall_wpm"] is not None]
    valid.sort(key=lambda r: (r["hook_strength_score"], r["views"]), reverse=True)
    all_wpms = [float(r["overall_wpm"]) for r in valid]
    bands = {"<140": 0, "140–160": 0, "160–180": 0, ">180": 0}
    for wpm in all_wpms:
        bands[duration_band(wpm)] += 1

    lines = [
        "# HOOKS + WPM — 24 canais de referência (transcrição L1B)",
        "",
        f"- **Coleta**: {dt.datetime.now().isoformat(timespec='seconds')}",
        f"- **Vídeos com transcrição**: {len(valid)} de {len(rows)}",
        f"- **WPM geral**: {statistics.mean(all_wpms):.1f}" if all_wpms else "- **WPM geral**: N/A",
        f"- **Mediana WPM**: {statistics.median(all_wpms):.1f}" if all_wpms else "- **Mediana WPM**: N/A",
        "",
        "## Panorama por canal",
        "",
        "| Canal | Vídeos c/ transcrição | WPM médio | Faixa WPM | Loops/min médio | Duração |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for s in summaries:
        lines.append(
            f"| {s['channel']} | {s['videos_with_transcript']}/{s['videos_total']} | "
            f"{s['mean_wpm'] if s['mean_wpm'] is not None else 'N/A'} | {s['wpm_range']} | "
            f"{s['mean_loops_per_min'] if s['mean_loops_per_min'] is not None else 'N/A'} | {s['duration_range']} |"
        )
    lines += [
        "",
        "## Distribuição de WPM",
        "",
        "| Faixa | Vídeos |",
        "|---|---:|",
    ]
    for label, count in bands.items():
        lines.append(f"| {label} | {count} |")
    lines += [
        "",
        "## 15 hooks mais fortes",
        "",
        "Ordenação por `views × multiplicador` (alcance relativo ao baseline do canal).",
        "",
    ]
    for i, r in enumerate(valid[:15], 1):
        hook = " ".join(r["hook_first_60s"].split())
        lines += [
            f"### {i}. {r['title']}",
            f"- **Canal**: {r['channel']}",
            f"- **Views**: {fmt_views(r['views'])} ({r['outlier_factor']:.2f}x)",
            f"- **WPM do gancho**: {r['hook_wpm']} | **WPM geral**: {r['overall_wpm']}",
            f"- **Hook (verbatim)**: > {hook}",
            "",
        ]

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps({
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "timestamp": timestamp,
            "summary_by_channel": summaries,
            "wpm_distribution": bands,
            "videos": rows,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return md_path, json_path


def append_vault_section(note: Path, section: str) -> None:
    note.parent.mkdir(parents=True, exist_ok=True)
    text = note.read_text(encoding="utf-8") if note.exists() else ""
    marker = "<!-- RE-MINERACAO_L1B -->"
    if marker not in text:
        with note.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write("\n\n" + section.strip() + "\n")


def update_vault(channel_data: list[dict[str, Any]], summaries: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    VAULT_DOSSIERS_DIR.mkdir(parents=True, exist_ok=True)
    for channel in channel_data:
        source = Path(channel["dossier_path"])
        shutil.copy2(source, VAULT_DOSSIERS_DIR / source.name)

    valid = [r for r in rows if r["has_transcript"] and r["overall_wpm"] is not None]
    wpms = [float(r["overall_wpm"]) for r in valid]
    general = f"{statistics.mean(wpms):.1f}" if wpms else "N/A"
    channel_ranges = "; ".join(
        f"{s['channel']}: {s['wpm_range']} WPM" for s in summaries if s["wpm_range"] != "N/A"
    )
    section = f"""<!-- RE-MINERACAO_L1B -->
## Camada L1B — transcrição, WPM e hooks

- **Cobertura**: {len(valid)} vídeos com transcrição em {len(summaries)} canais re-minerados (6 vídeos populares por canal).
- **WPM geral do conjunto**: {general} WPM.
- **Faixas por canal**: {channel_ranges}.
- **Dossiês com transcrição**: [[Canais Referencia]] (24 dossiês `_TRANSCRIT.md`).
"""
    append_vault_section(VAULT_DIR / "_INDEX_PESQUISA.md", section)
    append_vault_section(VAULT_DIR / "04_CANAIS_REFERENCIA.md", section)


async def main() -> int:
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    channels = discover_channels()
    if len(channels) != 24:
        raise RuntimeError(f"Expected 24 reference dossiers, found {len(channels)}")
    print(f"Discovered {len(channels)} channels. Rate interval={os.environ.get('YT_HUNTER_TRANSCRIPT_MIN_INTERVAL_MS')}ms", flush=True)

    channel_data: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, channel in enumerate(channels, 1):
        try:
            result = await mine_one(channel, timestamp)
            channel_data.append(result)
            ok = sum(1 for r in result["rows"] if r["has_transcript"])
            print(f"[OK {index}/24] {result['channel']}: {ok}/{len(result['rows'])} transcripts", flush=True)
        except Exception as exc:
            failures.append({"channel": channel["channel"], "url": channel["url"], "reason": f"{type(exc).__name__}: {exc}"})
            print(f"[FAIL {index}/24] {channel['channel']}: {type(exc).__name__}: {exc}", flush=True)

    all_rows = [r for channel in channel_data for r in channel["rows"]]
    summaries = build_channel_summary(channel_data)
    md_path, json_path = write_hooks_report(summaries, all_rows, timestamp)
    update_vault(channel_data, summaries, all_rows)

    # Persist run-level failure metadata alongside the raw JSON for auditability.
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["channel_failures"] = failures
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"REPORTS: {md_path} | {json_path}", flush=True)
    print(f"CHANNELS OK: {len(channel_data)}; FAILED: {len(failures)}; TRANSCRIPTS: {sum(1 for r in all_rows if r['has_transcript'])}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
