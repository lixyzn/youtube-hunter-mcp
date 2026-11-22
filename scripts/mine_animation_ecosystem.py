import asyncio
import json
import sys
from pathlib import Path

src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from youtube_hunter_mcp.channel_miner import deep_mine_channel
from youtube_hunter_mcp.niche_outliers import find_niche_outliers
from youtube_hunter_mcp.thumbnail_grid import build_thumbnail_grid
from youtube_hunter_mcp.packaging_analyzer import dissect_packaging
from youtube_hunter_mcp.mining_report import generate_mining_dashboard, get_mining_catalog

async def main():
    print("=== 1. Minerando canais complementares de animacao 2D e 3D ===")
    
    # Kurzgesagt Brasil - O maior expoente de animacao educativa 2D/isometrica no Brasil
    print("Minerando @Kurzgesagt_br...")
    res_kurz = await deep_mine_channel(
        channel_url_or_handle="@Kurzgesagt_br",
        max_videos=15,
        enrich_top_n=6,
        mode="popular",
        download_thumbnails=True,
        fetch_transcripts=True,
        lang_preference="pt"
    )
    print("Kurzgesagt OK:", res_kurz.get("success"))

    # Mundo Torajo - Um dos maiores canais BR de animacao narrativa 2D
    print("Minerando @Torajo...")
    res_torajo = await deep_mine_channel(
        channel_url_or_handle="@Torajo",
        max_videos=15,
        enrich_top_n=6,
        mode="popular",
        download_thumbnails=True,
        fetch_transcripts=True,
        lang_preference="pt"
    )
    print("Torajo OK:", res_torajo.get("success"))

    print("\n=== 2. Cacando Outliers Virais no Nicho de Animacao (2D e 3D) ===")
    
    queries = [
        "animacao 3d brasil",
        "animacao 2d historia brasil",
        "e se animacao brasil"
    ]
    
    for q in queries:
        print(f"Minerando nicho outlier: '{q}'...")
        try:
            out_res = await find_niche_outliers(
                query=q,
                max_search_results=12,
                min_multiplier=1.8,
                max_channel_subscribers=250000,
                enrich_top_n=4
            )
            print(f"Resultados '{q}': {out_res.get('total_outliers_found', 0)} outliers encontrados")
        except Exception as e:
            print(f"Erro em outlier '{q}': {e}")

    print("\n=== 3. Atualizando Dashboard Central de Inteligencia ===")
    dashboard = generate_mining_dashboard()
    print("Dashboard gerado com sucesso em:", dashboard.get("report_path"))
    print("Dashboard URI:", dashboard.get("report_uri"))

if __name__ == "__main__":
    asyncio.run(main())
