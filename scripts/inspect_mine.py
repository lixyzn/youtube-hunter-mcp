import json
from pathlib import Path

p = Path(r"D:\mcp\youtube-hunter-mcp\downloads\mines\channel_E_Se_popular_20261118_062230.json")
with open(p, encoding="utf-8") as f:
    d = json.load(f)

print("Channel:", d.get("channel_title"))
print("Median views:", d.get("median_views"))
print("Average views:", d.get("average_views"))
print("\n--- TOP VIDEOS & OUTLIERS ---")
for i, v in enumerate(d.get("videos", [])):
    title = v.get("title")
    views = v.get("views_raw")
    factor = v.get("outlier_factor")
    hook = v.get("script_hook")
    print(f"#{i+1} [{views}] ({factor}x) -> {title}")
    if hook:
        print(f"   Hook: {hook[:140]}...")
