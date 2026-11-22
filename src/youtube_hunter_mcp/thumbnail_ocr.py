"""
Thumbnail OCR & Visual Text Anatomy Engine for YouTube Hunter MCP.
Extracts text printed on thumbnail images, detects trigger words, capitalization, and emotional framing.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# Prevent ONNX Runtime from hogging 100% CPU across all cores
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("ONNXRUNTIME_NUM_THREADS", "2")

from rapidocr_onnxruntime import RapidOCR

from .thumbnails import download_thumbnail
from .utils import extract_video_id

logger = logging.getLogger("youtube_hunter.ocr")

_ocr_instance: Optional[RapidOCR] = None


def get_ocr_engine() -> RapidOCR:
    """Lazy initialize RapidOCR singleton instance."""
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = RapidOCR()
    return _ocr_instance


def extract_thumbnail_text(image_path_or_url_or_id: str) -> Dict[str, Any]:
    """
    Extract text, keywords, and typography patterns from a thumbnail image.

    Args:
        image_path_or_url_or_id: Local image file path, video URL, or video ID.

    Returns:
        Dict with detected text lines, confidence scores, full extracted text, and typography metrics.
    """
    path_obj = Path(image_path_or_url_or_id)

    # If it's a local file that exists
    if path_obj.is_file():
        image_path = str(path_obj.resolve())
    else:
        # Assume it's a video URL or ID and download thumbnail
        vid = extract_video_id(image_path_or_url_or_id)
        if not vid:
            return {
                "success": False,
                "error": f"Invalid image path or video ID: '{image_path_or_url_or_id}'",
            }
        dl = download_thumbnail(vid, subfolder="ocr_cache")
        if not dl.get("success"):
            return dl
        image_path = dl["local_path"]

    try:
        engine = get_ocr_engine()
        result, elapse = engine(image_path)

        lines = []
        full_text_parts = []
        is_all_caps = True
        has_numbers = False

        if result:
            for item in result:
                # item format: [box_points, text, confidence]
                text = item[1].strip()
                conf = float(item[2])
                if not text or conf < 0.4:
                    continue

                lines.append({
                    "text": text,
                    "confidence": round(conf, 3),
                })
                full_text_parts.append(text)

                if not text.isupper() and any(c.isalpha() for c in text):
                    is_all_caps = False
                if any(c.isdigit() for c in text):
                    has_numbers = True

        combined_text = " ".join(full_text_parts)

        return {
            "success": True,
            "image_path": image_path,
            "has_text": len(lines) > 0,
            "total_lines": len(lines),
            "full_text": combined_text,
            "is_all_caps": is_all_caps if lines else False,
            "has_numbers": has_numbers,
            "lines": lines,
        }

    except Exception as e:
        logger.exception(f"OCR failed for {image_path}")
        return {
            "success": False,
            "image_path": image_path,
            "error": f"OCR processing failed: {str(e)}",
        }
