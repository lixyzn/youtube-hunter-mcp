"""End-to-end check of yt_get_transcript through the MCP protocol."""
import asyncio, sys, os, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    params = StdioServerParameters(
        command=str(ROOT / ".venv" / "Scripts" / "youtube-hunter-mcp.exe"),
        args=[], cwd=str(ROOT), env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for video_id, lang in [("Oh5gXGGlwis", "pt"), ("dQw4w9WgXcQ", "en")]:
                result = await session.call_tool("yt_get_transcript", {"url_or_id": video_id, "lang_preference": lang})
                text = result.content[0].text if result.content else ""
                data = json.loads(text)
                print(f"\n=== {video_id} ({lang}) ===")
                print("success:", data.get("success"), "| extractor:", data.get("extractor"),
                      "| words:", data.get("total_words"), "| lang:", data.get("language_code"),
                      "| cached:", data.get("cached"))
                chain = data.get("source_chain", [])
                for item in chain:
                    print("   chain:", item.get("layer"), item.get("status"), str(item.get("reason"))[:90])
                print("   hook:", (data.get("hook") or "")[:160])
    return 0


raise SystemExit(asyncio.run(main()))
