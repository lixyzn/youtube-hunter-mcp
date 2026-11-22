import json
from pathlib import Path

base = Path(r"D:\mcp\youtube-hunter-mcp\downloads\mines")
outlier_files = sorted(list(base.glob("outliers_*.json")), key=lambda f: f.stat().st_mtime, reverse=True)

print(f"Encontrados {len(outlier_files)} arquivos de outliers.")
for f in outlier_files[:3]:
    with open(f, encoding="utf-8") as fp:
        d = json.load(fp)
    print("=" * 60)
    print(f"QUERY: {d.get('query')}")
    print(f"TOTAL OUTLIERS: {d.get('total_outliers_found')}")
    for item in d.get("outliers", [])[:4]:
        print(f" - [{item.get('views_raw')}] ({item.get('outlier_multiplier')}x sub) -> {item.get('title')}")
        print(f"   Canal: {item.get('channel_name')} ({item.get('subscriber_count_raw')} subs)")
        if item.get("thumbnail_text"):
            print(f"   OCR Capa: {item.get('thumbnail_text')}")
