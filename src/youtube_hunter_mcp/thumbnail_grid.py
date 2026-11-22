"""
Composite Thumbnail Grid & Moodboard Generator for YouTube Hunter MCP.
Stitches winning thumbnails into high-resolution visual comparison grids
with rank badges, metrics, and titles for AI multimodal vision and human inspection.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image, ImageDraw, ImageFont

from .thumbnails import BASE_DOWNLOAD_DIR, THUMBNAILS_DIR, download_thumbnail
from .utils import extract_video_id, sanitize_filename

logger = logging.getLogger("youtube_hunter.thumbnail_grid")

GRIDS_DIR = BASE_DOWNLOAD_DIR / "thumbnails" / "grids"
GRIDS_DIR.mkdir(parents=True, exist_ok=True)

# Standard dimensions for each thumbnail tile in the grid
TILE_WIDTH = 640
TILE_HEIGHT = 360
PADDING = 16
HEADER_HEIGHT = 70
FOOTER_HEIGHT = 20
BG_COLOR = (18, 18, 24)  # Deep sleek dark


def _get_font(size: int = 16, bold: bool = False) -> ImageFont.ImageFont:
    """Best-effort font loader for Windows and Linux fallbacks."""
    font_candidates = [
        # Windows system fonts
        "C:\\Windows\\Fonts\\segoeuib.ttf" if bold else "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\calibrib.ttf" if bold else "C:\\Windows\\Fonts\\calibri.ttf",
        # Linux / system fallbacks
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in font_candidates:
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _draw_pill_badge(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    bg_color: Tuple[int, int, int],
    text_color: Tuple[int, int, int] = (255, 255, 255),
    pad_x: int = 10,
    pad_y: int = 5,
) -> Tuple[int, int]:
    """Draw a modern rounded pill badge with text."""
    x, y = xy
    try:
        bbox = font.getbbox(text)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    except Exception:
        text_w = len(text) * 8
        text_h = 14

    badge_w = text_w + pad_x * 2
    badge_h = text_h + pad_y * 2

    # Draw rounded rectangle
    try:
        draw.rounded_rectangle(
            [x, y, x + badge_w, y + badge_h],
            radius=6,
            fill=bg_color,
        )
    except Exception:
        draw.rectangle([x, y, x + badge_w, y + badge_h], fill=bg_color)

    draw.text((x + pad_x, y + pad_y - 1), text, fill=text_color, font=font)
    return badge_w, badge_h


def _collect_thumbnail_images(
    items: Optional[List[Union[Dict[str, Any], str]]] = None,
    subfolder_or_query: Optional[str] = None,
    max_items: int = 6,
) -> List[Dict[str, Any]]:
    """Resolve local image paths and metadata from items or subfolder."""
    resolved: List[Dict[str, Any]] = []

    # Case 1: subfolder or query given
    if subfolder_or_query and not items:
        target_dir: Optional[Path] = None
        exact_path = THUMBNAILS_DIR / subfolder_or_query
        if exact_path.exists() and exact_path.is_dir():
            target_dir = exact_path
        else:
            # Try fuzzy match in thumbnails dir
            sanitized = sanitize_filename(subfolder_or_query).lower()
            for d in THUMBNAILS_DIR.iterdir():
                if d.is_dir() and (sanitized in d.name.lower() or d.name.lower() in sanitized):
                    target_dir = d
                    break

        if target_dir and target_dir.exists():
            for img_file in sorted(target_dir.glob("*.jpg")):
                stem = img_file.stem
                m = re.match(r"^(.*)_([A-Za-z0-9_-]{11})$", stem)
                if m:
                    title = m.group(1).replace("_", " ").strip()
                    vid = m.group(2)
                else:
                    title = stem.replace("_", " ")
                    vid = stem[-11:] if len(stem) >= 11 else ""

                resolved.append({
                    "video_id": vid,
                    "title": title,
                    "local_path": str(img_file.resolve()),
                    "views_text": "",
                    "multiplier": "",
                })
                if len(resolved) >= max_items:
                    break
        return resolved

    # Case 2: List of items or strings
    if items:
        for idx, item in enumerate(items[:max_items], 1):
            if isinstance(item, str):
                vid = extract_video_id(item) or item
                title = f"Video {idx}"
                views_text = ""
                mult = ""
                local_path = None
            elif isinstance(item, dict):
                vid = item.get("video_id") or extract_video_id(item.get("url") or "") or ""
                title = item.get("title") or f"Video {idx}"
                views_text = item.get("views_text") or (f"{item.get('views'):,}" if item.get("views") else "")
                mult = item.get("outlier_factor") or item.get("viral_multiplier") or ""
                if isinstance(mult, (int, float)) and mult > 0:
                    mult = f"{mult}x"
                local_path = item.get("thumbnail_local_path") or (item.get("enrichment") or {}).get("thumbnail_local_path")
            else:
                continue

            # If local path is missing or invalid, attempt to fetch thumbnail
            if not local_path or not Path(str(local_path)).exists():
                if vid:
                    res = download_thumbnail(vid, subfolder="grid_cache", custom_name=title[:30])
                    if res.get("success"):
                        local_path = res.get("local_path")

            if local_path and Path(str(local_path)).exists():
                resolved.append({
                    "video_id": vid,
                    "title": title,
                    "local_path": str(local_path),
                    "views_text": views_text,
                    "multiplier": str(mult) if mult else "",
                })

    return resolved


def build_thumbnail_grid(
    items_or_urls: Optional[List[Union[Dict[str, Any], str]]] = None,
    subfolder_or_query: Optional[str] = None,
    grid_title: Optional[str] = None,
    max_items: int = 6,
    columns: int = 3,
    output_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a visual moodboard / contact sheet combining top thumbnails with badges.

    Args:
        items_or_urls: List of video IDs, URLs, or enriched video dictionaries.
        subfolder_or_query: Optional folder name or search query inside downloads/thumbnails/.
        grid_title: Optional title header displayed at the top of the grid.
        max_items: Maximum thumbnails to include (default 6).
        columns: Number of grid columns (default 3).
        output_name: Optional custom output file name.

    Returns:
        Dict with local_path, file_uri, dimensions, and items metadata.
    """
    candidates = _collect_thumbnail_images(
        items=items_or_urls,
        subfolder_or_query=subfolder_or_query,
        max_items=max_items,
    )

    if not candidates:
        return {
            "success": False,
            "error": "No valid thumbnails found to build grid.",
            "hint": "Provide a list of video IDs/URLs or specify a subfolder in downloads/thumbnails/.",
        }

    total = len(candidates)
    cols = max(1, min(columns, total))
    rows = (total + cols - 1) // cols

    # Fonts
    title_font = _get_font(24, bold=True)
    badge_font = _get_font(18, bold=True)
    sub_font = _get_font(14, bold=False)

    # Compute canvas size
    grid_w = cols * TILE_WIDTH + (cols + 1) * PADDING
    grid_h = rows * TILE_HEIGHT + (rows + 1) * PADDING + (HEADER_HEIGHT if grid_title else 0) + FOOTER_HEIGHT

    canvas = Image.new("RGB", (grid_w, grid_h), BG_COLOR)
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Draw Header if requested
    y_offset = PADDING
    if grid_title:
        header_text = f"🦅 {grid_title}"
        draw.text((PADDING + 8, PADDING + 12), header_text, fill=(255, 255, 255), font=title_font)
        meta_info = f"{total} thumbnails analisadas · {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
        draw.text((PADDING + 10, PADDING + 42), meta_info, fill=(160, 165, 180), font=sub_font)
        y_offset += HEADER_HEIGHT

    # Place each thumbnail
    items_meta = []
    for idx, c in enumerate(candidates, 1):
        col_idx = (idx - 1) % cols
        row_idx = (idx - 1) // cols

        cell_x = PADDING + col_idx * (TILE_WIDTH + PADDING)
        cell_y = y_offset + row_idx * (TILE_HEIGHT + PADDING)

        img_path = Path(c["local_path"])
        try:
            with Image.open(img_path) as thumb_img:
                thumb_rgb = thumb_img.convert("RGB")
                resized = thumb_rgb.resize((TILE_WIDTH, TILE_HEIGHT), Image.Resampling.LANCZOS)
                canvas.paste(resized, (cell_x, cell_y))
        except Exception as err:
            logger.warning("Could not render thumbnail %s: %s", img_path, err)
            continue

        # Draw overlays on the cell
        # 1. Rank badge (Top-Left)
        rank_bg = (220, 38, 38, 230) if idx == 1 else ((234, 88, 12, 230) if idx == 2 else (30, 41, 59, 220))
        _draw_pill_badge(
            draw=draw,
            xy=(cell_x + 12, cell_y + 12),
            text=f"#{idx}",
            font=badge_font,
            bg_color=rank_bg,
            text_color=(255, 255, 255),
        )

        # 2. Metric badge (Top-Right): Multiplier or Views
        metric_text = ""
        if c.get("multiplier"):
            metric_text = f"🔥 {c['multiplier']}"
        elif c.get("views_text"):
            metric_text = f"👁️ {c['views_text']}"

        if metric_text:
            # Measure width to right-align
            try:
                bw = badge_font.getbbox(metric_text)[2] - badge_font.getbbox(metric_text)[0]
            except Exception:
                bw = len(metric_text) * 9
            pill_x = cell_x + TILE_WIDTH - (bw + 32)
            _draw_pill_badge(
                draw=draw,
                xy=(pill_x, cell_y + 12),
                text=metric_text,
                font=badge_font,
                bg_color=(15, 23, 42, 220),
                text_color=(245, 158, 11) if "🔥" in metric_text else (226, 232, 240),
            )

        # 3. Bottom title caption bar
        title_str = c.get("title", "")
        if title_str:
            title_display = title_str[:55] + ("..." if len(title_str) > 55 else "")
            caption_bar_h = 32
            draw.rectangle(
                [cell_x, cell_y + TILE_HEIGHT - caption_bar_h, cell_x + TILE_WIDTH, cell_y + TILE_HEIGHT],
                fill=(10, 10, 14, 215),
            )
            draw.text(
                (cell_x + 12, cell_y + TILE_HEIGHT - caption_bar_h + 8),
                title_display,
                fill=(241, 245, 249),
                font=sub_font,
            )

        items_meta.append({
            "rank": idx,
            "video_id": c.get("video_id"),
            "title": c.get("title"),
            "views": c.get("views_text"),
            "multiplier": c.get("multiplier"),
            "local_path": str(img_path.resolve()),
        })

    # Save final grid
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = sanitize_filename(grid_title or subfolder_or_query or "thumbnails", 40)
    out_filename = output_name or f"grid_{slug}_{timestamp}.jpg"
    final_path = GRIDS_DIR / out_filename

    canvas.save(final_path, format="JPEG", quality=92, optimize=True)

    return {
        "success": True,
        "grid_title": grid_title or slug,
        "total_thumbnails": len(items_meta),
        "columns": cols,
        "rows": rows,
        "dimensions": f"{grid_w}x{grid_h}",
        "local_path": str(final_path.resolve()),
        "file_uri": final_path.resolve().as_uri(),
        "items": items_meta,
    }
