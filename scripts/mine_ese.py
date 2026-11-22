import asyncio
import json
import sys
from pathlib import Path

# Add src to path
src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from youtube_hunter_mcp.channel_miner import deep_mine_channel
from youtube_hunter_mcp.mining_report import generate_mining_dashboard, get_mining_catalog

async def main():
    print("Iniciando mineracao de @ESeocifial...")
    result = await deep_mine_channel(
        channel_url_or_handle="@ESeocifial",
        max_videos=20,
        enrich_top_n=8,
        mode="popular",
        download_thumbnails=True,
        fetch_transcripts=True,
        lang_preference="pt"
    )
    print("Sucesso:", result.get("success"))
    if not result.get("success"):
        print("Erro:", result.get("error"))
        return
    
    print(f"Canal: {result.get('channel_title')}")
    print(f"Videos analisados: {len(result.get('videos', []))}")
    print(f"Dossie gerado: {result.get('dossier_path')}")
    
    # Gerar report HTML
    report = generate_mining_dashboard()
    print("Relatorio HTML atualizado:", report.get("report_path"))

if __name__ == "__main__":
    asyncio.run(main())
