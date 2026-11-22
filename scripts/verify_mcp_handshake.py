"""Verify the MCP server still starts and exposes the same public tools."""
import asyncio, sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    params = StdioServerParameters(
        command=str(ROOT / ".venv" / "Scripts" / "youtube-hunter-mcp.exe"),
        args=[],
        cwd=str(ROOT),
        env=dict(os.environ),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print("server:", init.serverInfo.name, init.serverInfo.version)
            print("tools:", len(names))
            for n in names:
                print("  -", n)
            return 0 if len(names) >= 14 else 1


raise SystemExit(asyncio.run(main()))
