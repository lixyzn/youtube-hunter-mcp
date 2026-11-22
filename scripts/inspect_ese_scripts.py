import json
from pathlib import Path

p = Path(r"D:\mcp\youtube-hunter-mcp\downloads\mines\channel_E_Se_popular_20261118_062230.json")
with open(p, encoding="utf-8") as f:
    d = json.load(f)

for v in d.get("videos", [])[:3]:
    print("=" * 60)
    print("TITULO:", v.get("title"))
    print("VIEWS:", v.get("views_raw"))
    print("OUTLIER FACTOR:", v.get("outlier_factor"))
    print("THUMBNAIL LOCAL:", v.get("local_thumbnail"))
    print("SCRIPT HOOK:")
    print(v.get("script_hook"))
    print("TRANSCRIPT EXCERPT:")
    t = v.get("transcript_text", "")
    print(t[:500] if t else "No transcript")
