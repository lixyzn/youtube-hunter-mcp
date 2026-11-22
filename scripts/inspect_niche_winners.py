#!/usr/bin/env python3
"""
Inspect Niche Winners Pipeline — YouTube Hunter MCP

Workflow:
1. Searches YouTube by keyword/niche (bypassing brittle channel handles).
2. Identifies top winning videos (by views or outlier factor).
3. Deeply inspects top N videos individually:
   - Metadata (channel, views, published date, category)
   - Hidden Creator Tags & Hashtags
   - Full Description
   - Audience Comments (pains, desires, questions, sentiment)
   - High-Res Thumbnail download
   - Thumbnail OCR text & typography
   - Packaging Dissection (Title vs Cover synergy, redundancy score, CTR verdict)
   - Opening Hook (first 60s) & Retention Pacing (WPM, curiosity loops)
4. Compiles a Markdown Dossier into `dossiers/` and structured JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from youtube_hunter_mcp.browser import scrape_video_page, search_youtube
from youtube_hunter_mcp.pacing_analyzer import analyze_narrative_pacing
from youtube_hunter_mcp.packaging_analyzer import dissect_packaging
from youtube_hunter_mcp.thumbnail_ocr import extract_thumbnail_text
from youtube_hunter_mcp.thumbnails import BASE_DOWNLOAD_DIR, download_thumbnail
from youtube_hunter_mcp.transcript import get_video_transcript_async
from youtube_hunter_mcp.utils import extract_video_id, parse_view_count, sanitize_filename

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("inspect_niche_winners")

DOSSIERS_DIR = PROJECT_ROOT / "dossiers"
DOSSIERS_DIR.mkdir(parents=True, exist_ok=True)


async def inspect_single_winner(
    video_item: Dict[str, Any],
    rank: int = 1,
    max_comments: int = 20,
    fetch_transcript: bool = True,
) -> Dict[str, Any]:
    """Deeply inspect a single winning video across all intelligence dimensions."""
    url = video_item.get("url") or f"https://www.youtube.com/watch?v={video_item.get('video_id')}"
    video_id = extract_video_id(url)
    title = video_item.get("title", "")
    logger.info(f"[{rank}] Inspecionando video: '{title}' ({video_id})...")

    # 1. Scrape video page: description, tags, hashtags, comments
    page_data = await scrape_video_page(url_or_id=video_id, max_comments=max_comments)
    if not page_data.get("success"):
        logger.warning(f"Falha ao raspar pagina do video {video_id}: {page_data.get('error')}")

    # 2. High-res thumbnail download
    thumb_data = download_thumbnail(video_id, subfolder="inspect", custom_name=f"winner_{rank}_{title}")
    thumb_path = thumb_data.get("file_path") if thumb_data.get("success") else None

    # 3. OCR on thumbnail
    ocr_data = {}
    if thumb_path and Path(thumb_path).exists():
        try:
            ocr_data = extract_thumbnail_text(thumb_path)
        except Exception as e:
            logger.warning(f"Erro no OCR da thumbnail {video_id}: {e}")

    # 4. Packaging analysis (Title vs Thumbnail)
    packaging_data = {}
    try:
        ocr_text = ocr_data.get("detected_text", "")
        packaging_data = dissect_packaging(
            title=title or page_data.get("title", ""),
            thumbnail_path_or_url=thumb_path,
            thumbnail_text=ocr_text,
        )
    except Exception as e:
        logger.warning(f"Erro na dissecação de packaging {video_id}: {e}")

    # 5. Transcript & Hook
    transcript_data = {}
    pacing_data = {}
    if fetch_transcript:
        try:
            t_res = await get_video_transcript_async(video_id, include_snippets=False)
            if t_res.get("success"):
                transcript_data = t_res
                full_text = t_res.get("full_text", "")
                duration = t_res.get("duration_seconds", 300)
                hook = t_res.get("hook", "")
                pacing_data = analyze_narrative_pacing(full_text, duration_seconds=duration, hook_text=hook)
        except Exception as e:
            logger.warning(f"Erro ao buscar transcricao {video_id}: {e}")

    return {
        "rank": rank,
        "video_id": video_id,
        "title": page_data.get("title") or title,
        "url": url,
        "channel_name": page_data.get("channel_name") or video_item.get("channel_name", ""),
        "channel_url": page_data.get("channel_url", ""),
        "views": page_data.get("views") or video_item.get("views", ""),
        "published_date": page_data.get("upload_date") or video_item.get("published_time", ""),
        "category": page_data.get("category"),
        "tags": page_data.get("tags", []),
        "hashtags": page_data.get("hashtags", []),
        "description": page_data.get("description", ""),
        "comments": page_data.get("comments", []),
        "thumbnail": thumb_data,
        "ocr": ocr_data,
        "packaging": packaging_data,
        "transcript": transcript_data,
        "pacing": pacing_data,
    }


def generate_niche_inspection_dossier(
    query: str,
    winners: List[Dict[str, Any]],
    output_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a Markdown Dossier from the inspected niche winners."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    file_ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_q = sanitize_filename(query, 40)
    out_name = output_filename or f"DOSSIER_NICHE_INSPECT_{safe_q}_{file_ts}.md"
    file_path = DOSSIERS_DIR / out_name

    md: List[str] = []
    md.append(f"# 🎯 Dossiê de Inteligência de Nicho: `{query}`")
    md.append(f"> **Gerado**: {timestamp} | **Método**: Busca de Vencedores + Inspeção Individual Profunda")
    md.append(f"> **Total Inspecionado**: {len(winners)} vídeos campeões")
    md.append("")

    # 1. Sumário Executivo dos Vídeos
    md.append("## 🏆 1. Tabela de Vencedores do Nicho")
    md.append("| Rank | Título | Canal | Visualizações | Tags (#) | Comentários | Link |")
    md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for w in winners:
        r = w.get("rank", 1)
        t = (w.get("title") or "").replace("|", "-")
        c = (w.get("channel_name") or "").replace("|", "-")
        v = w.get("views") or "N/D"
        tag_count = len(w.get("tags", []))
        comm_count = len(w.get("comments", []))
        url = w.get("url", "")
        md.append(f"| #{r} | **{t}** | {c} | `{v}` | `{tag_count} tags` | `{comm_count}` | [Assistir]({url}) |")
    md.append("")

    # 2. Desconstrução Individual Profunda
    md.append("## 🔬 2. Desconstrução Individual dos Top Vencedores")
    md.append("")

    for w in winners:
        r = w.get("rank", 1)
        title = w.get("title", "")
        ch_name = w.get("channel_name", "")
        url = w.get("url", "")
        thumb = w.get("thumbnail", {})
        ocr = w.get("ocr", {})
        pack = w.get("packaging", {})
        tags = w.get("tags", [])
        hashtags = w.get("hashtags", [])
        comments = w.get("comments", [])
        hook = w.get("transcript", {}).get("hook")
        pacing = w.get("pacing", {})

        md.append(f"---")
        md.append(f"### 🎬 #{r} — {title}")
        md.append(f"- **Canal**: [{ch_name}]({w.get('channel_url')})")
        md.append(f"- **URL**: {url}")
        md.append(f"- **Views**: `{w.get('views')}` | **Publicado**: `{w.get('published_date')}`")
        if w.get("category"):
            md.append(f"- **Categoria**: `{w.get('category')}`")
        md.append("")

        # Capa e Packaging
        md.append("#### 🖼️ Capa, OCR & Packaging")
        if thumb.get("file_path"):
            md.append(f"![Thumbnail]({thumb.get('file_path')})")
        if ocr.get("detected_text"):
            md.append(f"- **Texto OCR na Capa**: `\"{ocr.get('detected_text')}\"`")
            style = ocr.get("typography_style", {})
            if style:
                md.append(f"- **Tipografia**: `{style.get('primary_style')}` | Caps: `{style.get('all_caps')}` | Contém Números: `{style.get('has_numbers')}`")
        if pack:
            verdict = pack.get("packaging_verdict", "N/D")
            redun = pack.get("redundancy_percentage", 0)
            md.append(f"- **Veredito de Packaging**: `{verdict}` (Redundância Título x Capa: `{redun}%`)")
            if pack.get("recommendations"):
                md.append(f"- **Recomendação CTR**: {pack.get('recommendations')}")
        md.append("")

        # Tags do Criador
        md.append("#### 🏷️ Tags Secretas do Criador (Keywords)")
        if tags:
            md.append(f"```text\n{', '.join(tags)}\n```")
        else:
            md.append("_Nenhuma tag explícita encontrada no player._")
        if hashtags:
            md.append(f"- **Hashtags**: `{' '.join(hashtags)}`")
        md.append("")

        # Gancho & Roteiro
        if hook:
            md.append("#### 🪝 Gancho de Abertura (Primeiros 60s)")
            md.append(f"> \"{hook}\"")
            md.append("")
            if pacing.get("success"):
                p_metrics = pacing.get("metrics", {})
                md.append(f"- **Velocidade (WPM)**: `{p_metrics.get('overall_wpm')} WPM` ({p_metrics.get('pacing_classification')})")
                md.append(f"- **Ritmo no Gancho**: `{p_metrics.get('hook_wpm')} WPM`")
                loops = pacing.get("engagement_loops", {})
                md.append(f"- **Gatilhos de Curiosidade**: `{loops.get('curiosity_triggers_detected')}` loops ({loops.get('curiosity_frequency_per_minute')}/min)")
            md.append("")

        # Descrição
        desc = w.get("description", "")
        if desc:
            md.append("#### 📝 Descrição do Vídeo (Resumo)")
            first_lines = "\n".join(desc.splitlines()[:10])
            md.append(f"```text\n{first_lines}\n... ({len(desc.splitlines())} linhas no total)\n```")
            md.append("")

        # Comentários / Dores do Público
        md.append("#### 💬 Comentários Mais Relevantes (Voz do Público)")
        if comments:
            for c in comments[:6]:
                author = c.get("author", "Anônimo")
                c_text = c.get("text", "").replace("\n", " ")
                likes = c.get("likes", "0")
                md.append(f"- **{author}** ({likes} likes): \"{c_text}\"")
        else:
            md.append("_Nenhum comentário extraído._")
        md.append("")

    # 3. Padrões Vencedores Consolidados
    md.append("## 🧬 3. Padrões Vencedores Detectados para Replicar")
    all_tags = [t.lower() for w in winners for t in w.get("tags", [])]
    from collections import Counter
    top_common_tags = Counter(all_tags).most_common(12)
    if top_common_tags:
        md.append("### 🔑 Tags mais Frequentes entre os Vencedores:")
        md.append(", ".join([f"`{t[0]}` ({t[1]}x)" for t in top_common_tags]))
        md.append("")

    md.append("---")
    md.append("*Gerado automaticamente pelo YouTube Hunter MCP — Pipeline de Busca & Inspeção Individual.*")

    content = "\n".join(md)
    file_path.write_text(content, encoding="utf-8")

    return {
        "success": True,
        "dossier_path": str(file_path.resolve()),
        "file_uri": file_path.resolve().as_uri(),
        "total_winners": len(winners),
    }


async def run_pipeline(
    query: str,
    top_n: int = 3,
    max_search_results: int = 15,
    max_comments: int = 15,
    fetch_transcripts: bool = True,
) -> Dict[str, Any]:
    """Execute the full search -> top winners -> inspect individual pipeline."""
    logger.info(f"Buscando vídeos no YouTube para a query: '{query}'...")
    search_data = await search_youtube(query=query, max_results=max_search_results)
    if not search_data.get("success"):
        return {"success": False, "error": search_data.get("error", "Search failed")}

    items = search_data.get("items") or search_data.get("results") or []
    if not items:
        return {"success": False, "error": f"Nenhum vídeo retornado para a busca '{query}'"}

    # Sort items by parsed view count descending
    items_sorted = sorted(items, key=lambda x: parse_view_count(x.get("views", "")), reverse=True)
    selected_winners = items_sorted[:top_n]

    logger.info(f"Selecionados top {len(selected_winners)} vídeos com maior volume de views.")

    inspected_winners: List[Dict[str, Any]] = []
    for idx, item in enumerate(selected_winners, start=1):
        inspected = await inspect_single_winner(
            video_item=item,
            rank=idx,
            max_comments=max_comments,
            fetch_transcript=fetch_transcripts,
        )
        inspected_winners.append(inspected)

    # Generate Dossier
    dossier_info = generate_niche_inspection_dossier(
        query=query,
        winners=inspected_winners,
    )

    return {
        "success": True,
        "query": query,
        "winners_inspected": len(inspected_winners),
        "dossier": dossier_info,
        "winners": inspected_winners,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inspeciona vídeos vencedores de um nicho via busca.")
    parser.add_argument("--query", "-q", type=str, required=True, help="Termo ou nicho de busca")
    parser.add_argument("--top", "-n", type=int, default=3, help="Número de vídeos top para dissecar (default: 3)")
    parser.add_argument("--max-results", type=int, default=15, help="Resultados da busca a filtrar (default: 15)")
    parser.add_argument("--comments", type=int, default=15, help="Comentários por vídeo (default: 15)")
    parser.add_argument("--no-transcripts", action="store_true", help="Pular extração de transcrição/gancho")

    args = parser.parse_args()

    result = asyncio.run(run_pipeline(
        query=args.query,
        top_n=args.top,
        max_search_results=args.max_results,
        max_comments=args.comments,
        fetch_transcripts=not args.no_transcripts,
    ))

    if result.get("success"):
        print(f"\n[OK] Concluido com sucesso!")
        print(f"Dossie gerado em: {result.get('dossier', {}).get('dossier_path')}")
    else:
        print(f"\n[ERRO] Falha no pipeline: {result.get('error')}")
        sys.exit(1)
