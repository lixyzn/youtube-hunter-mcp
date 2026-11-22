import json, pathlib, subprocess, sys

p = sorted(pathlib.Path(r"D:\pesquisa de mercado anime\04_scripts_e_hooks").glob("HOOKS_WPM_*.json"))[-1]
data = json.loads(p.read_text(encoding="utf-8"))
fails = [v for v in data["videos"] if not v.get("has_transcript")]
print("videos sem transcricao:", len(fails))
for v in fails:
    print("-", v["channel"], "|", v["video_id"], "|", (v.get("title") or "")[:50])

ydl = r"D:\mcp\youtube-hunter-mcp\.venv\Scripts\yt-dlp.exe"
print("\n=== cross-check yt-dlp (info do player, sem baixar legenda) ===")
for v in fails:
    vid = v["video_id"]
    cmd = [ydl, "--skip-download", "--no-warnings", "--js-runtimes", "node",
           "--extractor-args", "youtube:player_client=android_vr",
           "--print", "%(automatic_captions.keys)s|%(subtitles.keys)s", f"https://www.youtube.com/watch?v={vid}"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        line = (out.stdout or out.stderr or "").strip().splitlines()
        print(f"- {vid}: {line[-1][:140] if line else 'sem出力'}")
    except Exception as e:
        print(f"- {vid}: EXC {str(e)[:80]}")
