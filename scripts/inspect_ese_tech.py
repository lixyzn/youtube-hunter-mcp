import asyncio
import json
import sys
from pathlib import Path

src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from youtube_hunter_mcp.browser import scrape_video_page

async def main():
    videos = [
        "9vUdppDD_Kw",  # What if you had SUPERHUMAN reflexes?
        "yschJT3LzQY",  # E se você tivesse IA em 2004?
        "reli3mNDgiQ",  # What if your strength doubled every 24 hours?
    ]
    
    results = []
    for vid in videos:
        print(f"Inspecting video {vid}...")
        try:
            res = await scrape_video_page(vid, max_comments=15)
            print("Title:", res.get("title"))
            print("Tags:", res.get("tags"))
            print("Description Excerpt:", res.get("description")[:200] if res.get("description") else "None")
            results.append({
                "video_id": vid,
                "title": res.get("title"),
                "description": res.get("description"),
                "tags": res.get("tags"),
                "comments": [c.get("text") for c in res.get("comments", []) if c.get("text")]
            })
        except Exception as e:
            print(f"Error inspecting {vid}: {e}")

    out_file = Path(r"D:\mcp\youtube-hunter-mcp\downloads\mines\ese_tech_details.json")
    out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved tech details to {out_file}")

if __name__ == "__main__":
    asyncio.run(main())
