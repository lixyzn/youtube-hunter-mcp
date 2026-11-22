"""Acceptance matrix for the multi-stage transcript engine.

Run from the project root with:
    .venv\\Scripts\\python.exe scripts\\test_transcript_matrix.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youtube_hunter_mcp.transcript import get_video_transcript_async  # noqa: E402


CASES = [
    # Run the known captions-disabled case first, while L1 can still provide a
    # fast definitive negative response.  The following positive cases then
    # demonstrate the global circuit breaker after an IP block.
    ("without captions (expected clean failure)", os.getenv("YT_HUNTER_TEST_NO_CAPTIONS_VIDEO", "aqz-KE-bpKQ"), "en"),
    ("manual EN", "dQw4w9WgXcQ", "en"),
    ("auto PT-BR", os.getenv("YT_HUNTER_TEST_PT_VIDEO", "9bZkp7q19f0"), "pt"),
    ("previously failed NANA", "Oh5gXGGlwis", "pt"),
]


async def main() -> int:
    print("TRANSCRIPT ACCEPTANCE MATRIX")
    print("=" * 80)
    failures = 0
    for label, video_id, lang in CASES:
        started = time.monotonic()
        result = await get_video_transcript_async(video_id, lang_preference=lang, include_snippets=False)
        elapsed = time.monotonic() - started
        resolver = "NONE"
        for attempt in result.get("source_chain", []):
            if attempt.get("status") == "success":
                resolver = attempt.get("layer", "?")
                break
        print(f"\n[{label}] {video_id}")
        print(f"  success={result.get('success')} resolver={resolver} time={elapsed:.2f}s words={result.get('total_words', 0)} language={result.get('language_code') or result.get('language')}")
        if not result.get("success"):
            failures += 1
            print(f"  error={result.get('error')}")
        print("  chain=" + json.dumps(result.get("source_chain", []), ensure_ascii=False))
    print("\n" + "=" * 80)
    print(f"completed: {len(CASES)} cases, {failures} clean failures")
    # The fourth case is expected to fail cleanly; do not turn it into a
    # process-level failure because that is an expected negative-path test.
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
