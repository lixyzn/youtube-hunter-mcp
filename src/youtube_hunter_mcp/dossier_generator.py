"""
Markdown Intelligence Dossier Generator for YouTube Hunter MCP.
Builds Obsidian-compatible, publication-ready research reports with embedded thumbnails,
OCR analysis, side-by-side hook breakdowns, and retention pacing benchmarks.
Supports both channel mining and niche outlier runs.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .pacing_analyzer import analyze_narrative_pacing
from .thumbnail_ocr import extract_thumbnail_text
from .thumbnails import BASE_DOWNLOAD_DIR
from .utils import sanitize_filename

DOSSIERS_DIR = BASE_DOWNLOAD_DIR.parent / "dossiers"
DOSSIERS_DIR.mkdir(parents=True, exist_ok=True)


def generate_channel_dossier(
    mine_result: Dict[str, Any],
    output_filename: Optional[str] = None,
    kind: str = "channel_mine",
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Generate an in-depth Markdown dossier from a deep_mine_channel or niche_outliers result.

    Args:
        mine_result: The dictionary returned by deep_mine_channel or find_niche_outliers.
        output_filename: Optional custom filename for the markdown file.
        kind: 'channel_mine' or 'niche_outliers'.

    Returns:
        Dict with local markdown file path, URI, and summary.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    file_ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    if kind == "niche_outliers":
        return _generate_niche_outlier_dossier(mine_result, output_filename, timestamp, file_ts)
    else:
        return _generate_channel_mine_dossier(mine_result, output_filename, timestamp, file_ts)


def _generate_channel_mine_dossier(
    mine_result: Dict[str, Any],
    output_filename: Optional[str],
    timestamp: str,
    file_ts: str,
) -> Dict[str, Any]:
    channel_title = (
        mine_result.get("channel_name")
        or mine_result.get("channel_title")
        or "Channel"
    )
    channel_url = mine_result.get("channel_url", "")
    stats = mine_result.get("stats") or mine_result.get("statistics") or {}
    videos = mine_result.get("videos", [])

    safe_title = sanitize_filename(channel_title, 40)
    out_name = output_filename or f"DOSSIER_{safe_title}_{file_ts}.md"
    file_path = DOSSIERS_DIR / out_name

    md_lines: List[str] = []

    # Title & Header
    md_lines.append(f"# 🦅 YouTube Intelligence Dossier: {channel_title}")
    md_lines.append(f"> **Generated**: {timestamp} | **Channel**: [{channel_title}]({channel_url})")
    md_lines.append("")

    # Dashboard Metrics
    avg_views = stats.get("average_views") or stats.get("mean_views") or 0
    median_views = stats.get("median_views", 0)
    max_views = stats.get("max_views", 0)
    outliers_found = stats.get("top_outliers_count") or stats.get("outliers_found") or 0

    md_lines.append("## 📊 1. Channel Performance Baseline")
    md_lines.append(f"- **Total Videos Scrutinized**: `{len(videos)}`")
    md_lines.append(f"- **Channel Average Views**: `{avg_views:,}` views")
    md_lines.append(f"- **Median Views**: `{median_views:,}` views")
    md_lines.append(f"- **Viral Ceiling (Max Views)**: `{max_views:,}` views")
    md_lines.append(f"- **Outliers Detected**: `{outliers_found}` videos exceeding baseline")
    md_lines.append("")

    # Top Outliers Table
    md_lines.append("## 🔥 2. Viral Outliers Table (Furaram a Bolha)")
    md_lines.append("| Rank | Title | Views | Multiplier | Tag | Link |")
    md_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

    for i, v in enumerate(videos[:10], 1):
        views_display = (
            v.get("views_raw")
            or v.get("views_text")
            or (f"{v.get('views'):,}" if v.get("views") else "N/A")
        )
        multiplier = v.get("outlier_factor", "1.0x")
        if isinstance(multiplier, (int, float)):
            multiplier = f"{multiplier}x"
        tag = v.get("outlier_class") or v.get("performance_tag") or "Baseline"
        url = v.get("url", "")
        title = v.get("title", "")
        md_lines.append(
            f"| #{i} | **{title}** | {views_display} | "
            f"`{multiplier}` | {tag} | [Assistir]({url}) |"
        )
    md_lines.append("")

    # Thumbnail Visual & OCR Anatomy
    md_lines.append("## 🖼️ 3. Thumbnail & Visual Anatomy (Top Winners)")
    md_lines.append("Abaixo estão as capas de maior conversão do canal baixadas em alta resolução:")
    md_lines.append("")

    for i, v in enumerate(videos[:5], 1):
        thumb_path = (
            v.get("thumbnail_local_path")
            or (v.get("enrichment", {}).get("thumbnail", {}).get("local_path"))
        )
        views_display = v.get("views_raw") or v.get("views_text") or str(v.get("views", ""))
        factor_display = v.get("outlier_factor", "")
        if isinstance(factor_display, (int, float)):
            factor_display = f"{factor_display}x"

        md_lines.append(f"### #{i} — {v.get('title', '')}")
        md_lines.append(f"- **Desempenho**: `{views_display} views` ({factor_display} acima da média)")
        if thumb_path and Path(thumb_path).exists():
            thumb_uri = Path(thumb_path).resolve().as_uri()
            md_lines.append(f"![{v.get('title', '')}]({thumb_uri})")
            ocr = extract_thumbnail_text(str(thumb_path))
            if ocr.get("has_text"):
                md_lines.append(f"- **Texto na Thumbnail (OCR)**: `{ocr.get('full_text')}`")
                md_lines.append(
                    f"- **Estilo Tipográfico**: `ALL CAPS: {ocr.get('is_all_caps')}` | `Contém Números: {ocr.get('has_numbers')}`"
                )
            else:
                md_lines.append("- **Texto na Thumbnail**: *(Nenhum texto detectado — foco 100% visual/expressão facial)*")
        md_lines.append("")

    # The Hook Vault & Pacing Breakdown
    md_lines.append("## 🪝 4. The Hook Vault (Primeiros 60 Segundos)")
    md_lines.append("Desconstrução do gancho narrativo dos vídeos com maior retenção do canal:")
    md_lines.append("")

    hooks_written = 0
    for v in videos:
        trans = v.get("transcript", {})
        hook = trans.get("hook_first_60s") or trans.get("hook")
        if hook:
            hooks_written += 1
            full_script = trans.get("full_script") or trans.get("full_text", "")
            duration = trans.get("duration_seconds") or 300
            pacing = analyze_narrative_pacing(full_script, duration_seconds=duration, hook_text=hook)

            md_lines.append(f"### Hook #{hooks_written}: *{v.get('title', '')}*")
            md_lines.append(f"> \"{hook}\"")
            md_lines.append("")
            if pacing.get("success"):
                p_metrics = pacing["metrics"]
                p_loops = pacing["engagement_loops"]
                md_lines.append(
                    f"- **Velocidade de Fala (WPM)**: `{p_metrics.get('overall_wpm')} WPM` ({p_metrics.get('pacing_classification')})"
                )
                md_lines.append(
                    f"- **Ritmo no Gancho**: `{p_metrics.get('hook_wpm')} WPM` (`{p_metrics.get('velocity_pattern')}`)"
                )
                md_lines.append(
                    f"- **Gatilhos de Curiosidade**: `{p_loops.get('curiosity_triggers_detected')}` loops abertos ({p_loops.get('curiosity_frequency_per_minute')}/min)"
                )
            md_lines.append("")
            if hooks_written >= 3:
                break

    # Strategic Narrative Blueprint
    md_lines.append("## 🎯 5. Fórmula Narrativa Recomendada para o seu Próximo Vídeo")
    md_lines.append("Com base nos dados minerados desse concorrente, siga esta estrutura para o seu conteúdo em inglês:")
    md_lines.append("")
    md_lines.append("```markdown")
    md_lines.append("1. [00:00 - 00:15] PATTERN INTERRUPT & THE STAKE:")
    md_lines.append("   - Comece direto no ápice do problema ou promessa.")
    md_lines.append("   - Não fale 'Hey guys, welcome back'. Abra com uma afirmação controversa ou pergunta aberta.")
    md_lines.append("")
    md_lines.append("2. [00:15 - 00:45] THE VISUAL PROOF & OPEN LOOP:")
    md_lines.append("   - Mostre o resultado rápido (prova de tela, métrica ou objeto físico).")
    md_lines.append("   - Crie o loop: 'Mas quase todo mundo erra neste detalhe específico...'")
    md_lines.append("")
    md_lines.append("3. [00:45 - 01:00] THE ROADMAP:")
    md_lines.append("   - 'Neste vídeo, eu vou te mostrar exatamente o passo a passo de...'")
    md_lines.append("   - Mantenha o ritmo entre 155 - 175 WPM para manter a retenção americana.")
    md_lines.append("```")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("*Gerado automaticamente pelo YouTube Hunter MCP no Disco D.*")

    content = "\n".join(md_lines)
    file_path.write_text(content, encoding="utf-8")

    return {
        "success": True,
        "dossier_title": f"Dossier: {channel_title}",
        "local_path": str(file_path.resolve()),
        "file_uri": file_path.resolve().as_uri(),
        "total_lines": len(md_lines),
    }


def _generate_niche_outlier_dossier(
    mine_result: Dict[str, Any],
    output_filename: Optional[str],
    timestamp: str,
    file_ts: str,
) -> Dict[str, Any]:
    keyword = mine_result.get("keyword") or mine_result.get("query") or "Niche"
    stats = mine_result.get("stats", {})
    videos = mine_result.get("videos") or mine_result.get("top_outliers", [])

    safe_keyword = sanitize_filename(keyword, 40)
    out_name = output_filename or f"DOSSIER_OUTLIERS_{safe_keyword}_{file_ts}.md"
    file_path = DOSSIERS_DIR / out_name

    md_lines: List[str] = []

    # Title & Header
    md_lines.append(f"# 🦅 YouTube Niche Outliers Dossier: {keyword}")
    md_lines.append(f"> **Generated**: {timestamp} | **Topic / Query**: `{keyword}`")
    md_lines.append("")

    # Dashboard Metrics
    md_lines.append("## 📊 1. Niche Performance & Outlier Stats")
    md_lines.append(f"- **Total Results Analyzed**: `{stats.get('total_analyzed', len(videos))}`")
    md_lines.append(f"- **Qualified Viral Outliers**: `{stats.get('qualified_outliers', len(videos))}`")
    md_lines.append(f"- **Subscriber Cap**: `{stats.get('subscriber_cap', 'N/A')}`")
    md_lines.append(f"- **Median Outlier Multiplier**: `{stats.get('median_outlier_factor', 0.0)}x`")
    md_lines.append(f"- **Peak Multiplier (Max)**: `{stats.get('max_outlier_factor', 0.0)}x`")
    md_lines.append("")

    # Top Outliers Table
    md_lines.append("## 🔥 2. Viral Outliers Table (Small Channels Breaking Out)")
    md_lines.append("| Rank | Title | Channel | Views | Subs | Multiplier | Link |")
    md_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for i, v in enumerate(videos[:15], 1):
        views_display = v.get("views_text") or (f"{v.get('views'):,}" if v.get("views") else "N/A")
        subs_display = v.get("subscribers_text") or (f"{v.get('subscribers'):,}" if v.get("subscribers") else "N/A")
        multiplier = v.get("outlier_factor", "1.0x")
        if isinstance(multiplier, (int, float)):
            multiplier = f"{multiplier}x"
        title = v.get("title", "")
        ch_name = v.get("channel_name", "")
        url = v.get("url", "")
        md_lines.append(
            f"| #{i} | **{title}** | {ch_name} | {views_display} | "
            f"{subs_display} | `{multiplier}` | [Assistir]({url}) |"
        )
    md_lines.append("")

    # Visual & OCR Anatomy
    md_lines.append("## 🖼️ 3. Thumbnail & Visual Anatomy (Top Viral Winners)")
    md_lines.append("")

    for i, v in enumerate(videos[:5], 1):
        thumb_path = v.get("thumbnail_local_path")
        views_display = v.get("views_text") or str(v.get("views", ""))
        factor_display = v.get("outlier_factor", "")
        if isinstance(factor_display, (int, float)):
            factor_display = f"{factor_display}x"

        md_lines.append(f"### #{i} — {v.get('title', '')}")
        md_lines.append(f"- **Canal**: `{v.get('channel_name', '')}` ({v.get('subscribers_text', '')})")
        md_lines.append(f"- **Desempenho**: `{views_display} views` ({factor_display} acima da base de inscritos)")
        if thumb_path and Path(thumb_path).exists():
            thumb_uri = Path(thumb_path).resolve().as_uri()
            md_lines.append(f"![{v.get('title', '')}]({thumb_uri})")
            ocr = extract_thumbnail_text(str(thumb_path))
            if ocr.get("has_text"):
                md_lines.append(f"- **Texto na Thumbnail (OCR)**: `{ocr.get('full_text')}`")
                md_lines.append(
                    f"- **Estilo Tipográfico**: `ALL CAPS: {ocr.get('is_all_caps')}` | `Contém Números: {ocr.get('has_numbers')}`"
                )
            else:
                md_lines.append("- **Texto na Thumbnail**: *(Nenhum texto detectado — foco 100% visual/expressão facial)*")
        md_lines.append("")

    # Hooks
    md_lines.append("## 🪝 4. Opening Hooks Vault")
    hooks_written = 0
    for v in videos:
        trans = v.get("transcript", {})
        hook = trans.get("hook_first_60s") or trans.get("hook")
        if hook:
            hooks_written += 1
            md_lines.append(f"### Hook #{hooks_written}: *{v.get('title', '')}*")
            md_lines.append(f"> \"{hook}\"")
            md_lines.append("")
            if hooks_written >= 3:
                break

    md_lines.append("---")
    md_lines.append("*Gerado automaticamente pelo YouTube Hunter MCP no Disco D.*")

    content = "\n".join(md_lines)
    file_path.write_text(content, encoding="utf-8")

    return {
        "success": True,
        "dossier_title": f"Dossier: {keyword}",
        "local_path": str(file_path.resolve()),
        "file_uri": file_path.resolve().as_uri(),
        "total_lines": len(md_lines),
    }
