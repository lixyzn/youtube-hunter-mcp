import asyncio, json, re, sys
sys.path.insert(0, r"D:\mcp\youtube-hunter-mcp\src")
import httpx
from youtube_hunter_mcp.innertube_transcript import USER_AGENT, _extract_caption_tracks, build_panel_params

FAILING = ["aW7wZfJEMeQ", "2jwMoirRcBQ"]  # Daniel Morais: sem faixa segundo o terminal
WORKING = ["Vt4LEBtzONw"]                   # coolnugget Geto: funciona

async def probe(client, vid):
    html = (await client.get(f"https://www.youtube.com/watch?v={vid}")).text
    has_ck = '"captionTracks"' in html
    m = re.search(r'"captionTracks":(\[.*?\]),"audioTracks"', html, re.S)
    tracks = _extract_caption_tracks(html)
    print(f"\n=== {vid} ===")
    print("  page len:", len(html), "| 'captionTracks' presente:", has_ck, "| regex casou:", bool(m))
    print("  tracks extraidas:", [(t['language_code'], t['is_generated']) for t in tracks][:10])
    # todas as ocorrencias de languageCode no html (amostra)
    codes = re.findall(r'"languageCode":"([a-zA-Z\-]+)"', html)
    print("  languageCode no html (amostra):", sorted(set(codes))[:12])
    if "captionTracks" in html and not m:
        i = html.find('"captionTracks"')
        print("  contexto:", html[i:i+400].replace("\n", " "))
    # tenta o painel
    ver = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', html)
    visitor = re.search(r'"visitorData":"([^"]+)"', html)
    ctx = {"client": {"hl": "en", "gl": "BR", "clientName": "WEB",
                      "clientVersion": ver.group(1) if ver else "2.20261026.01.00",
                      "visitorData": visitor.group(1) if visitor else "", "userAgent": USER_AGENT,
                      "osName": "Windows", "osVersion": "10.0", "platform": "DESKTOP",
                      "browserName": "Chrome", "browserVersion": "140.0.0.0",
                      "timeZone": "America/Sao_Paulo", "originalUrl": f"https://www.youtube.com/watch?v={vid}"}}
    r = await client.post("https://www.youtube.com/youtubei/v1/get_panel?prettyPrint=false",
                          headers={"Content-Type": "application/json", "X-Youtube-Client-Name": "1",
                                   "X-Youtube-Client-Version": ctx["client"]["clientVersion"],
                                   "Origin": "https://www.youtube.com",
                                   "Referer": f"https://www.youtube.com/watch?v={vid}",
                                   "X-Goog-Visitor-Id": visitor.group(1) if visitor else ""},
                          content=json.dumps({"context": ctx, "panelId": "PAmodern_transcript_view",
                                              "params": build_panel_params(vid)}).encode())
    s = r.text
    print("  get_panel:", r.status_code, "| segmentos:", s.count("transcriptSegmentViewModel"))

async def main():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}) as c:
        for vid in FAILING + WORKING:
            await probe(c, vid)

asyncio.run(main())
