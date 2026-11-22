import json
from pathlib import Path

def print_channel_summary(filepath):
    with open(filepath, encoding="utf-8") as f:
        d = json.load(f)
    print("=" * 60)
    print(f"CANAL: {d.get('channel_title')}")
    print(f"MEDIAN VIEWS: {d.get('median_views'):,}" if d.get('median_views') else f"MEDIAN VIEWS: {d.get('median_views')}")
    print(f"AVERAGE VIEWS: {d.get('average_views'):,}" if d.get('average_views') else f"AVERAGE VIEWS: {d.get('average_views')}")
    print("TOP 5 VIDEOS:")
    for i, v in enumerate(d.get("videos", [])[:5]):
        print(f"  #{i+1} [{v.get('views_raw')}] ({v.get('outlier_factor')}x) -> {v.get('title')}")
        if v.get('script_hook'):
            print(f"      Hook: {v.get('script_hook')[:110]}...")

base = Path(r"D:\mcp\youtube-hunter-mcp\downloads\mines")
print_channel_summary(base / "channel_E_Se_popular_20261118_062230.json")
print_channel_summary(base / "channel_Em_Poucas_Palavras_–_Kurzgesagt_popular_20261118_062340.json")
print_channel_summary(base / "channel_Mundo_Torajo_popular_20261118_062404.json")
