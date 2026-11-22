"""
Narrative Pacing, WPM, and Retention Rhythm Analyzer for YouTube Hunter MCP.
Deconstructs script velocity, question density, open curiosity loops, and retention hooks.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

CURIOUS_KEYWORDS = [
    r"\bwhy\b",
    r"\bhow\b",
    r"\bwhat if\b",
    r"\bsecret\b",
    r"\bmistake\b",
    r"\btruth\b",
    r"\bnever\b",
    r"\bdon't\b",
    r"\bwarning\b",
    r"\breason\b",
    r"\bhack\b",
    r"\btrap\b",
    r"\bhidden\b",
    r"\bshocking\b",
    r"\bactually\b",
    r"\bthe catch\b",
    r"\bhere is the problem\b",
]


def classify_pacing(wpm: float) -> Dict[str, str]:
    """Classify speech tempo based on Words Per Minute."""
    if wpm >= 180:
        return {
            "tier": "⚡ Hyper-Paced (High Energy / Fast Cuts)",
            "description": "Very fast tempo typical of top American entertainment and high-retention video essays.",
        }
    elif wpm >= 150:
        return {
            "tier": "🔥 Dynamic Storytelling (Optimal Retention)",
            "description": "Sweet spot for educational and tech content. Fast enough to prevent drop-off without fatiguing listeners.",
        }
    elif wpm >= 120:
        return {
            "tier": "⚖️ Steady Masterclass (Deep Dive / Educational)",
            "description": "Authoritative pacing typical of podcasts, academic breakdowns, or long-form discussions.",
        }
    else:
        return {
            "tier": "🧘 Relaxed / Atmospheric (< 120 WPM)",
            "description": "Slow pacing, often relies heavily on B-roll pauses, visuals, or ambient sound.",
        }


def analyze_narrative_pacing(
    transcript_text: str,
    duration_seconds: float,
    hook_text: Optional[str] = None,
    hook_duration_seconds: float = 60.0,
) -> Dict[str, Any]:
    """
    Analyze script pacing, speaking speed, curiosity loops, and hook mechanics.

    Args:
        transcript_text: Full clean script text.
        duration_seconds: Total duration of the video or transcript in seconds.
        hook_text: Script text from the first 60 seconds (optional).
        hook_duration_seconds: Duration of the hook in seconds (default 60s).

    Returns:
        Structured narrative and pacing report.
    """
    if not transcript_text or duration_seconds <= 0:
        return {
            "success": False,
            "error": "Transcript text and positive duration are required for pacing analysis.",
        }

    words = transcript_text.split()
    total_words = len(words)
    duration_minutes = duration_seconds / 60.0
    wpm = round(total_words / duration_minutes, 1)

    # Hook metrics
    hook_words_count = 0
    hook_wpm = 0.0
    if hook_text:
        hook_words = hook_text.split()
        hook_words_count = len(hook_words)
        hook_wpm = round(hook_words_count / (hook_duration_seconds / 60.0), 1)

    # Question & Curiosity Loop Density
    question_count = transcript_text.count("?")
    curiosity_triggers = []
    text_lower = transcript_text.lower()

    for pattern in CURIOUS_KEYWORDS:
        matches = re.findall(pattern, text_lower)
        if matches:
            curiosity_triggers.append({
                "trigger": pattern.replace(r"\b", "").strip(),
                "count": len(matches),
            })

    total_curiosity_hits = sum(t["count"] for t in curiosity_triggers) + question_count
    curiosity_loops_per_min = round(total_curiosity_hits / max(1.0, duration_minutes), 2)

    # Velocity Comparison
    velocity_shift = "steady"
    if hook_wpm > 0:
        diff = hook_wpm - wpm
        if diff > 15:
            velocity_shift = "accelerated_hook (Fast energetic start to capture attention)"
        elif diff < -15:
            velocity_shift = "slow_burn_hook (Deliberate dramatic pause or atmospheric start)"

    pacing_info = classify_pacing(wpm)

    return {
        "success": True,
        "metrics": {
            "total_words": total_words,
            "duration_seconds": round(duration_seconds, 1),
            "duration_formatted": f"{int(duration_minutes)}m {int(duration_seconds % 60)}s",
            "overall_wpm": wpm,
            "hook_wpm": hook_wpm if hook_wpm > 0 else wpm,
            "velocity_pattern": velocity_shift,
            "pacing_classification": pacing_info["tier"],
            "pacing_note": pacing_info["description"],
        },
        "engagement_loops": {
            "direct_questions_count": question_count,
            "curiosity_triggers_detected": total_curiosity_hits,
            "curiosity_frequency_per_minute": curiosity_loops_per_min,
            "top_trigger_words": sorted(curiosity_triggers, key=lambda x: x["count"], reverse=True)[:6],
        },
        "recommendations": {
            "target_wpm_for_niche": 160,
            "pacing_verdict": (
                "Ideal high-retention pacing." if 150 <= wpm <= 185
                else "Consider increasing speech tempo or trimming pauses in editing." if wpm < 150
                else "Very fast; ensure key points have pauses or visual B-roll."
            ),
        },
    }
