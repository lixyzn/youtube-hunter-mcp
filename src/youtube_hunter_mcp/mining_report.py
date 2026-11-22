"""
Mining data persistence and HTML dashboard/report generation for YouTube Hunter MCP.
Aggregates mined channel sessions and niche outlier hunts into a browsable local HTML report.
"""

from __future__ import annotations

import datetime
import html
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .thumbnails import BASE_DOWNLOAD_DIR
from .utils import extract_video_id, sanitize_filename

MINES_DIR = BASE_DOWNLOAD_DIR / "mines"
MINES_DIR.mkdir(parents=True, exist_ok=True)

REPORTS_DIR = BASE_DOWNLOAD_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _timestamp_slug() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_write_json(path: Path, data: Dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_channel_mine(data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Persist a deep_mine_channel result to disk for later dashboard/report generation."""
    if not data or not data.get("success"):
        return None
    record = {
        "record_type": "channel_mine",
        "saved_at": _now_iso(),
        **data,
    }
    channel = sanitize_filename(data.get("channel_title") or "channel", 50)
    mode = sanitize_filename(str(data.get("mining_mode") or "mine"), 20)
    filename = f"channel_{channel}_{mode}_{_timestamp_slug()}.json"
    path = _safe_write_json(MINES_DIR / filename, record)
    return {"path": str(path.resolve()), "file_uri": path.resolve().as_uri()}


def save_outlier_mine(data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Persist a find_niche_outliers result to disk for later dashboard/report generation."""
    if not data or not data.get("success"):
        return None
    record = {
        "record_type": "niche_outliers",
        "saved_at": _now_iso(),
        **data,
    }
    query = sanitize_filename(data.get("query") or "outliers", 50)
    filename = f"outliers_{query}_{_timestamp_slug()}.json"
    path = _safe_write_json(MINES_DIR / filename, record)
    return {"path": str(path.resolve()), "file_uri": path.resolve().as_uri()}


def _synthesize_legacy_outlier_records(existing: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Best-effort: surface legacy outlier thumbnail folders as report entries when no saved JSON exists."""
    try:
        thumbs_root = BASE_DOWNLOAD_DIR / "thumbnails"
        if not thumbs_root.exists():
            return []
        existing_queries = set()
        for r in existing:
            q = (r.get("query") or "").strip().lower()
            if q:
                existing_queries.add(q)
        legacy = []
        for folder in sorted(thumbs_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not folder.is_dir():
                continue
            name = folder.name
            if not name.startswith("outliers_"):
                continue
            query_guess = name[len("outliers_"):].replace("_", " ").strip()
            if query_guess.lower() in existing_queries:
                continue
            items = []
            for img in sorted(folder.glob("*.jpg")):
                stem = img.stem
                # filenames are usually like "<title>_<videoid>"
                m = re.match(r"^(.*)_([A-Za-z0-9_-]{11})$", stem)
                if m:
                    title_guess = m.group(1).replace("_", " ").strip()
                    vid = m.group(2)
                else:
                    title_guess = stem.replace("_", " ").strip()
                    vid = ""
                url = f"https://www.youtube.com/watch?v={vid}" if vid else ""
                items.append({
                    "video_id": vid,
                    "title": title_guess or stem,
                    "url": url,
                    "channel_url": "",
                    "channel_name": "",
                    "views": None,
                    "views_raw": "N/A",
                    "viral_multiplier": 0,
                    "viral_tag": "LEGADO (pasta de thumbs)",
                    "thumbnail_local_path": str(img.resolve()),
                })
            if not items:
                continue
            legacy.append({
                "record_type": "niche_outliers",
                "saved_at": datetime.datetime.fromtimestamp(folder.stat().st_mtime).isoformat(timespec="seconds"),
                "query": query_guess,
                "total_analyzed": len(items),
                "outliers_found": len(items),
                "filters_applied": {"min_multiplier": "N/A", "max_subscribers_cap": "N/A"},
                "top_viral_outliers": items,
                "_legacy": True,
                "_source_file": str(folder.resolve()),
            })
        return legacy
    except Exception:
        return []


def _synthesize_legacy_channel_records(existing: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Synthesize channel mine records from dossiers/ when no saved JSON exists."""
    try:
        dossiers_dir = BASE_DOWNLOAD_DIR.parent / "dossiers"
        if not dossiers_dir.exists():
            return []
        existing_channels = set()
        for r in existing:
            c = (r.get("channel_name") or r.get("channel_title") or "").strip().lower()
            if c:
                existing_channels.add(c)
        legacy = []
        for doc in sorted(dossiers_dir.glob("DOSSIER_*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            if "DOSSIER_OUTLIERS_" in doc.name:
                continue
            text = doc.read_text(encoding="utf-8")
            m_title = re.search(r"^# 🦅 YouTube Intelligence Dossier:\s*(.*)$", text, re.MULTILINE)
            channel_name = m_title.group(1).strip() if m_title else doc.stem.replace("DOSSIER_", "").split("_202")[0].replace("_", " ")
            if channel_name.lower() in existing_channels:
                continue

            m_url = re.search(r"\|\s*\*\*Channel\*\*:\s*\[([^\]]+)\]\(([^)]+)\)", text)
            channel_url = m_url.group(2).strip() if m_url else f"https://www.youtube.com/@{sanitize_filename(channel_name)}"

            m_avg = re.search(r"Channel Average Views\*\*:\s*`([\d.,]+)`", text)
            m_med = re.search(r"Median Views\*\*:\s*`([\d.,]+)`", text)
            m_max = re.search(r"Viral Ceiling \(Max Views\)\*\*:\s*`([\d.,]+)`", text)
            m_out = re.search(r"Outliers Detected\*\*:\s*`(\d+)`", text)

            avg_views = int(m_avg.group(1).replace(",", "").replace(".", "")) if m_avg else 0
            med_views = int(m_med.group(1).replace(",", "").replace(".", "")) if m_med else 0
            max_views = int(m_max.group(1).replace(",", "").replace(".", "")) if m_max else 0
            outliers_count = int(m_out.group(1)) if m_out else 0

            videos = []
            for line in text.splitlines():
                if line.startswith("| #"):
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 7:
                        v_title = parts[2].replace("**", "").strip()
                        v_views = parts[3].strip()
                        v_mult = parts[4].replace("`", "").strip()
                        v_tag = parts[5].strip()
                        m_link = re.search(r"\((https://[^\)]+)\)", parts[6])
                        v_url = m_link.group(1) if m_link else ""
                        vid = extract_video_id(v_url) or ""
                        videos.append({
                            "video_id": vid,
                            "title": v_title,
                            "url": v_url,
                            "views_raw": v_views,
                            "views": None,
                            "outlier_factor": v_mult,
                            "performance_tag": v_tag,
                            "thumbnail_local_path": "",
                        })

            existing_channels.add(channel_name.lower())
            legacy.append({
                "record_type": "channel_mine",
                "saved_at": datetime.datetime.fromtimestamp(doc.stat().st_mtime).isoformat(timespec="seconds"),
                "channel_name": channel_name,
                "channel_title": channel_name,
                "channel_url": channel_url,
                "mining_mode": "popular",
                "stats": {
                    "median_views": med_views,
                    "mean_views": avg_views,
                    "average_views": avg_views,
                    "max_views": max_views,
                    "top_outliers_count": outliers_count,
                    "outliers_found": outliers_count,
                },
                "statistics": {
                    "median_views": med_views,
                    "mean_views": avg_views,
                    "average_views": avg_views,
                    "max_views": max_views,
                    "outliers_found": outliers_count,
                },
                "videos": videos,
                "dossier": {"local_path": str(doc.resolve()), "file_uri": doc.resolve().as_uri()},
                "_legacy": True,
                "_source_file": str(doc.resolve()),
                "_source_mtime": doc.stat().st_mtime,
            })
        return legacy
    except Exception:
        return []


def load_mine_records() -> List[Dict[str, Any]]:
    """Load all saved mining records, newest first (includes legacy thumbnail-folder outliers if needed)."""
    records: List[Dict[str, Any]] = []
    if MINES_DIR.exists():
        for p in sorted(MINES_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
                obj["_source_file"] = str(p.resolve())
                obj["_source_mtime"] = p.stat().st_mtime
                records.append(obj)
            except Exception:
                continue
    records.extend(_synthesize_legacy_outlier_records(records))
    records.extend(_synthesize_legacy_channel_records(records))
    records.sort(key=lambda r: r.get("_source_mtime") or 0, reverse=True)
    return records


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _rel_or_uri(target: Optional[str], report_dir: Path) -> str:
    if not target:
        return ""
    try:
        p = Path(str(target))
        if p.exists():
            try:
                rel = os.path.relpath(str(p.resolve()), str(report_dir.resolve()))
                return rel.replace("\\", "/")
            except Exception:
                return p.resolve().as_uri()
    except Exception:
        pass
    s = str(target)
    if s.startswith("file://") or s.startswith("http://") or s.startswith("https://"):
        return s
    return s


def _pick_channel_thumb(record: Dict[str, Any], report_dir: Path) -> str:
    videos = record.get("videos") or []
    for v in videos:
        t = v.get("thumbnail_local_path")
        if t and Path(str(t)).exists():
            return _rel_or_uri(t, report_dir)
    for v in (record.get("strategic_takeaways") or {}).get("top_outliers") or []:
        t = v.get("thumbnail_local_path")
        if t and Path(str(t)).exists():
            return _rel_or_uri(t, report_dir)
    return ""


def _pick_outlier_thumb(record: Dict[str, Any], report_dir: Path) -> str:
    for v in record.get("top_viral_outliers") or []:
        t = v.get("thumbnail_local_path")
        if t and Path(str(t)).exists():
            return _rel_or_uri(t, report_dir)
    return ""


def _fmt_num(n: Any) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except Exception:
        return _esc(n)


def _views_sort_value(raw: Any) -> int:
    if raw is None:
        return -1
    if isinstance(raw, (int, float)):
        return int(raw)
    s = str(raw)
    m = re.search(r"([\d.,]+)\s*([KMBkmb])", s)
    if m:
        num = float(m.group(1).replace(",", "."))
        mult = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(m.group(2).lower(), 1)
        return int(num * mult)
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) if digits else -1


def _render_video_rows_channel(videos: List[Dict[str, Any]], report_dir: Path) -> str:
    rows = []
    for i, v in enumerate(videos, 1):
        views = v.get("views") if v.get("views") is not None else _views_sort_value(v.get("views_raw"))
        outlier = v.get("outlier_score") or 0
        try:
            outlier_num = float(outlier)
        except Exception:
            outlier_num = 0.0
        thumb = _rel_or_uri(v.get("thumbnail_local_path"), report_dir)
        thumb_html = (
            f'<img class="thumb" src="{_esc(thumb)}" loading="lazy" alt="thumb">'
            if thumb else '<div class="thumb placeholder">sem print</div>'
        )
        url = v.get("url") or (f"https://www.youtube.com/watch?v={v.get('video_id')}" if v.get("video_id") else "#")
        trans = v.get("transcript") or {}
        hook = trans.get("hook_first_60s") or trans.get("hook") or ""
        hook_block = f'<details class="hook"><summary>Hook / roteiro</summary><div>{_esc(hook[:1200])}</div></details>' if hook else ''
        rows.append(
            f'<tr data-views="{int(views) if views is not None else -1}" data-outlier="{outlier_num}">'
            f'<td class="rank">{i}</td>'
            f'<td class="thumb-cell"><a href="{_esc(url)}" target="_blank" rel="noopener">{thumb_html}</a></td>'
            f'<td class="title-cell"><a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(v.get("title") or "(sem título)")}</a>'
            f'<div class="meta">{_esc(v.get("published_time") or "")} · {_esc(v.get("duration") or "")}</div>'
            f'{hook_block}</td>'
            f'<td class="num">{_esc(v.get("views_raw") or _fmt_num(views))}</td>'
            f'<td class="num">{_esc(v.get("outlier_factor") or "")}</td>'
            f'<td><span class="tag">{_esc(v.get("performance_tag") or "")}</span></td>'
            '</tr>'
        )
    return "\n".join(rows)


def _render_video_rows_outliers(videos: List[Dict[str, Any]], report_dir: Path) -> str:
    rows = []
    for i, v in enumerate(videos, 1):
        views = v.get("views") if v.get("views") is not None else _views_sort_value(v.get("views_raw"))
        mult = v.get("viral_multiplier") or 0
        try:
            mult_num = float(mult)
        except Exception:
            mult_num = 0.0
        thumb = _rel_or_uri(v.get("thumbnail_local_path"), report_dir)
        thumb_html = (
            f'<img class="thumb" src="{_esc(thumb)}" loading="lazy" alt="thumb">'
            if thumb else '<div class="thumb placeholder">sem print</div>'
        )
        url = v.get("url") or (f"https://www.youtube.com/watch?v={v.get('video_id')}" if v.get("video_id") else "#")
        chan_url = v.get("channel_url") or "#"
        hook = v.get("hook_first_60s") or ""
        ocr = v.get("thumbnail_text") or ""
        ocr_block = f'<div class="ocr"><strong>Texto na thumb:</strong> {_esc(ocr[:300])}</div>' if ocr else ''
        hook_block = f'<details class="hook"><summary>Hook</summary><div>{_esc(hook[:1200])}</div></details>' if hook else ''
        rows.append(
            f'<tr data-views="{int(views) if views is not None else -1}" data-outlier="{mult_num}">'
            f'<td class="rank">{i}</td>'
            f'<td class="thumb-cell"><a href="{_esc(url)}" target="_blank" rel="noopener">{thumb_html}</a></td>'
            f'<td class="title-cell"><a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(v.get("title") or "(sem título)")}</a>'
            f'<div class="meta">Canal: <a href="{_esc(chan_url)}" target="_blank" rel="noopener">{_esc(v.get("channel_name") or v.get("channel") or "N/A")}</a>'
            f' · Inscritos: {_esc(v.get("subscribers_raw") or v.get("subscribers") or "N/A")}</div>'
            f'{ocr_block}{hook_block}</td>'
            f'<td class="num">{_esc(v.get("views_raw") or _fmt_num(views))}</td>'
            f'<td class="num">{_esc(mult)}x</td>'
            f'<td><span class="tag">{_esc(v.get("viral_tag") or "")}</span></td>'
            '</tr>'
        )
    return "\n".join(rows)


def _render_channel_section(record: Dict[str, Any], report_dir: Path, idx: int) -> str:
    stats = record.get("statistics") or {}
    videos = record.get("videos") or []
    videos_sorted = sorted(videos, key=lambda v: (v.get("views") or 0), reverse=True)
    title = record.get("channel_title") or "Canal"
    url = record.get("channel_url") or "#"
    mode = record.get("mining_mode") or ""
    saved_at = record.get("saved_at") or ""
    thumb = _pick_channel_thumb(record, report_dir)
    hero = f'<img class="hero" src="{_esc(thumb)}" alt="print">' if thumb else '<div class="hero placeholder">sem print/thumbnail</div>'
    table_id = f"chan-{idx}"
    return f'''
    <section class="card channel-card" id="section-{table_id}">
      <div class="card-head">
        <div class="hero-wrap"><a href="{_esc(url)}" target="_blank" rel="noopener">{hero}</a></div>
        <div class="card-info">
          <h2>📺 {_esc(title)}</h2>
          <p class="links"><a href="{_esc(url)}" target="_blank" rel="noopener">Abrir canal no YouTube</a></p>
          <div class="stats-grid">
            <div class="stat"><span>Modo</span><strong>{_esc(mode)}</strong></div>
            <div class="stat"><span>Vídeos analisados</span><strong>{_esc(record.get("total_videos_analyzed") or len(videos))}</strong></div>
            <div class="stat"><span>Média views</span><strong>{_fmt_num(stats.get("average_views"))}</strong></div>
            <div class="stat"><span>Mediana</span><strong>{_fmt_num(stats.get("median_views"))}</strong></div>
            <div class="stat"><span>Máx views</span><strong>{_fmt_num(stats.get("max_views"))}</strong></div>
            <div class="stat"><span>Mín views</span><strong>{_fmt_num(stats.get("min_views"))}</strong></div>
            <div class="stat"><span>Outliers</span><strong>{_esc(stats.get("outliers_found") or 0)}</strong></div>
            <div class="stat"><span>Minerado em</span><strong>{_esc(saved_at)}</strong></div>
          </div>
        </div>
      </div>
      <div class="toolbar">
        <span class="label">Ordenar vídeos:</span>
        <button onclick="sortTable('{table_id}', 'views', 'desc')">⬇ Maiores views</button>
        <button onclick="sortTable('{table_id}', 'views', 'asc')">⬆ Menores views</button>
        <button onclick="sortTable('{table_id}', 'outlier', 'desc')">🔥 Maior outlier</button>
        <button onclick="sortTable('{table_id}', 'outlier', 'asc')">Menor outlier</button>
      </div>
      <div class="table-wrap">
        <table id="{table_id}">
          <thead><tr><th>#</th><th>Print/Thumb</th><th>Título / Canal</th><th>Views</th><th>Multiplicador</th><th>Performance</th></tr></thead>
          <tbody>
            {_render_video_rows_channel(videos_sorted, report_dir)}
          </tbody>
        </table>
      </div>
    </section>
    '''


def _render_outliers_section(record: Dict[str, Any], report_dir: Path, idx: int) -> str:
    videos = record.get("top_viral_outliers") or []
    videos_sorted = sorted(videos, key=lambda v: (v.get("views") or 0), reverse=True)
    query = record.get("query") or "Nicho"
    saved_at = record.get("saved_at") or ""
    thumb = _pick_outlier_thumb(record, report_dir)
    hero = f'<img class="hero" src="{_esc(thumb)}" alt="print">' if thumb else '<div class="hero placeholder">sem print/thumbnail</div>'
    filters = record.get("filters_applied") or {}
    table_id = f"out-{idx}"
    return f'''
    <section class="card outlier-card" id="section-{table_id}">
      <div class="card-head">
        <div class="hero-wrap">{hero}</div>
        <div class="card-info">
          <h2>🚀 Nicho/Busca: {_esc(query)}</h2>
          <p class="links muted">Mineração de outliers virais (canais pequenos que estouraram)</p>
          <div class="stats-grid">
            <div class="stat"><span>Analisados</span><strong>{_esc(record.get("total_analyzed") or 0)}</strong></div>
            <div class="stat"><span>Outliers achados</span><strong>{_esc(record.get("outliers_found") or len(videos))}</strong></div>
            <div class="stat"><span>Filtro mult.</span><strong>{_esc(filters.get("min_multiplier") or "N/A")}</strong></div>
            <div class="stat"><span>Cap inscritos</span><strong>{_esc(filters.get("max_subscribers_cap") or "N/A")}</strong></div>
            <div class="stat"><span>Minerado em</span><strong>{_esc(saved_at)}</strong></div>
          </div>
        </div>
      </div>
      <div class="toolbar">
        <span class="label">Ordenar vídeos:</span>
        <button onclick="sortTable('{table_id}', 'views', 'desc')">⬇ Maiores views</button>
        <button onclick="sortTable('{table_id}', 'views', 'asc')">⬆ Menores views</button>
        <button onclick="sortTable('{table_id}', 'outlier', 'desc')">🔥 Maior multiplicador</button>
        <button onclick="sortTable('{table_id}', 'outlier', 'asc')">Menor multiplicador</button>
      </div>
      <div class="table-wrap">
        <table id="{table_id}">
          <thead><tr><th>#</th><th>Print/Thumb</th><th>Título / Canal</th><th>Views</th><th>Multiplicador</th><th>Tag</th></tr></thead>
          <tbody>
            {_render_video_rows_outliers(videos_sorted, report_dir)}
          </tbody>
        </table>
      </div>
    </section>
    '''


def generate_mining_dashboard(output_name: Optional[str] = None) -> Dict[str, Any]:
    """Generate a self-contained HTML dashboard with all saved mined channels and outlier hunts."""
    records = load_mine_records()
    ts = _timestamp_slug()
    safe_name = sanitize_filename(output_name, 40) if output_name else "mining_dashboard"
    report_path = REPORTS_DIR / f"{safe_name}_{ts}.html"
    report_dir = report_path.parent

    channel_records = [
        r for r in records
        if r.get("record_type") == "channel_mine"
        or ("channel_title" in r and "videos" in r and r.get("record_type") != "niche_outliers")
    ]
    outlier_records = [
        r for r in records
        if r.get("record_type") == "niche_outliers"
        or ("top_viral_outliers" in r and "query" in r)
    ]

    sections_html = []
    toc_items = []
    for i, rec in enumerate(channel_records, 1):
        sec_id = f"chan-{i}"
        toc_items.append(
            f'<li><a href="#section-{sec_id}">📺 {_esc(rec.get("channel_title") or "Canal")}</a> '
            f'<small>({_esc(rec.get("mining_mode") or "")})</small></li>'
        )
        sections_html.append(_render_channel_section(rec, report_dir, i))
    for i, rec in enumerate(outlier_records, 1):
        sec_id = f"out-{i}"
        toc_items.append(
            f'<li><a href="#section-{sec_id}">🚀 {_esc(rec.get("query") or "Nicho")}</a> '
            f'<small>(outliers)</small></li>'
        )
        sections_html.append(_render_outliers_section(rec, report_dir, i))

    total_channels = len(channel_records)
    total_niches = len(outlier_records)
    total_videos = sum(len(r.get("videos") or []) for r in channel_records) + sum(
        len(r.get("top_viral_outliers") or []) for r in outlier_records
    )

    # Collect any visual thumbnail grids/moodboards
    grids_dir = BASE_DOWNLOAD_DIR / "thumbnails" / "grids"
    grids_html = []
    if grids_dir.exists():
        for g in sorted(grids_dir.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True)[:6]:
            rel_g = _rel_or_uri(str(g), report_dir)
            g_name = g.stem.replace("grid_", "").replace("_", " ")
            grids_html.append(
                f'<div class="grid-card"><a href="{_esc(rel_g)}" target="_blank" rel="noopener">'
                f'<img src="{_esc(rel_g)}" alt="{_esc(g_name)}" loading="lazy">'
                f'<div class="grid-card-name">{_esc(g_name)}</div>'
                f'</a></div>'
            )

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    empty_msg = ""
    if not records:
        empty_msg = (
            '<div class="empty">'
            '<h2>Nenhum dado minerado encontrado ainda</h2>'
            '<p>Execute <code>yt_deep_mine_channel</code> ou <code>yt_find_viral_outliers</code> primeiro. '
            'Os resultados serão salvos automaticamente em <code>downloads/mines/</code> e aparecerão aqui.</p>'
            '</div>'
        )

    grids_block = ""
    if grids_html:
        grids_block = f"""
        <div class="grids-section">
          <h3 style="margin-top:0;font-size:16px;">🖼️ Grades Visuais de Thumbnails (Moodboards)</h3>
          <p class="meta" style="margin-bottom:12px;">Comparações montadas em alta resolução para visão multimodal da IA ou inspeção humana rápida:</p>
          <div class="grids-gallery">
            {''.join(grids_html)}
          </div>
        </div>
        """

    html_doc = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Hunter - Painel de Mineração</title>
<style>
:root {{
  --bg:#0b0f14; --panel:#141a22; --panel2:#1b2330; --text:#e8eef6; --muted:#9fb0c3;
  --accent:#5cc8ff; --accent2:#7cf29c; --border:#263244; --warn:#ffcc66;
}}
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family: Segoe UI, Roboto, Arial, sans-serif; background:var(--bg); color:var(--text); }}
a {{ color: var(--accent); text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
header {{ padding: 28px 28px 10px; border-bottom:1px solid var(--border); background: linear-gradient(180deg,#101722,#0b0f14); }}
h1 {{ margin:0 0 6px; font-size: 28px; }}
.subtitle {{ color: var(--muted); margin:0 0 14px; }}
.summary {{ display:flex; flex-wrap:wrap; gap:12px; margin: 12px 0 18px; }}
.pill {{ background:var(--panel); border:1px solid var(--border); padding:10px 14px; border-radius:10px; }}
.pill strong {{ color: var(--accent2); font-size:18px; margin-right:6px; }}
.layout {{ display:grid; grid-template-columns: 280px 1fr; gap: 0; }}
nav.toc {{ position: sticky; top:0; align-self:start; max-height:100vh; overflow:auto; padding:18px; border-right:1px solid var(--border); background:#0e141c; }}
nav.toc h3 {{ margin:0 0 10px; font-size:14px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }}
nav.toc ul {{ list-style:none; padding:0; margin:0; }}
nav.toc li {{ margin:8px 0; font-size:14px; }}
main {{ padding: 20px 24px 40px; }}
.card {{ background:var(--panel); border:1px solid var(--border); border-radius:14px; padding:18px; margin: 0 0 22px; }}
.card-head {{ display:flex; gap:18px; align-items:flex-start; }}
.hero-wrap {{ width: 320px; flex: 0 0 320px; }}
.hero {{ width:100%; height:180px; object-fit:cover; border-radius:10px; border:1px solid var(--border); background:#0a0e13; display:block; }}
.hero.placeholder {{ display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:13px; }}
.card-info {{ flex:1; min-width:0; }}
.card-info h2 {{ margin:0 0 6px; font-size:22px; }}
.muted {{ color: var(--muted); }}
.stats-grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(150px,1fr)); gap:8px; margin-top:10px; }}
.stat {{ background:var(--panel2); border:1px solid var(--border); border-radius:8px; padding:8px 10px; }}
.stat span {{ display:block; color:var(--muted); font-size:12px; }}
.stat strong {{ font-size:15px; }}
.toolbar {{ margin:14px 0 8px; display:flex; flex-wrap:wrap; gap:8px; align-items:center; }}
.toolbar .label {{ color:var(--muted); font-size:13px; margin-right:4px; }}
button {{ background:#1f2b3a; color:var(--text); border:1px solid var(--border); padding:7px 11px; border-radius:8px; cursor:pointer; font-size:13px; }}
button:hover {{ background:#263447; border-color:#35506f; }}
.table-wrap {{ overflow:auto; border:1px solid var(--border); border-radius:10px; }}
table {{ width:100%; border-collapse:collapse; min-width:900px; }}
th, td {{ padding:10px 10px; border-bottom:1px solid var(--border); vertical-align:top; text-align:left; }}
th {{ background:#182130; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.03em; position:sticky; top:0; }}
tr:hover td {{ background:#18202b; }}
.thumb-cell {{ width:180px; }}
.thumb {{ width:160px; height:90px; object-fit:cover; border-radius:8px; border:1px solid var(--border); display:block; background:#0a0e13; }}
.thumb.placeholder {{ display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:12px; }}
.title-cell a {{ font-weight:600; }}
.meta {{ color:var(--muted); font-size:12px; margin-top:4px; }}
.ocr {{ color:#d7e6a1; font-size:12px; margin-top:6px; }}
.num {{ white-space:nowrap; font-variant-numeric: tabular-nums; }}
.tag {{ display:inline-block; padding:3px 8px; border-radius:999px; background:#223044; border:1px solid #31465f; font-size:12px; }}
details.hook {{ margin-top:6px; }}
details.hook summary {{ cursor:pointer; color:var(--accent); font-size:12px; }}
details.hook div {{ margin-top:6px; color:#dfe9f5; font-size:13px; line-height:1.4; white-space:pre-wrap; }}
.empty {{ background:var(--panel); border:1px dashed var(--border); border-radius:14px; padding:30px; text-align:center; color:var(--muted); }}
code {{ background:#111822; border:1px solid var(--border); padding:2px 6px; border-radius:6px; color:#d7eaff; }}
.grids-section {{ margin-bottom:24px; padding:18px; background:var(--panel); border:1px solid var(--border); border-radius:14px; }}
.grids-gallery {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:14px; }}
.grid-card {{ border-radius:8px; overflow:hidden; border:1px solid var(--border); background:#0c1017; transition:transform .2s, border-color .2s; }}
.grid-card:hover {{ transform:translateY(-3px); border-color:#3b82f6; }}
.grid-card img {{ width:100%; height:150px; object-fit:cover; display:block; }}
.grid-card-name {{ padding:8px 10px; font-size:12px; font-weight:600; color:#e2e8f0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
@media (max-width: 980px) {{
  .layout {{ grid-template-columns: 1fr; }}
  nav.toc {{ position:relative; max-height:none; border-right:none; border-bottom:1px solid var(--border); }}
  .card-head {{ flex-direction:column; }}
  .hero-wrap {{ width:100%; flex:none; }}
  .hero {{ height:220px; }}
}}
</style>
</head>
<body>
<header>
  <h1>🦅 YouTube Hunter — Painel de Mineração</h1>
  <p class="subtitle">Visão geral dos canais e nichos minerados, com links, prints/thumbnails e comparação de vídeos (maiores/menores).</p>
  <div class="summary">
    <div class="pill"><strong>{total_channels}</strong> canais minerados</div>
    <div class="pill"><strong>{total_niches}</strong> buscas de outliers por nicho</div>
    <div class="pill"><strong>{total_videos}</strong> vídeos listados</div>
    <div class="pill">Gerado em <strong>{_esc(now_str)}</strong></div>
  </div>
</header>
<div class="layout">
  <nav class="toc">
    <h3>Minerados</h3>
    <ul>
      {''.join(toc_items) if toc_items else '<li class="muted">Nada ainda</li>'}
    </ul>
  </nav>
  <main>
    {empty_msg}
    {grids_block}
    {''.join(sections_html)}
  </main>
</div>
<script>
function sortTable(tableId, key, dir) {{
  const table = document.getElementById(tableId);
  if (!table) return;
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const mult = dir === 'asc' ? 1 : -1;
  rows.sort((a,b) => {{
    const av = parseFloat(a.dataset[key] || '-1');
    const bv = parseFloat(b.dataset[key] || '-1');
    if (av === bv) return 0;
    return (av < bv ? -1 : 1) * mult;
  }});
  rows.forEach((r, i) => {{
    tbody.appendChild(r);
    const rank = r.querySelector('.rank');
    if (rank) rank.textContent = (i + 1);
  }});
}}
</script>
</body>
</html>
"""

    report_path.write_text(html_doc, encoding="utf-8")
    return {
        "success": True,
        "report_path": str(report_path.resolve()),
        "report_uri": report_path.resolve().as_uri(),
        "records_found": len(records),
        "channels": total_channels,
        "niche_searches": total_niches,
        "videos_listed": total_videos,
        "mines_dir": str(MINES_DIR.resolve()),
        "message": (
            "Relatório HTML gerado com sucesso." if records else
            "Relatório HTML gerado, mas nenhum dado minerado foi encontrado em downloads/mines/. "
            "Rode yt_deep_mine_channel ou yt_find_viral_outliers para popular."
        ),
    }


def get_mining_catalog() -> Dict[str, Any]:
    """
    Compile a complete, structured catalog and executive markdown overview
    of all channels, niche topics, visual grids, and dossiers stored on disk.
    """
    records = load_mine_records()

    dossiers_dir = BASE_DOWNLOAD_DIR.parent / "dossiers"
    thumbs_root = BASE_DOWNLOAD_DIR / "thumbnails"
    grids_dir = thumbs_root / "grids"
    transcripts_dir = BASE_DOWNLOAD_DIR / "transcripts_cache"
    reports_dir = BASE_DOWNLOAD_DIR / "reports"

    total_thumbs = len(list(thumbs_root.glob("*/*.jpg"))) if thumbs_root.exists() else 0
    total_transcripts = len(list(transcripts_dir.glob("*.json"))) if transcripts_dir.exists() else 0
    total_dossiers = len(list(dossiers_dir.glob("*.md"))) if dossiers_dir.exists() else 0
    total_grids = len(list(grids_dir.glob("*.jpg"))) if grids_dir.exists() else 0
    total_reports = len(list(reports_dir.glob("*.html"))) if reports_dir.exists() else 0

    latest_report = None
    if reports_dir.exists():
        htmls = sorted(reports_dir.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
        if htmls:
            latest_report = {
                "filename": htmls[0].name,
                "local_path": str(htmls[0].resolve()),
                "file_uri": htmls[0].resolve().as_uri(),
                "created_at": datetime.datetime.fromtimestamp(htmls[0].stat().st_mtime).isoformat(timespec="seconds"),
            }

    channels = []
    niches = []

    for r in records:
        rtype = r.get("record_type")
        if rtype == "channel_mine":
            c_name = r.get("channel_name") or r.get("channel_title") or "Canal"
            vids = r.get("videos") or []
            stats = r.get("stats") or r.get("statistics") or {}
            top_outlier = None
            if vids:
                sorted_vids = sorted(vids, key=lambda v: (v.get("views") or 0), reverse=True)
                top = sorted_vids[0]
                top_outlier = {
                    "title": top.get("title"),
                    "views": top.get("views_raw") or top.get("views"),
                    "multiplier": top.get("outlier_factor") or "1.0x",
                    "url": top.get("url"),
                }
            channels.append({
                "channel_name": c_name,
                "channel_url": r.get("channel_url"),
                "total_videos_analyzed": len(vids),
                "median_views": stats.get("median_views", 0),
                "average_views": stats.get("average_views") or stats.get("mean_views", 0),
                "top_outlier": top_outlier,
                "saved_at": r.get("saved_at") or "",
                "dossier": r.get("dossier"),
            })
        elif rtype == "niche_outliers":
            q = r.get("query") or r.get("keyword") or "Outliers"
            outliers = r.get("top_viral_outliers") or r.get("top_outliers") or r.get("videos") or []
            top_v = outliers[0] if outliers else {}
            peak_mult = 0.0
            for o in outliers:
                m = o.get("viral_multiplier") or o.get("outlier_factor") or 0
                try:
                    m_f = float(m)
                    if m_f > peak_mult:
                        peak_mult = m_f
                except Exception:
                    pass
            niches.append({
                "query": q,
                "total_analyzed": r.get("total_analyzed") or len(outliers),
                "outliers_found": len(outliers),
                "peak_multiplier": f"{peak_mult}x" if peak_mult > 0 else "N/A",
                "top_outlier_title": top_v.get("title") or "N/A",
                "top_outlier_views": top_v.get("views_raw") or top_v.get("views") or "N/A",
                "saved_at": r.get("saved_at") or "",
            })

    # Visual Grids list
    visual_grids = []
    if grids_dir.exists():
        for g in sorted(grids_dir.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True):
            visual_grids.append({
                "filename": g.name,
                "local_path": str(g.resolve()),
                "file_uri": g.resolve().as_uri(),
                "created_at": datetime.datetime.fromtimestamp(g.stat().st_mtime).isoformat(timespec="seconds"),
            })

    # Dossiers list
    dossiers_list = []
    if dossiers_dir.exists():
        for d in sorted(dossiers_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            dossiers_list.append({
                "filename": d.name,
                "local_path": str(d.resolve()),
                "file_uri": d.resolve().as_uri(),
                "size_kb": round(d.stat().st_size / 1024, 1),
                "created_at": datetime.datetime.fromtimestamp(d.stat().st_mtime).isoformat(timespec="seconds"),
            })

    # Build sleek Markdown Summary Table
    md = []
    md.append("# 🦅 YouTube Hunter — Catálogo Executivo de Inteligência")
    md.append(f"> **Atualizado em**: `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}` | **Base no Disco D**")
    md.append("")
    md.append("## 📊 1. Métricas Globais em Disco")
    md.append(f"- **Canais Mapeados**: `{len(channels)}` canais")
    md.append(f"- **Nichos de Outliers Pesquisados**: `{len(niches)}` pesquisas de nicho")
    md.append(f"- **Thumbnails Salvas**: `{total_thumbs}` capas em alta resolução")
    md.append(f"- **Transcrições em Cache**: `{total_transcripts}` roteiros prontos")
    md.append(f"- **Grades Visuais (Moodboards)**: `{len(visual_grids)}` montagens para visão multimodal")
    md.append(f"- **Dossiês Markdown**: `{len(dossiers_list)}` relatórios gerados")
    if latest_report:
        md.append(f"- **Último Painel Web**: [{latest_report['filename']}]({latest_report['file_uri']})")
    md.append("")

    if channels:
        md.append("## 📺 2. Canais Investigados")
        md.append("| Canal | Vídeos | Média Views | Maior Outlier | Data |")
        md.append("| :--- | :--- | :--- | :--- | :--- |")
        for c in channels:
            top_str = "N/A"
            if c.get("top_outlier"):
                to = c["top_outlier"]
                title_short = (to.get('title') or "")[:35]
                top_str = f"**{to.get('views')}** (`{to.get('multiplier')}`) — {title_short}..."
            md.append(f"| [{c['channel_name']}]({c.get('channel_url')}) | `{c['total_videos_analyzed']}` | `{c.get('median_views', 0):,}` | {top_str} | {c['saved_at'][:10]} |")
        md.append("")

    if niches:
        md.append("## 🎯 3. Nichos de Outliers Pesquisados")
        md.append("| Nicho / Palavra-Chave | Outliers | Pico Multiplicador | Melhor Vídeo | Data |")
        md.append("| :--- | :--- | :--- | :--- | :--- |")
        for n in niches[:20]:
            title_short = (n.get('top_outlier_title') or "")[:45]
            md.append(f"| `{n['query']}` | `{n['outliers_found']}` | `{n['peak_multiplier']}` | {title_short}... | {n['saved_at'][:10]} |")
        if len(niches) > 20:
            md.append(f"\n*(+ {len(niches) - 20} outros nichos disponíveis no disco)*")
        md.append("")

    if visual_grids:
        md.append("## 🖼️ 4. Grades Visuais Disponíveis (Moodboards para IA e Análise)")
        for g in visual_grids[:5]:
            md.append(f"- [{g['filename']}]({g['file_uri']}) (`{g['created_at']}`)")
        md.append("")

    if dossiers_list:
        md.append("## 📄 5. Dossiês Markdown em `dossiers/`")
        for d in dossiers_list[:5]:
            md.append(f"- [{d['filename']}]({d['file_uri']}) (`{d['size_kb']} KB`)")
        md.append("")

    markdown_summary = "\n".join(md)

    return {
        "success": True,
        "summary": {
            "total_channels": len(channels),
            "total_niches": len(niches),
            "total_thumbnails": total_thumbs,
            "total_transcripts": total_transcripts,
            "total_visual_grids": len(visual_grids),
            "total_dossiers": len(dossiers_list),
            "total_reports": total_reports,
        },
        "latest_report": latest_report,
        "channels": channels,
        "niches": niches,
        "visual_grids": visual_grids,
        "dossiers": dossiers_list,
        "markdown_overview": markdown_summary,
    }
