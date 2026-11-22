import json, pathlib
p = sorted(pathlib.Path(r"D:\pesquisa de mercado anime\04_scripts_e_hooks").glob("HOOKS_WPM_*.json"))[-1]
data = json.loads(p.read_text(encoding="utf-8"))
videos = data["videos"]
print("video keys:", list(videos[0].keys()))
print()
fails = []
for v in videos:
    ok = v.get("transcript_success")
    if ok is False:
        fails.append(v)
    elif ok is None:
        # fallback heuristics
        if not v.get("hook_text") and not v.get("hook"):
            fails.append(v)
print("total:", len(videos), "| falhas:", len(fails))
for v in fails:
    print("-", v.get("channel"), "|", (v.get("title") or "")[:55], "| id:", v.get("video_id"))
    for key in ("transcript_error", "error", "transcript_extractor", "extractor", "hook_text", "hook"):
        if v.get(key) not in (None, ""):
            print(f"    {key}:", str(v.get(key))[:200])
print("\nsummary_by_channel sample:")
print(json.dumps(data["summary_by_channel"][:2] if isinstance(data["summary_by_channel"], list) else data["summary_by_channel"], ensure_ascii=False, indent=1)[:900])
print("\nchannel_failures:", json.dumps(data["channel_failures"], ensure_ascii=False)[:400])
