"""
Packaging and CTR Synergy Analyzer for YouTube Hunter MCP.
Deconstructs Title + Thumbnail synergy, curiosity gaps, mobile truncation,
word redundancy, and psychological click drivers.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .thumbnail_ocr import extract_thumbnail_text
from .utils import extract_video_id

# Common English & Portuguese stopwords to ignore when measuring overlap
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "of", "in", "on", "at", "to", "for",
    "with", "is", "are", "was", "were", "it", "its", "that", "this", "these", "those",
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "por", "para", "com", "e", "que", "se", "como",
}

POWER_WORDS = [
    r"\bsecret\b", r"\bmistake\b", r"\btruth\b", r"\bnever\b", r"\bdangerous\b",
    r"\bwarning\b", r"\bshocking\b", r"\bhidden\b", r"\bactually\b", r"\bfinally\b",
    r"\bimpossible\b", r"\bruined\b", r"\bdestroyed\b", r"\bdisaster\b", r"\bworst\b",
    r"\bbest\b", r"\bbanned\b", r"\bexposed\b", r"\blie\b", r"\bfake\b", r"\bfail\b",
    r"\bsegredo\b", r"\berro\b", r"\bverdade\b", r"\bnunca\b", r"\bperigoso\b",
    r"\baviso\b", r"\bchocante\b", r"\bescondido\b", r"\bfinalmente\b", r"\bimpossível\b",
    r"\bruinado\b", r"\bdestruído\b", r"\bpior\b", r"\bmelhor\b", r"\bproibido\b",
]

PATTERNS = [
    (r"\b(why|por que|porque)\b", "Curiosity / Causality ('Why X happened')"),
    (r"\b(never|don't|pare|nunca|não|stop)\b", "Negative Framing / Loss Aversion (Strong CTR trigger)"),
    (r"\b(secret|hidden|truth|segredo|verdade|escondido)\b", "Mystery / Insider Knowledge ('The Truth About X')"),
    (r"\b(finally|at last|finalmente)\b", "Long-awaited Resolution / High Stakes"),
    (r"\b(how to|como)\b", "Direct How-To / Educational Promise"),
    (r"\b(ruined|destroyed|collapsed|falência|fracassou)\b", "Tragedy / Collapse / Downfall Hook"),
    (r"\b(nobody|no one|ninguém)\b", "Exclusivity / Contrarian ('Nobody saw it coming')"),
    (r"\b\d+\s*(ways|reasons|motivos|segredos|erros|mistakes|dias|days)\b", "Numbered Listicle / Clear Scope"),
]


def _tokenize(text: str) -> List[str]:
    cleaned = re.sub(r"[^\w\s]", " ", (text or "").lower())
    tokens = [w for w in cleaned.split() if len(w) > 2 and w not in STOPWORDS]
    return tokens


def dissect_packaging(
    title: str,
    thumbnail_path_or_url: Optional[str] = None,
    thumbnail_text: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Dissect YouTube packaging synergy between the video Title and Thumbnail cover.

    Args:
        title: YouTube video title.
        thumbnail_path_or_url: Local thumbnail image path, remote URL, or video ID.
        thumbnail_text: Optional manually provided thumbnail OCR text.

    Returns:
        Dict with character metrics, synergy classification, redundancy score, and recommendations.
    """
    clean_title = (title or "").strip()
    if not clean_title:
        return {"success": False, "error": "Title cannot be empty."}

    # 1. OCR Extraction if thumbnail is provided and text wasn't supplied
    ocr_result = None
    cover_text = (thumbnail_text or "").strip()

    if not cover_text and thumbnail_path_or_url:
        try:
            ocr_result = extract_thumbnail_text(thumbnail_path_or_url)
            if ocr_result.get("has_text"):
                cover_text = ocr_result.get("full_text", "")
        except Exception:
            pass

    # 2. Title Metrics
    char_count = len(clean_title)
    words = clean_title.split()
    word_count = len(words)

    # YouTube truncates titles around 50-60 characters on mobile devices
    mobile_cutoff_risk = char_count > 50
    ideal_length = 35 <= char_count <= 50

    # 3. Detect Power Words & Curiosity Triggers
    detected_power_words = []
    for pattern in POWER_WORDS:
        m = re.search(pattern, clean_title, re.IGNORECASE)
        if m:
            detected_power_words.append(m.group(0).lower())
    detected_power_words = list(dict.fromkeys(detected_power_words))

    detected_patterns = []
    for pattern_re, label in PATTERNS:
        if re.search(pattern_re, clean_title, re.IGNORECASE):
            detected_patterns.append(label)

    # 4. Cover Text Metrics
    cover_words = cover_text.split() if cover_text else []
    cover_word_count = len(cover_words)
    cover_clutter = "clean" if cover_word_count <= 4 else ("moderate" if cover_word_count <= 7 else "cluttered")

    # 5. Redundancy & Synergy Calculation
    title_tokens = set(_tokenize(clean_title))
    cover_tokens = set(_tokenize(cover_text)) if cover_text else set()

    overlap_words = list(title_tokens.intersection(cover_tokens))
    redundancy_percentage = (
        round((len(overlap_words) / max(len(cover_tokens), 1)) * 100, 1)
        if cover_tokens
        else 0.0
    )

    # 6. Overall Packaging Verdict
    flaws = []
    strengths = []

    if mobile_cutoff_risk:
        flaws.append(f"Mobile Cutoff Risk: Title has {char_count} chars (safe limit is ~50). Important words might be hidden behind '...'.")
    elif ideal_length:
        strengths.append("Optimal Title Length: Perfectly fits mobile and desktop feeds without truncation.")

    if redundancy_percentage >= 50.0:
        flaws.append(f"High Redundancy ({redundancy_percentage}%): Thumbnail repeats words already in the title ({', '.join(overlap_words)}). Cover should complement or create mystery, not duplicate.")
    elif cover_text and redundancy_percentage == 0.0:
        strengths.append("High Synergy: Thumbnail text adds brand new curiosity without repeating title words.")

    if cover_word_count > 5:
        flaws.append(f"Cover Text Clutter: {cover_word_count} words on thumbnail. Top creators use 2 to 4 words maximum.")
    elif 1 <= cover_word_count <= 4:
        strengths.append(f"Punchy Cover Text: {cover_word_count} words is the sweet spot for visual glanceability.")

    if detected_power_words:
        strengths.append(f"Emotional Hooks: Contains power words ({', '.join(detected_power_words)}).")

    # Final Classification
    if len(flaws) == 0 and len(strengths) >= 2:
        verdict = "🔥 S-TIER PACKAGING (High CTR Potential)"
    elif len(flaws) == 1 and redundancy_percentage < 50:
        verdict = "⭐ SOLID PACKAGING (Minor Tweaks Possible)"
    else:
        verdict = "⚠️ SUB-OPTIMAL PACKAGING (Needs Optimization)"

    # Actionable Recommendations
    recommendations = []
    if mobile_cutoff_risk:
        frontload = " ".join(words[:5])
        recommendations.append(f"Shorten title or frontload key curiosity words in the first 5 words ('{frontload}').")
    if redundancy_percentage >= 40:
        recommendations.append(f"Change cover text: instead of repeating '{overlap_words[0]}', use an emotional reaction, question, or 3-word cliffhanger.")
    if cover_word_count > 5:
        recommendations.append("Reduce cover text to 2-4 punchy words in ALL CAPS with high-contrast background.")
    if not detected_patterns:
        recommendations.append("Test adding a curiosity gap (e.g. 'Why...', 'The Secret of...', or a negative alert).")

    return {
        "success": True,
        "title": clean_title,
        "cover_text_detected": cover_text,
        "metrics": {
            "title_characters": char_count,
            "title_words": word_count,
            "mobile_friendly": not mobile_cutoff_risk,
            "cover_words_count": cover_word_count,
            "cover_clutter_tier": cover_clutter,
            "overlap_words": overlap_words,
            "redundancy_percentage": redundancy_percentage,
        },
        "psychological_triggers": {
            "power_words": detected_power_words,
            "patterns": detected_patterns or ["Straightforward Topic Statement"],
        },
        "verdict": verdict,
        "strengths": strengths,
        "flaws": flaws,
        "recommendations": recommendations,
    }
